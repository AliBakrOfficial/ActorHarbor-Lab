from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import time
from urllib.parse import urlsplit


class AutomationEngine:
    def __init__(self) -> None:
        self.available = False
        self.backend_name = "unavailable"
        self.reason = "Playwright for Python is not installed in this environment."
        self._playwright = None
        self._remembered_snapshots: dict[tuple[str, str, str], dict] = {}
        self._attempt_import()

    def _attempt_import(self) -> None:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return

        self.available = True
        self.backend_name = "playwright"
        self.reason = ""
        self._playwright = {
            "sync_playwright": sync_playwright,
            "timeout_error": PlaywrightTimeoutError,
        }

    def describe(self) -> str:
        if self.available:
            return "Playwright automation is available."
        return self.reason

    def can_automate(self, step: dict) -> bool:
        if not self.available:
            return False
        return step.get("action") in {
            "navigate",
            "staff_login",
            "patient_qr_login",
            "click",
            "patient_create_call",
            "capture_screenshot",
            "open_tab",
            "activate_tab",
            "reload",
            "wait",
            "assert_state",
        }

    @contextmanager
    def playwright_runtime(self):
        runtime = self.start_playwright_runtime()
        try:
            yield runtime["playwright"]
        finally:
            self.stop_playwright_runtime(runtime)

    def start_playwright_runtime(self, log_callback=None) -> dict:
        if not self.available:
            raise RuntimeError(self.reason)
        sync_playwright = self._playwright["sync_playwright"]
        controller = sync_playwright().start()
        self._log(log_callback, "Started Playwright runtime.")
        return {"controller": controller, "playwright": controller}

    def stop_playwright_runtime(self, runtime: dict | None, log_callback=None) -> None:
        if not runtime:
            return
        controller = runtime.get("controller")
        if controller:
            self._log(log_callback, "Stopping Playwright runtime.")
            controller.stop()

    def open_actor_session(
        self,
        *,
        playwright,
        chrome_path: str,
        profile_dir: Path,
        launch_mode: str,
        headless: bool,
        viewport_size: tuple[int, int],
        log_callback=None,
    ) -> dict:
        browser_type = playwright.chromium
        args = ["--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble", "--disable-gpu"]
        max_attempts = 2
        last_error = None
        for attempt in range(1, max_attempts + 1):
            self._log(
                log_callback,
                f"Opening actor session for {profile_dir.name} in {launch_mode} mode (attempt {attempt}/{max_attempts}).",
            )
            try:
                context = self._launch_persistent_context(
                    browser_type=browser_type,
                    profile_dir=profile_dir,
                    chrome_path=chrome_path,
                    headless=headless,
                    viewport_size=viewport_size,
                    args=args,
                )
                page = self._resolve_initial_page(context=context, log_callback=log_callback)
                return {
                    "context": context,
                    "page": page,
                    "profile_dir": profile_dir,
                    "launch_mode": launch_mode,
                    "startup_attempts": attempt,
                    "startup_recovered": attempt > 1,
                    "startup_state": "fresh-launch",
                }
            except Exception as exc:  # noqa: BLE001 - normalize startup failures honestly
                category = self._classify_launch_exception(exc)
                recoverable = category in {"browser-window-not-found", "browser-closed-during-startup"}
                last_error = ActorSessionStartupError(
                    self._format_launch_exception(exc=exc, category=category, attempt=attempt, recoverable=recoverable),
                    category=category,
                    recoverable=recoverable,
                    attempts=attempt,
                    raw_message=str(exc),
                )
                self._log(
                    log_callback,
                    f"Actor session startup failed for {profile_dir.name} [{category}] on attempt {attempt}: {str(exc).splitlines()[0]}",
                )
                if recoverable and attempt < max_attempts:
                    self._log(log_callback, f"Retrying actor session startup for {profile_dir.name} after a short settle delay.")
                    time.sleep(0.35)
                    continue
                raise last_error
        raise last_error or ActorSessionStartupError(
            f"Actor session startup failed for {profile_dir.name}.",
            category="launch-failed",
            recoverable=False,
            attempts=max_attempts,
        )

    def close_actor_session(self, session: dict, log_callback=None) -> None:
        context = session.get("context")
        profile_dir = session.get("profile_dir")
        if context:
            self._log(log_callback, f"Closing actor session for {getattr(profile_dir, 'name', 'profile')}.")
            context.close()

    def execute_step(
        self,
        *,
        actor: dict,
        step: dict,
        page,
        runtime_session=None,
        base_url: str,
        selectors: dict,
        artifact_dir: Path,
        timeout_ms: int = 15000,
        log_callback=None,
    ) -> dict:
        action = step.get("action")
        if action == "navigate":
            target_url = _resolve_url(base_url, step.get("route") or actor.get("route") or actor.get("base_route") or "#/")
            if page.url == target_url and (
                not step.get("assertion") or self._assertion_satisfied(page=page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms)
            ):
                self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Target already satisfied; skipping navigate.")
                return {
                    "status": "passed",
                    "message": f"Target already satisfied at {page.url}",
                    "reason": "route-already-satisfied",
                    "resolution": "skipped-because-already-satisfied",
                }
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Navigating to {target_url}")
            page.goto(target_url, wait_until="domcontentloaded")
            is_patient_route = self._is_patient_route_auth_step(actor=actor, target_url=target_url)
            if is_patient_route:
                if not self._stabilize_patient_session(
                    page=page,
                    actor=actor,
                    assertion=step.get("assertion", {}),
                    base_url=base_url,
                    runtime_session=runtime_session,
                    timeout_ms=timeout_ms,
                    ):
                        raise RuntimeError(
                            f"Patient session did not stabilize after navigating {actor.get('name', actor.get('id', 'actor'))} to {target_url}. Final URL: {page.url}"
                        )
            try:
                self._wait_for_step_target(page=page, step=step, selectors=selectors, timeout_ms=timeout_ms)
                if step.get("assertion"):
                    self._wait_for_assertion(page=page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms)
            except Exception:
                if not is_patient_route or not self._retry_patient_route_recovery(
                    page=page,
                    actor=actor,
                    target_url=target_url,
                    selectors=selectors,
                    step=step,
                    base_url=base_url,
                    runtime_session=runtime_session,
                    timeout_ms=timeout_ms,
                    log_callback=log_callback,
                ):
                    raise
            if self._is_staff_route_auth_step(actor=actor, target_url=target_url):
                if not self._stabilize_staff_authenticated_surface(
                    actor=actor,
                    page=page,
                    runtime_session=runtime_session,
                    step=step,
                    selectors=selectors,
                    target_url=target_url,
                    timeout_ms=timeout_ms,
                ):
                    raise RuntimeError(
                        f"Staff authenticated shell did not stabilize after navigating {actor.get('name', actor.get('id', 'actor'))} to {target_url}. Final URL: {page.url}"
                    )
            if is_patient_route:
                if not self._stabilize_patient_session(
                    page=page,
                    actor=actor,
                    assertion=step.get("assertion", {}),
                    base_url=base_url,
                    runtime_session=runtime_session,
                    timeout_ms=timeout_ms,
                ):
                    raise RuntimeError(
                        f"Patient session did not stabilize after navigating {actor.get('name', actor.get('id', 'actor'))} to {target_url}. Final URL: {page.url}"
                    )
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Navigation target became ready.")
            resolution = "executed"
            if page.url != target_url and self._assertion_satisfied(page=page, assertion=step.get("assertion", {}), timeout_ms=1200):
                resolution = "resolved-by-auth-aware-branch"
            return {
                "status": "passed",
                "message": f"Navigated to {target_url}",
                "reason": "assertion-passed",
                "resolution": resolution,
            }

        if action == "staff_login":
            login_url = _resolve_url(base_url, step.get("route") or actor.get("route") or "#/staff/login")
            protected_route = step.get("post_login_route") or actor.get("landing_route") or ""
            protected_url = _resolve_url(base_url, protected_route) if protected_route else login_url
            actor_name = actor.get("name", actor.get("id", "actor"))
            if self._is_staff_authenticated_for_step(page=page, step=step, protected_url=protected_url, timeout_ms=1500):
                if not self._stabilize_staff_authenticated_surface(
                    actor=actor,
                    page=page,
                    runtime_session=runtime_session,
                    step=step,
                    selectors=selectors,
                    target_url=protected_url,
                    timeout_ms=timeout_ms,
                ):
                    raise RuntimeError(
                        f"Staff authenticated shell did not stabilize for {actor_name} on an already-reachable protected surface. Final URL: {page.url}"
                    )
                self._log(log_callback, f"[{actor_name}] Login form absent and actor is already authenticated on a valid protected surface.")
                return {
                    "status": "passed",
                    "message": f"Already authenticated as {actor_name}; no login form was needed.",
                    "reason": "already-authenticated",
                    "resolution": "skipped-because-already-authenticated",
                }

            probe_target = protected_url if protected_route else login_url
            self._log(log_callback, f"[{actor_name}] Probing protected target at {probe_target}")
            page.goto(probe_target, wait_until="domcontentloaded")
            self._wait_for_step_target(page=page, step=step, selectors=selectors, timeout_ms=min(timeout_ms, 6000), optional=True)
            page.wait_for_timeout(min(1200, self._step_settle_ms(step) + 400))
            login_selectors = selectors.get("staff_login", {})
            if not self._login_form_visible(page=page, selectors=login_selectors, timeout_ms=600) and self._is_staff_authenticated_for_step(
                page=page,
                step=step,
                protected_url=protected_url,
                timeout_ms=1500,
            ):
                if not self._stabilize_staff_authenticated_surface(
                    actor=actor,
                    page=page,
                    runtime_session=runtime_session,
                    step=step,
                    selectors=selectors,
                    target_url=protected_url,
                    timeout_ms=timeout_ms,
                ):
                    raise RuntimeError(
                        f"Staff authenticated shell did not stabilize for {actor_name} after reaching the protected surface without a login form. Final URL: {page.url}"
                    )
                self._log(log_callback, f"[{actor_name}] Protected target reached without showing the login form.")
                return {
                    "status": "passed",
                    "message": f"Reached the protected surface for {actor_name} without a new login.",
                    "reason": "protected-surface-already-reachable",
                    "resolution": "resolved-by-auth-aware-branch",
                }

            self._log(log_callback, f"[{actor_name}] Resetting to the plain login route before submitting credentials.")
            page.goto(login_url, wait_until="domcontentloaded")
            self._wait_for_step_target(page=page, step=step, selectors=selectors, timeout_ms=min(timeout_ms, 6000), optional=True)
            if not self._login_form_visible(page=page, selectors=login_selectors, timeout_ms=2000):
                raise RuntimeError("Login form was not present and the protected surface was not reachable.")

            response_status = self._execute_staff_login_submission(
                actor=actor,
                actor_name=actor_name,
                page=page,
                login_url=login_url,
                login_selectors=login_selectors,
                timeout_ms=timeout_ms,
                log_callback=log_callback,
            )
            if response_status is not None and response_status >= 400:
                raise RuntimeError(f"Staff login request returned HTTP {response_status} for {actor_name}. Final URL: {page.url}")
            post_login_assertion = {"type": "url_contains", "value": protected_route} if protected_route else step.get("assertion", {})
            if not self._stabilize_staff_authentication(
                actor=actor,
                page=page,
                runtime_session=runtime_session,
                step=step,
                selectors=selectors,
                login_url=login_url,
                protected_url=protected_url,
                assertion=post_login_assertion,
                timeout_ms=timeout_ms,
            ):
                raise RuntimeError(
                    f"Staff authentication did not stabilize on the protected surface for {actor_name}. Final URL: {page.url}"
                )
            self._log(log_callback, f"[{actor_name}] Login assertion passed after shell stabilization.")
            return {
                "status": "passed",
                "message": f"Logged in as {actor_name}",
                "reason": "login-executed",
                "resolution": "executed",
            }

        if action == "patient_qr_login":
            target_url = _resolve_url(base_url, step.get("route") or actor.get("route") or "#/patient/scan")
            if self._assertion_satisfied(page=page, assertion=step.get("assertion", {}), timeout_ms=1200):
                self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Patient session is already active; skipping QR submission.")
                return {
                    "status": "passed",
                    "message": f"Patient session is already active for {actor.get('name', actor.get('id', 'actor'))}.",
                    "reason": "already-authenticated",
                    "resolution": "skipped-because-already-satisfied",
                }
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Opening patient QR flow at {target_url}")
            page.goto(target_url, wait_until="domcontentloaded")
            scan_selectors = selectors.get("patient_scan", {})
            manual_trigger = scan_selectors.get("manual_trigger")
            token_selector = scan_selectors.get("token", 'input[type="text"]')
            if manual_trigger and not self._selector_visible(page=page, selector=token_selector, timeout_ms=800):
                page.locator(manual_trigger).click()
                self._selector_visible(page=page, selector=token_selector, timeout_ms=2500)
            page.locator(token_selector).first.fill(actor.get("qr_token", ""))
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Submitting patient QR token.")
            page.locator(scan_selectors.get("submit", 'button[type="submit"]')).first.click()
            if not self._stabilize_patient_session(
                page=page,
                actor=actor,
                assertion=step.get("assertion", {}),
                base_url=base_url,
                runtime_session=runtime_session,
                timeout_ms=timeout_ms,
            ):
                if not self._retry_patient_qr_login_if_bootstrap_failed(
                    page=page,
                    actor=actor,
                    target_url=target_url,
                    selectors=selectors,
                    assertion=step.get("assertion", {}),
                    base_url=base_url,
                    runtime_session=runtime_session,
                    timeout_ms=timeout_ms,
                    log_callback=log_callback,
                ):
                    raise RuntimeError(
                        f"Patient session did not stabilize on an authenticated surface for {actor.get('name', actor.get('id', 'actor'))}. Final URL: {page.url}"
                    )
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Patient session assertion passed after shell stabilization.")
            return {
                "status": "passed",
                "message": f"Started patient session for {actor.get('name', actor.get('id', 'actor'))}",
                "reason": "patient-session-started",
                "resolution": "executed",
            }

        if action == "click":
            selector = self._resolve_selector(step, selectors)
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Clicking {selector}")
            locator = page.locator(selector)
            selector_index = step.get("selector_index")
            target = locator.first
            if selector_index not in (None, "") and hasattr(locator, "nth"):
                try:
                    target = locator.nth(int(selector_index))
                except Exception:
                    target = locator.first
            target.click()
            self._wait_for_assertion(page=page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms)
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Click assertion passed.")
            return {
                "status": "passed",
                "message": f"Clicked {selector}",
                "reason": "click-executed",
                "resolution": "executed",
            }

        if action == "patient_create_call":
            target_url = _resolve_url(base_url, step.get("route") or actor.get("route") or "#/patient/services")
            if self._assertion_satisfied(page=page, assertion=step.get("assertion", {}), timeout_ms=1200):
                self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Patient call status is already visible; skipping duplicate creation.")
                return {
                    "status": "passed",
                    "message": "Patient call is already on the status surface.",
                    "reason": "call-already-created",
                    "resolution": "skipped-because-already-satisfied",
                }
            if "/#/patient/services" not in page.url:
                self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Opening patient services at {target_url}")
                page.goto(target_url, wait_until="domcontentloaded")
            if not self._stabilize_patient_session(
                page=page,
                actor=actor,
                assertion={"type": "url_contains", "value": "/#/patient/services"},
                base_url=base_url,
                runtime_session=runtime_session,
                timeout_ms=timeout_ms,
            ):
                raise RuntimeError(
                    f"Patient session did not remain stable before creating a call for {actor.get('name', actor.get('id', 'actor'))}. Final URL: {page.url}"
                )
            service_selectors = selectors.get("patient_services", {})
            page.locator(service_selectors.get("service_card", ".patient-service-card")).first.wait_for(state="visible", timeout=timeout_ms)
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Selecting the first patient service card.")
            page.locator(service_selectors.get("service_card", ".patient-service-card")).first.click()
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Confirming the service request dialog.")
            page.locator(service_selectors.get("confirm_submit", ".q-dialog .bg-primary")).first.click()
            self._wait_for_assertion(page=page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms)
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Patient call creation assertion passed.")
            return {
                "status": "passed",
                "message": "Created a patient service call and reached the call status page.",
                "reason": "call-created",
                "resolution": "executed",
            }

        if action == "capture_screenshot":
            file_path = self.capture_step_screenshot(
                page=page,
                artifact_dir=artifact_dir,
                step=step,
                status="passed",
                step_index=step.get("_step_index", 0),
                selectors=selectors,
                timeout_ms=timeout_ms,
            )
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Captured screenshot {file_path.name}")
            return {
                "status": "passed",
                "message": f"Captured screenshot {file_path.name}",
                "reason": "screenshot-captured",
                "resolution": "executed",
            }

        if action == "open_tab":
            if runtime_session is None:
                return {
                    "status": "blocked",
                    "message": "Runtime session is required to open a new tab.",
                    "reason": "missing-runtime-session",
                    "resolution": "blocked",
                }

            context = runtime_session.get("context")
            if context is None:
                raise RuntimeError("Actor session does not expose a browser context for opening tabs.")

            target_url = _resolve_url(base_url, step.get("route") or actor.get("route") or actor.get("base_route") or "#/")
            tab_id = step.get("target_tab_id") or step.get("tab_id") or f"tab-{len(runtime_session.get('tabs', {})) + 1}"
            new_page = context.new_page()
            if hasattr(new_page, "bring_to_front"):
                try:
                    new_page.bring_to_front()
                except Exception:
                    pass
            new_page.goto(target_url, wait_until="domcontentloaded")
            self._wait_for_step_target(page=new_page, step=step, selectors=selectors, timeout_ms=timeout_ms, optional=True)
            self._wait_for_assertion(page=new_page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms)
            if self._is_staff_route_auth_step(actor=actor, target_url=target_url):
                if not self._stabilize_staff_authenticated_surface(
                    actor=actor,
                    page=new_page,
                    runtime_session=runtime_session,
                    step=step,
                    selectors=selectors,
                    target_url=target_url,
                    timeout_ms=timeout_ms,
                ):
                    raise RuntimeError(
                        f"Staff authenticated shell did not stabilize after opening tab {tab_id} for {actor.get('name', actor.get('id', 'actor'))}. Final URL: {new_page.url}"
                    )
            self._register_session_page(runtime_session, tab_id, new_page)
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Opened tab {tab_id} at {target_url}")
            return {
                "status": "passed",
                "message": f"Opened tab {tab_id} at {target_url}",
                "reason": "tab-opened",
                "resolution": "executed",
                "current_url": new_page.url,
            }

        if action == "activate_tab":
            if runtime_session is None:
                return {
                    "status": "blocked",
                    "message": "Runtime session is required to activate a tab.",
                    "reason": "missing-runtime-session",
                    "resolution": "blocked",
                }

            tab_id = step.get("tab_id") or "main"
            tab_page = self._page_for_tab(runtime_session, tab_id)
            if tab_page is None:
                raise RuntimeError(f"Tab {tab_id!r} is not available for this actor session.")
            if hasattr(tab_page, "bring_to_front"):
                tab_page.bring_to_front()
            tab_page.wait_for_timeout(self._step_settle_ms(step))
            runtime_session["active_tab_id"] = tab_id
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Activated tab {tab_id}")
            return {
                "status": "passed",
                "message": f"Activated tab {tab_id}",
                "reason": "tab-activated",
                "resolution": "executed",
                "current_url": getattr(tab_page, "url", ""),
            }

        if action == "reload":
            if hasattr(page, "bring_to_front"):
                try:
                    page.bring_to_front()
                except Exception:
                    pass
            page.reload(wait_until="domcontentloaded")
            self._wait_for_step_target(page=page, step=step, selectors=selectors, timeout_ms=timeout_ms, optional=True)
            self._wait_for_assertion(page=page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms)
            if self._is_staff_route_auth_step(actor=actor, target_url=page.url):
                if not self._stabilize_staff_authenticated_surface(
                    actor=actor,
                    page=page,
                    runtime_session=runtime_session,
                    step=step,
                    selectors=selectors,
                    target_url=page.url,
                    timeout_ms=timeout_ms,
                ):
                    raise RuntimeError(
                        f"Staff authenticated shell did not stabilize after reloading {actor.get('name', actor.get('id', 'actor'))}. Final URL: {page.url}"
                    )
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Reloaded {page.url}")
            return {
                "status": "passed",
                "message": f"Reloaded {page.url}",
                "reason": "page-reloaded",
                "resolution": "executed",
                "current_url": page.url,
            }

        if action == "wait":
            wait_ms = int(step.get("wait_ms", step.get("settle_ms", 800)) or 800)
            page.wait_for_timeout(wait_ms)
            return {
                "status": "passed",
                "message": f"Waited {wait_ms}ms",
                "reason": "wait-complete",
                "resolution": "executed",
                "current_url": getattr(page, "url", ""),
            }

        if action == "assert_state":
            snapshot = self.capture_state_snapshot(page=page, runtime_session=runtime_session)
            checks = step.get("checks", [])
            failures = self._evaluate_state_checks(
                snapshot=snapshot,
                page=page,
                checks=checks,
                runtime_session=runtime_session,
                memory_scope={
                    "artifact_dir": str(artifact_dir),
                    "actor_name": actor.get("name", actor.get("id", "actor")),
                },
            )
            remember_key = str(step.get("remember_as", "") or "").strip()
            if remember_key:
                if runtime_session is not None:
                    runtime_session.setdefault("state_memory", {})[remember_key] = snapshot
                page_memory = getattr(page, "_actorharbor_state_memory", None)
                if not isinstance(page_memory, dict):
                    page_memory = {}
                    setattr(page, "_actorharbor_state_memory", page_memory)
                page_memory[remember_key] = snapshot
                self._remembered_snapshots[(str(artifact_dir), actor.get("name", actor.get("id", "actor")), remember_key)] = snapshot
            file_path = self.write_state_snapshot(
                artifact_dir=artifact_dir,
                step=step,
                step_index=step.get("_step_index", 0),
                snapshot=snapshot,
                checks=checks,
                failures=failures,
            )
            status = "passed" if not failures else "failed"
            return {
                "status": status,
                "message": "State checks passed." if not failures else "; ".join(failures),
                "reason": "state-assertions-passed" if not failures else "state-assertions-failed",
                "resolution": "executed" if not failures else "failed",
                "current_url": snapshot.get("url", getattr(page, "url", "")),
                "artifact_path": str(file_path),
                "observations": snapshot,
            }

        return {
            "status": "blocked",
            "message": f"Unsupported automated action: {action}",
            "reason": "unsupported-action",
            "resolution": "blocked",
        }

    def run_with_context(self, *, chrome_path: str, profile_dir: Path, launch_mode: str, headless: bool, viewport_size: tuple[int, int], runner, log_callback=None):
        if not self.available:
            raise RuntimeError(self.reason)

        sync_playwright = self._playwright["sync_playwright"]
        args = ["--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble"]
        with sync_playwright() as playwright:
            browser_type = playwright.chromium
            self._log(log_callback, f"Launching persistent browser context for {profile_dir.name} in {launch_mode} mode.")
            context = browser_type.launch_persistent_context(
                user_data_dir=str(profile_dir),
                executable_path=chrome_path or None,
                headless=headless,
                viewport={"width": viewport_size[0], "height": viewport_size[1]},
                args=args,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                return runner(context, page)
            finally:
                self._log(log_callback, f"Closing browser context for {profile_dir.name}.")
                context.close()

    def _resolve_selector(self, step: dict, selectors: dict) -> str:
        if step.get("selector"):
            return step["selector"]
        selector_key = step.get("selector_key", "")
        if not selector_key:
            raise ValueError("Step does not define a selector or selector_key.")
        group, key = selector_key.split(".", 1)
        return selectors[group][key]

    def _wait_for_step_target(self, *, page, step: dict, selectors: dict, timeout_ms: int, optional: bool = False) -> None:
        selector = step.get("wait_for_selector")
        try:
            if selector:
                page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
                return
            selector_key = step.get("wait_for_selector_key")
            if selector_key:
                page.locator(self._resolve_selector({"selector_key": selector_key}, selectors)).first.wait_for(state="visible", timeout=timeout_ms)
                return
            wait_for_text = step.get("wait_for_text", "")
            if wait_for_text:
                page.locator("body").wait_for(state="visible", timeout=timeout_ms)
                page.wait_for_function(
                    """(expected) => document.body && document.body.innerText.includes(expected)""",
                    arg=wait_for_text,
                    timeout=timeout_ms,
                )
        except Exception:
            if not optional:
                raise

    def _wait_for_assertion(self, *, page, assertion: dict, timeout_ms: int) -> None:
        if not assertion:
            return
        assertion_type = assertion.get("type")
        value = assertion.get("value", "")
        if assertion_type == "url_contains":
            page.wait_for_function(
                """
                (expected) => {
                  const normalizeRoute = (value) => {
                    if (!value) return ''
                    return value.startsWith('/#/') ? value.slice(1) : value
                  }
                  const current = window.location.href || ''
                  const hashIndex = current.indexOf('#')
                  const effectiveRoute = hashIndex >= 0
                    ? '#'+ current.slice(hashIndex + 1).split('?')[0]
                    : current.split('?')[0]
                  return normalizeRoute(effectiveRoute).includes(normalizeRoute(expected))
                }
                """,
                arg=value,
                timeout=timeout_ms,
            )
            return
        if assertion_type == "body_contains":
            page.locator("body").wait_for(state="visible", timeout=timeout_ms)
            page.wait_for_function(
                """(expected) => document.body && document.body.innerText.includes(expected)""",
                arg=value,
                timeout=timeout_ms,
            )
            return
        if assertion_type == "selector_visible":
            page.locator(value).first.wait_for(state="visible", timeout=timeout_ms)

    def _assertion_satisfied(self, *, page, assertion: dict, timeout_ms: int) -> bool:
        if not assertion:
            return False
        try:
            self._wait_for_assertion(page=page, assertion=assertion, timeout_ms=timeout_ms)
        except Exception:
            return False
        return True

    def _is_step_already_satisfied(self, *, page, step: dict, target_url: str, timeout_ms: int) -> bool:
        assertion = step.get("assertion", {})
        if assertion and self._assertion_satisfied(page=page, assertion=assertion, timeout_ms=timeout_ms):
            return True
        return bool(target_url and page.url == target_url)

    def _is_staff_authenticated_for_step(self, *, page, step: dict, protected_url: str, timeout_ms: int) -> bool:
        if self._looks_like_staff_login_url(page.url):
            return False
        if protected_url and page.url == protected_url:
            return True
        return self._assertion_satisfied(page=page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms)

    def _login_form_visible(self, *, page, selectors: dict, timeout_ms: int) -> bool:
        email_selector = selectors.get("email", 'input[type="email"]')
        password_selector = selectors.get("password", 'input[type="password"]')
        try:
            page.locator(email_selector).first.wait_for(state="visible", timeout=timeout_ms)
            page.locator(password_selector).first.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            return False
        return True

    def _looks_like_staff_login_url(self, current_url: str) -> bool:
        effective_route = self._effective_route(current_url)
        normalized_route = self._normalize_route_fragment(effective_route)
        return "#/staff/login" in normalized_route or normalized_route.endswith("/staff/login")

    def _looks_like_patient_reauth_url(self, current_url: str) -> bool:
        effective_route = self._effective_route(current_url)
        normalized_route = self._normalize_route_fragment(effective_route)
        return "#/patient/scan" in normalized_route or "#/patient/session-expired" in normalized_route

    def _classify_auth_surface(self, current_url: str) -> str:
        if self._looks_like_staff_login_url(current_url):
            return "staff-login"
        effective_route = self._normalize_route_fragment(self._effective_route(current_url))
        if "#/patient/session-expired" in effective_route:
            return "patient-session-expired"
        if "#/patient/scan" in effective_route:
            return "patient-scan"
        if "#/" in effective_route:
            return "app-surface"
        return "unknown"

    def _effective_route(self, current_url: str) -> str:
        if not current_url:
            return ""
        split = urlsplit(current_url)
        if split.fragment:
            fragment = split.fragment.split("?", 1)[0]
            return f"#{fragment if fragment.startswith('/') else f'/{fragment}'}"
        return split.path.split("?", 1)[0]

    def _normalize_route_fragment(self, value: str) -> str:
        if value.startswith("/#/"):
            return value[1:]
        return value

    def _stabilize_staff_authentication(
        self,
        *,
        actor: dict,
        page,
        runtime_session,
        step: dict,
        selectors: dict,
        login_url: str,
        protected_url: str,
        assertion: dict,
        timeout_ms: int,
    ) -> bool:
        deadline = time.time() + (timeout_ms / 1000)
        login_selectors = selectors.get("staff_login", {})
        probed_protected = False
        while time.time() < deadline:
            if self._stabilize_staff_authenticated_surface(
                actor=actor,
                page=page,
                runtime_session=runtime_session,
                step={**step, "assertion": assertion},
                selectors=selectors,
                target_url=protected_url,
                timeout_ms=900,
            ):
                return True
            if (
                not self._login_form_visible(page=page, selectors=login_selectors, timeout_ms=300)
                and not self._looks_like_staff_login_url(page.url)
            ):
                if protected_url and not probed_protected:
                    try:
                        page.goto(protected_url, wait_until="domcontentloaded")
                        probed_protected = True
                    except Exception:
                        pass
                if self._stabilize_staff_authenticated_surface(
                    actor=actor,
                    page=page,
                    runtime_session=runtime_session,
                    step={**step, "assertion": assertion},
                    selectors=selectors,
                    target_url=protected_url,
                    timeout_ms=1200,
                ):
                    return True
            elif self._looks_like_staff_login_url(page.url) and page.url != login_url:
                try:
                    page.goto(login_url, wait_until="domcontentloaded")
                except Exception:
                    pass
            try:
                page.wait_for_load_state("domcontentloaded", timeout=800)
            except Exception:
                pass
            page.wait_for_timeout(250)
        return False

    def _stabilize_patient_session(
        self,
        *,
        page,
        actor: dict,
        assertion: dict,
        base_url: str,
        runtime_session,
        timeout_ms: int,
    ) -> bool:
        deadline = time.time() + (timeout_ms / 1000)
        landing_url = _resolve_url(base_url, actor.get("landing_route") or "#/patient/welcome")
        services_url = _resolve_url(base_url, "#/patient/services")
        while time.time() < deadline:
            snapshot = self._safe_capture_state_snapshot(page=page, runtime_session=runtime_session)
            if snapshot and self._patient_surface_is_stable(page=page, snapshot=snapshot, assertion=assertion, timeout_ms=min(timeout_ms, 900)):
                return True
            if snapshot and not self._looks_like_patient_reauth_url(snapshot.get("url", "")):
                try:
                    page.wait_for_load_state("networkidle", timeout=900)
                except Exception:
                    pass
                page.wait_for_timeout(250)
                snapshot = self._safe_capture_state_snapshot(page=page, runtime_session=runtime_session)
                if snapshot and self._patient_surface_is_stable(page=page, snapshot=snapshot, assertion=assertion, timeout_ms=min(timeout_ms, 900)):
                    return True
            for probe_url in (landing_url, services_url):
                try:
                    page.goto(probe_url, wait_until="domcontentloaded")
                except Exception:
                    continue
                snapshot = self._safe_capture_state_snapshot(page=page, runtime_session=runtime_session)
                if snapshot and self._patient_surface_is_stable(page=page, snapshot=snapshot, assertion=assertion, timeout_ms=min(timeout_ms, 900)):
                    return True
            try:
                page.wait_for_load_state("domcontentloaded", timeout=800)
            except Exception:
                pass
            page.wait_for_timeout(250)
        return False

    def _retry_patient_qr_login_if_bootstrap_failed(
        self,
        *,
        page,
        actor: dict,
        target_url: str,
        selectors: dict,
        assertion: dict,
        base_url: str,
        runtime_session,
        timeout_ms: int,
        log_callback=None,
    ) -> bool:
        if not self._patient_bootstrap_looks_retryable(page=page, runtime_session=runtime_session):
            return False
        self._log(
            log_callback,
            f"[{actor.get('name', actor.get('id', 'actor'))}] Patient bootstrap hit expired/session-init failure signals; clearing transient browser state and retrying once.",
        )
        self._clear_patient_browser_state(page=page)
        page.goto(target_url, wait_until="domcontentloaded")
        scan_selectors = selectors.get("patient_scan", {})
        manual_trigger = scan_selectors.get("manual_trigger")
        token_selector = scan_selectors.get("token", 'input[type="text"]')
        if manual_trigger and not self._selector_visible(page=page, selector=token_selector, timeout_ms=800):
            page.locator(manual_trigger).click()
            self._selector_visible(page=page, selector=token_selector, timeout_ms=2500)
        page.locator(token_selector).first.fill(actor.get("qr_token", ""))
        page.locator(scan_selectors.get("submit", 'button[type="submit"]')).first.click()
        return self._stabilize_patient_session(
            page=page,
            actor=actor,
            assertion=assertion,
            base_url=base_url,
            runtime_session=runtime_session,
            timeout_ms=timeout_ms,
        )

    def _retry_patient_route_recovery(
        self,
        *,
        page,
        actor: dict,
        target_url: str,
        selectors: dict,
        step: dict,
        base_url: str,
        runtime_session,
        timeout_ms: int,
        log_callback=None,
    ) -> bool:
        if not self._retry_patient_qr_login_if_bootstrap_failed(
            page=page,
            actor=actor,
            target_url=_resolve_url(base_url, actor.get("route") or "#/patient/scan"),
            selectors=selectors,
            assertion={"type": "url_contains", "value": "/#/patient/welcome"},
            base_url=base_url,
            runtime_session=runtime_session,
            timeout_ms=timeout_ms,
            log_callback=log_callback,
        ):
            return False
        self._log(
            log_callback,
            f"[{actor.get('name', actor.get('id', 'actor'))}] Recovered patient session; reopening {target_url} once.",
        )
        page.goto(target_url, wait_until="domcontentloaded")
        if not self._stabilize_patient_session(
            page=page,
            actor=actor,
            assertion=step.get("assertion", {}),
            base_url=base_url,
            runtime_session=runtime_session,
            timeout_ms=timeout_ms,
        ):
            return False
        self._wait_for_step_target(page=page, step=step, selectors=selectors, timeout_ms=timeout_ms)
        if step.get("assertion"):
            self._wait_for_assertion(page=page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms)
        return True

    def _patient_bootstrap_looks_retryable(self, *, page, runtime_session) -> bool:
        snapshot = self._safe_capture_state_snapshot(page=page, runtime_session=runtime_session)
        if not snapshot:
            return False
        if snapshot.get("auth_surface") not in {"patient-session-expired", "patient-scan"}:
            return False
        recent_auth_events = snapshot.get("recent_auth_events", [])
        return any(
            event.get("kind") == "request-failed"
            and any(fragment in event.get("url", "") for fragment in ("/sanctum/", "/patient/session/init"))
            for event in recent_auth_events
        )

    def _clear_patient_browser_state(self, *, page) -> None:
        context = getattr(page, "context", None)
        if context and callable(getattr(context, "clear_cookies", None)):
            try:
                context.clear_cookies()
            except Exception:
                pass
        if hasattr(page, "evaluate"):
            try:
                page.evaluate(
                    """() => {
                      window.localStorage?.clear?.()
                      window.sessionStorage?.clear?.()
                    }"""
                )
            except Exception:
                pass

    def _execute_staff_login_submission(
        self,
        *,
        actor: dict,
        actor_name: str,
        page,
        login_url: str,
        login_selectors: dict,
        timeout_ms: int,
        log_callback=None,
    ) -> int | None:
        for attempt in range(1, 3):
            try:
                self._settle_staff_login_surface(page=page, login_selectors=login_selectors, timeout_ms=timeout_ms)
                self._log(log_callback, f"[{actor_name}] Login form detected; filling staff credentials (attempt {attempt}/2).")
                page.locator(login_selectors.get("email", 'input[type="email"]')).first.fill(actor.get("login_email", ""))
                page.locator(login_selectors.get("password", 'input[type="password"]')).first.fill(actor.get("login_password", ""))
                self._log(log_callback, f"[{actor_name}] Submitting staff credentials.")
                response_status = self._submit_staff_login_with_response(
                    page=page,
                    submit_selector=login_selectors.get("submit", 'button[type="submit"]'),
                    timeout_ms=timeout_ms,
                )
            except Exception as exc:
                if attempt == 1 and "execution context was destroyed" in str(exc).lower():
                    self._log(log_callback, f"[{actor_name}] Login surface navigated mid-submit; resetting and retrying once.")
                    page.goto(login_url, wait_until="domcontentloaded")
                    continue
                raise
            if response_status is not None:
                self._log(log_callback, f"[{actor_name}] Staff login response completed with status {response_status}.")
                return response_status
            if attempt == 1 and self._login_form_visible(page=page, selectors=login_selectors, timeout_ms=1000):
                self._log(
                    log_callback,
                    f"[{actor_name}] Staff login request did not complete cleanly; retrying once after resetting the login surface.",
                )
                page.goto(login_url, wait_until="domcontentloaded")
                continue
            return response_status
        return None

    def _settle_staff_login_surface(self, *, page, login_selectors: dict, timeout_ms: int) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 2000))
        except Exception:
            pass
        if not self._login_form_visible(page=page, selectors=login_selectors, timeout_ms=min(timeout_ms, 2000)):
            raise RuntimeError("Login form was not stable enough for credential submission.")
        try:
            page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 1500))
        except Exception:
            pass
        page.wait_for_timeout(250)

    def _submit_staff_login_with_response(self, *, page, submit_selector: str, timeout_ms: int) -> int | None:
        if hasattr(page, "expect_response"):
            try:
                with page.expect_response(
                    lambda response: "/api/v1/auth/session/login" in response.url and getattr(response.request, "method", "") == "POST",
                    timeout=timeout_ms,
                ) as response_info:
                    page.locator(submit_selector).first.click()
                response = response_info.value
                return getattr(response, "status", None)
            except Exception:
                pass
        page.locator(submit_selector).first.click()
        return None

    def capture_step_screenshot(
        self,
        *,
        page,
        artifact_dir: Path,
        step: dict,
        status: str,
        step_index: int,
        selectors: dict,
        timeout_ms: int,
    ) -> Path:
        self._stabilize_for_screenshot(page=page, step=step, selectors=selectors, timeout_ms=timeout_ms)
        filename = f"{step_index:02d}-{step['id']}-{status}.png"
        file_path = artifact_dir / filename
        page.screenshot(path=str(file_path), full_page=True)
        return file_path

    def capture_actor_state_screenshot(
        self,
        *,
        page,
        artifact_dir: Path,
        actor_slug: str,
        actor_index: int,
        timeout_ms: int,
    ) -> Path:
        self._stabilize_for_screenshot(page=page, step={"assertion": {}, "wait_for_selector": ""}, selectors={}, timeout_ms=timeout_ms)
        file_path = artifact_dir / f"actor-{actor_index:02d}-{actor_slug}-final-state.png"
        page.screenshot(path=str(file_path), full_page=True)
        return file_path

    def _stabilize_for_screenshot(self, *, page, step: dict, selectors: dict, timeout_ms: int) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:  # noqa: BLE001 - best-effort screenshot stability
            return

        target_selector = step.get("wait_for_selector")
        if not target_selector and step.get("wait_for_selector_key"):
            target_selector = self._resolve_selector({"selector_key": step["wait_for_selector_key"]}, selectors)

        if not target_selector:
            assertion = step.get("assertion", {})
            if assertion.get("type") == "selector_visible":
                target_selector = assertion.get("value")

        if target_selector:
            try:
                page.locator(target_selector).first.wait_for(state="visible", timeout=timeout_ms)
            except Exception:  # noqa: BLE001 - fall back to general settle
                pass

        assertion = step.get("assertion", {})
        if assertion.get("type") == "body_contains":
            try:
                page.locator("body").wait_for(state="visible", timeout=timeout_ms)
                page.wait_for_function(
                    """(expected) => document.body && document.body.innerText.includes(expected)""",
                    arg=assertion.get("value", ""),
                    timeout=timeout_ms,
                )
            except Exception:  # noqa: BLE001 - settle should stay best-effort
                pass

        wait_for_text = step.get("wait_for_text", "")
        if wait_for_text:
            try:
                page.wait_for_function(
                    """(expected) => document.body && document.body.innerText.includes(expected)""",
                    arg=wait_for_text,
                    timeout=timeout_ms,
                )
            except Exception:  # noqa: BLE001 - settle should stay best-effort
                pass

        try:
            page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 2500))
        except Exception:  # noqa: BLE001 - networkidle is helpful but not mandatory
            pass
        page.wait_for_timeout(self._step_settle_ms(step))

    def _step_settle_ms(self, step: dict) -> int:
        try:
            value = int(step.get("settle_ms", 250) or 250)
        except (TypeError, ValueError):
            value = 250
        return max(100, min(value, 2000))

    def _register_session_page(self, runtime_session: dict, tab_id: str, page) -> None:
        tabs = runtime_session.setdefault("tabs", {})
        tabs[tab_id] = page
        runtime_session["active_tab_id"] = tab_id

    def _page_for_tab(self, runtime_session: dict | None, tab_id: str | None):
        if runtime_session is None:
            return None
        tabs = runtime_session.get("tabs", {})
        return tabs.get(tab_id or runtime_session.get("active_tab_id") or "main")

    def capture_state_snapshot(self, *, page, runtime_session=None) -> dict:
        snapshot = {
            "url": getattr(page, "url", ""),
            "auth_surface": self._classify_auth_surface(getattr(page, "url", "")),
            "staff_shell_visible": False,
            "staff_login_form_visible": False,
            "staff_user_hint_present": False,
            "staff_auth_mode_hint_present": False,
            "patient_session_hint_present": False,
            "visibility_state": "unknown",
            "hidden": None,
            "notification_texts": [],
            "lifecycle_banner_texts": [],
            "highlighted_call_ids": [],
            "call_card_ids": [],
            "call_card_texts": [],
            "calls_badge_texts": [],
            "local_storage_keys": [],
            "session_storage_keys": [],
            "cookie_names": [],
            "session_cookie_names": [],
            "active_tab_id": runtime_session.get("active_tab_id") if runtime_session else None,
            "known_tabs": sorted((runtime_session or {}).get("tabs", {}).keys()) if runtime_session else [],
            "network_events": list((runtime_session or {}).get("network_events", []))[-12:],
            "recent_auth_events": [],
        }

        if not hasattr(page, "evaluate"):
            return snapshot

        data = page.evaluate(
            """() => {
              const notifications = Array.from(document.querySelectorAll('.q-notification'))
                .map((node) => (node.innerText || '').trim())
                .filter(Boolean)
              const lifecycleBanners = Array.from(document.querySelectorAll('.staff-shell-layout__lifecycle-cta'))
                .map((node) => (node.innerText || '').trim())
                .filter(Boolean)
              const highlightedCards = Array.from(document.querySelectorAll('.operational-call-card--highlighted'))
              const callCards = Array.from(document.querySelectorAll('[id^="operational-call-"]'))
              const callsBadges = Array.from(document.querySelectorAll('.staff-shell-layout__nav-button--calls .q-badge'))
                .map((node) => (node.innerText || '').trim())
                .filter(Boolean)
              return {
                url: window.location.href,
                staffShellVisible: Boolean(document.querySelector('.staff-shell-layout')),
                staffLoginFormVisible: Boolean(
                  document.querySelector('input[type="email"], input[name="email"], input[autocomplete="username"]')
                    && document.querySelector('input[type="password"], input[name="password"], input[autocomplete="current-password"]')
                ),
                visibilityState: document.visibilityState,
                hidden: document.hidden,
                notifications,
                lifecycleBanners,
                highlightedCallIds: highlightedCards
                  .map((node) => Number((node.id || '').replace('operational-call-', '')) || null)
                  .filter((value) => value !== null),
                callCardIds: callCards
                  .map((node) => Number((node.id || '').replace('operational-call-', '')) || null)
                  .filter((value) => value !== null),
                callCardTexts: callCards.map((node) => (node.innerText || '').trim()).filter(Boolean).slice(0, 12),
                callsBadges,
                localStorageKeys: Object.keys(window.localStorage || {}).sort(),
                sessionStorageKeys: Object.keys(window.sessionStorage || {}).sort(),
                staffUserHintPresent: Boolean(window.localStorage?.getItem('ncs.staff.user')),
                staffAuthModeHintPresent: Boolean(window.localStorage?.getItem('ncs.staff.auth_mode')),
                patientSessionHintPresent: Boolean(window.localStorage?.getItem('ncs.patient.session')),
              }
            }"""
        )
        snapshot.update(
            {
                "url": data.get("url", snapshot["url"]),
                "auth_surface": self._classify_auth_surface(data.get("url", snapshot["url"])),
                "staff_shell_visible": bool(data.get("staffShellVisible")),
                "staff_login_form_visible": bool(data.get("staffLoginFormVisible")),
                "staff_user_hint_present": bool(data.get("staffUserHintPresent")),
                "staff_auth_mode_hint_present": bool(data.get("staffAuthModeHintPresent")),
                "patient_session_hint_present": bool(data.get("patientSessionHintPresent")),
                "visibility_state": data.get("visibilityState", "unknown"),
                "hidden": data.get("hidden"),
                "notification_texts": data.get("notifications", []),
                "lifecycle_banner_texts": data.get("lifecycleBanners", []),
                "highlighted_call_ids": data.get("highlightedCallIds", []),
                "call_card_ids": data.get("callCardIds", []),
                "call_card_texts": data.get("callCardTexts", []),
                "calls_badge_texts": data.get("callsBadges", []),
                "local_storage_keys": data.get("localStorageKeys", []),
                "session_storage_keys": data.get("sessionStorageKeys", []),
            }
        )
        context = getattr(page, "context", None)
        if context and callable(getattr(context, "cookies", None)):
            try:
                cookies = context.cookies()
                cookie_names = sorted({item.get("name", "") for item in cookies if item.get("name")})
                session_cookie_names = sorted(
                    {
                        item.get("name", "")
                        for item in cookies
                        if item.get("name")
                        and (
                            "session" in item.get("name", "").lower()
                            or "xsrf" in item.get("name", "").lower()
                            or "csrf" in item.get("name", "").lower()
                        )
                    }
                )
                snapshot["cookie_names"] = cookie_names
                snapshot["session_cookie_names"] = session_cookie_names
            except Exception:
                pass
        snapshot["recent_auth_events"] = [
            event
            for event in snapshot.get("network_events", [])
            if any(
                fragment in event.get("url", "")
                for fragment in ("/sanctum/", "/auth/session/", "/broadcasting/auth", "/patient/session/")
            )
        ]
        return snapshot

    def write_state_snapshot(self, *, artifact_dir: Path, step: dict, step_index: int, snapshot: dict, checks: list[dict], failures: list[str]) -> Path:
        import json

        file_path = artifact_dir / f"{step_index:02d}-{step['id']}-state.json"
        file_path.write_text(
            json.dumps(
                {
                    "step_id": step["id"],
                    "title": step.get("title", step["id"]),
                    "checks": checks,
                    "failures": failures,
                    "snapshot": snapshot,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return file_path

    def _evaluate_state_checks(self, *, snapshot: dict, page, checks: list[dict], runtime_session=None, memory_scope=None) -> list[str]:
        failures: list[str] = []
        for check in checks or []:
            kind = check.get("kind")
            value = check.get("value")

            if kind == "url_contains":
                effective_route = self._normalize_route_fragment(self._effective_route(snapshot.get("url", "")))
                expected_route = self._normalize_route_fragment(str(value))
                if expected_route not in effective_route:
                    failures.append(f"url does not contain {value!r}")
                continue

            if kind == "visibility_state":
                if snapshot.get("visibility_state") != value:
                    failures.append(f"visibility_state was {snapshot.get('visibility_state')!r}, expected {value!r}")
                continue

            if kind == "selector_visible":
                if not self._selector_visible(page=page, selector=str(value), timeout_ms=1200):
                    failures.append(f"selector not visible: {value}")
                continue

            if kind == "selector_absent":
                if self._selector_visible(page=page, selector=str(value), timeout_ms=800):
                    failures.append(f"selector unexpectedly visible: {value}")
                continue

            if kind == "text_present":
                haystack = "\n".join(
                    snapshot.get("notification_texts", [])
                    + snapshot.get("lifecycle_banner_texts", [])
                    + snapshot.get("call_card_texts", [])
                )
                if value not in haystack:
                    failures.append(f"text not present: {value}")
                continue

            if kind == "text_absent":
                haystack = "\n".join(
                    snapshot.get("notification_texts", [])
                    + snapshot.get("lifecycle_banner_texts", [])
                    + snapshot.get("call_card_texts", [])
                )
                if value in haystack:
                    failures.append(f"text unexpectedly present: {value}")
                continue

            if kind == "highlighted_count_exact":
                if len(snapshot.get("highlighted_call_ids", [])) != int(value):
                    failures.append(
                        f"highlighted count was {len(snapshot.get('highlighted_call_ids', []))}, expected {int(value)}"
                    )
                continue

            if kind == "highlighted_count_at_least":
                if len(snapshot.get("highlighted_call_ids", [])) < int(value):
                    failures.append(
                        f"highlighted count was {len(snapshot.get('highlighted_call_ids', []))}, expected at least {int(value)}"
                    )
                continue

            if kind == "badge_count_exact":
                actual = self._sum_numeric_text(snapshot.get("calls_badge_texts", []))
                if actual != int(value):
                    failures.append(f"calls badge count was {actual}, expected {int(value)}")
                continue

            if kind == "badge_count_matches_memory":
                baseline = self._snapshot_from_memory(
                    page=page,
                    runtime_session=runtime_session,
                    key=str(value),
                    memory_scope=memory_scope,
                )
                if baseline is None:
                    failures.append(f"baseline snapshot not found: {value}")
                    continue
                actual = self._sum_numeric_text(snapshot.get("calls_badge_texts", []))
                expected = self._sum_numeric_text(baseline.get("calls_badge_texts", []))
                if actual != expected:
                    failures.append(f"calls badge count was {actual}, expected baseline {expected} from {value}")
                continue

            if kind == "badge_count_at_least":
                actual = self._sum_numeric_text(snapshot.get("calls_badge_texts", []))
                if actual < int(value):
                    failures.append(f"calls badge count was {actual}, expected at least {int(value)}")
                continue

            if kind == "call_cards_count_at_least":
                if len(snapshot.get("call_card_ids", [])) < int(value):
                    failures.append(f"call card count was {len(snapshot.get('call_card_ids', []))}, expected at least {int(value)}")
                continue

            failures.append(f"unsupported state check: {kind}")

        return failures

    def _selector_visible(self, *, page, selector: str, timeout_ms: int) -> bool:
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            return False
        return True

    def _sum_numeric_text(self, values: list[str]) -> int:
        total = 0
        for value in values:
            stripped = "".join(character for character in str(value) if character.isdigit())
            if stripped:
                total += int(stripped)
        return total

    def _snapshot_from_memory(self, *, page, runtime_session, key: str, memory_scope=None) -> dict | None:
        if runtime_session is not None:
            remembered = runtime_session.get("state_memory", {}).get(key)
            if remembered is not None:
                return remembered
        page_memory = getattr(page, "_actorharbor_state_memory", None)
        if isinstance(page_memory, dict):
            remembered = page_memory.get(key)
            if remembered is not None:
                return remembered
        if isinstance(memory_scope, dict):
            scoped = self._remembered_snapshots.get(
                (
                    memory_scope.get("artifact_dir", ""),
                    memory_scope.get("actor_name", ""),
                    key,
                )
            )
            if scoped is not None:
                return scoped
        return None

    def _is_staff_route_auth_step(self, *, actor: dict, target_url: str) -> bool:
        if actor.get("kind", "staff") == "patient":
            return False
        if self._looks_like_staff_login_url(target_url):
            return False
        effective_route = self._normalize_route_fragment(self._effective_route(target_url))
        return effective_route.startswith("#/")

    def _is_patient_route_auth_step(self, *, actor: dict, target_url: str) -> bool:
        if actor.get("kind", "staff") != "patient":
            return False
        effective_route = self._normalize_route_fragment(self._effective_route(target_url))
        return effective_route.startswith("#/patient/") and "#/patient/scan" not in effective_route

    def _stabilize_staff_authenticated_surface(
        self,
        *,
        actor: dict,
        page,
        runtime_session,
        step: dict,
        selectors: dict,
        target_url: str,
        timeout_ms: int,
    ) -> bool:
        deadline = time.time() + (timeout_ms / 1000)
        reprobed_target = False
        while time.time() < deadline:
            snapshot = self._safe_capture_state_snapshot(page=page, runtime_session=runtime_session)
            if snapshot is None:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=800)
                except Exception:
                    pass
                page.wait_for_timeout(250)
                continue
            if self._staff_surface_is_stable(page=page, snapshot=snapshot, step=step, timeout_ms=min(timeout_ms, 900)):
                self._wait_for_step_target(page=page, step=step, selectors=selectors, timeout_ms=1500, optional=True)
                return True
            if target_url and self._looks_like_staff_login_url(snapshot.get("url", "")) and not reprobed_target:
                try:
                    page.goto(target_url, wait_until="domcontentloaded")
                    reprobed_target = True
                except Exception:
                    pass
            try:
                page.wait_for_load_state("domcontentloaded", timeout=800)
            except Exception:
                pass
            page.wait_for_timeout(250)
        return False

    def _staff_surface_is_stable(self, *, page, snapshot: dict, step: dict, timeout_ms: int) -> bool:
        if snapshot.get("auth_surface") == "staff-login":
            return False
        if step.get("assertion") and not self._assertion_satisfied(page=page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms):
            return False
        if snapshot.get("staff_login_form_visible"):
            return False
        if not (
            snapshot.get("staff_shell_visible")
            or snapshot.get("staff_user_hint_present")
            or snapshot.get("staff_auth_mode_hint_present")
        ):
            return False
        if not (
            snapshot.get("staff_user_hint_present")
            or snapshot.get("session_cookie_names")
        ):
            return False
        return True

    def _patient_surface_is_stable(self, *, page, snapshot: dict, assertion: dict, timeout_ms: int) -> bool:
        if snapshot.get("auth_surface") in {"patient-scan", "patient-session-expired"}:
            return False
        if assertion and not self._assertion_satisfied(page=page, assertion=assertion, timeout_ms=timeout_ms):
            return False
        if snapshot.get("patient_session_hint_present"):
            return True
        recent_auth_events = snapshot.get("recent_auth_events", [])
        has_patient_session_event = any("/patient/session/" in event.get("url", "") for event in recent_auth_events)
        if snapshot.get("session_cookie_names") and has_patient_session_event:
            return True
        return False

    def _safe_capture_state_snapshot(self, *, page, runtime_session=None) -> dict | None:
        try:
            return self.capture_state_snapshot(page=page, runtime_session=runtime_session)
        except Exception:
            return None

    def _launch_persistent_context(self, *, browser_type, profile_dir: Path, chrome_path: str, headless: bool, viewport_size: tuple[int, int], args: list[str]):
        return browser_type.launch_persistent_context(
            user_data_dir=str(profile_dir),
            executable_path=chrome_path or None,
            headless=headless,
            viewport={"width": viewport_size[0], "height": viewport_size[1]},
            args=args,
        )

    def _resolve_initial_page(self, *, context, log_callback=None):
        deadline = time.time() + 1.2
        while time.time() < deadline:
            if context.pages:
                page = context.pages[0]
                self._log(log_callback, f"Attached to an existing page at {getattr(page, 'url', 'about:blank')}.")
                return page
            time.sleep(0.08)
        self._log(log_callback, "No page was attached during startup; opening a new page explicitly.")
        return context.new_page()

    def _classify_launch_exception(self, exc: Exception) -> str:
        message = str(exc)
        lowered = message.lower()
        if "browser window not found" in lowered:
            return "browser-window-not-found"
        if "target page, context or browser has been closed" in lowered:
            return "browser-closed-during-startup"
        if "user data directory is already in use" in lowered or "profile appears to be in use" in lowered:
            return "profile-in-use"
        return "launch-failed"

    def _format_launch_exception(self, *, exc: Exception, category: str, attempt: int, recoverable: bool) -> str:
        prefix = "Recoverable actor-session startup issue" if recoverable else "Actor-session startup failed"
        return f"{prefix} [{category}] on attempt {attempt}: {exc}"

    def _log(self, callback, message: str) -> None:
        if callback:
            callback(message)


def _resolve_url(base_url: str, route: str) -> str:
    if route.startswith("http://") or route.startswith("https://"):
        return route
    base = base_url.rstrip("/")
    if route.startswith("#"):
        return f"{base}/{route}"
    if route.startswith("/"):
        return f"{base}{route}"
    return f"{base}/{route}"


class ActorSessionStartupError(RuntimeError):
    def __init__(self, message: str, *, category: str, recoverable: bool, attempts: int, raw_message: str = "") -> None:
        super().__init__(message)
        self.category = category
        self.recoverable = recoverable
        self.attempts = attempts
        self.raw_message = raw_message or message
