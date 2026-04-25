from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import time


class AutomationEngine:
    def __init__(self) -> None:
        self.available = False
        self.backend_name = "unavailable"
        self.reason = "Playwright for Python is not installed in this environment."
        self._playwright = None
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
            self._wait_for_step_target(page=page, step=step, selectors=selectors, timeout_ms=timeout_ms)
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
            if self._is_staff_authenticated_for_step(page=page, step=step, protected_url=protected_url, timeout_ms=1500):
                self._log(log_callback, f"[{actor_name}] Protected target reached without showing the login form.")
                return {
                    "status": "passed",
                    "message": f"Reached the protected surface for {actor_name} without a new login.",
                    "reason": "protected-surface-already-reachable",
                    "resolution": "resolved-by-auth-aware-branch",
                }

            login_selectors = selectors.get("staff_login", {})
            if not self._login_form_visible(page=page, selectors=login_selectors, timeout_ms=2000):
                raise RuntimeError("Login form was not present and the protected surface was not reachable.")

            self._log(log_callback, f"[{actor_name}] Login form detected; filling staff credentials.")
            page.locator(login_selectors.get("email", 'input[type="email"]')).first.fill(actor.get("login_email", ""))
            page.locator(login_selectors.get("password", 'input[type="password"]')).first.fill(actor.get("login_password", ""))
            self._log(log_callback, f"[{actor_name}] Submitting staff credentials.")
            page.locator(login_selectors.get("submit", 'button[type="submit"]')).first.click()
            post_login_assertion = step.get("assertion", {}) or ({"type": "url_contains", "value": protected_route} if protected_route else {})
            self._wait_for_assertion(page=page, assertion=post_login_assertion, timeout_ms=timeout_ms)
            self._wait_for_step_target(page=page, step=step, selectors=selectors, timeout_ms=min(timeout_ms, 6000), optional=True)
            self._log(log_callback, f"[{actor_name}] Login assertion passed.")
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
            if manual_trigger:
                page.locator(manual_trigger).click()
            page.locator(scan_selectors.get("token", 'input[type="text"]')).first.fill(actor.get("qr_token", ""))
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Submitting patient QR token.")
            page.locator(scan_selectors.get("submit", 'button[type="submit"]')).first.click()
            self._wait_for_assertion(page=page, assertion=step.get("assertion", {}), timeout_ms=timeout_ms)
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Patient session assertion passed.")
            return {
                "status": "passed",
                "message": f"Started patient session for {actor.get('name', actor.get('id', 'actor'))}",
                "reason": "patient-session-started",
                "resolution": "executed",
            }

        if action == "click":
            selector = self._resolve_selector(step, selectors)
            self._log(log_callback, f"[{actor.get('name', actor.get('id', 'actor'))}] Clicking {selector}")
            page.locator(selector).first.click()
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
            service_selectors = selectors.get("patient_services", {})
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
                """(expected) => window.location.href.includes(expected)""",
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
        return "/#/staff/login" in current_url or "/staff/login" in current_url

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
