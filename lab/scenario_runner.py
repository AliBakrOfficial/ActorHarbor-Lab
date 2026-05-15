from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from typing import Callable

from .automation import ActorSessionStartupError, AutomationEngine
from .chrome_manager import build_launch_command, launch_chrome, profile_data_dir, resolve_url
from .run_history import create_run_record, ensure_artifact_dir, finalize_run_record, write_run_artifacts


def build_scenario_plan(scenario: dict, profiles: list[dict], mode: str) -> list[dict]:
    profile_lookup = {profile["id"]: profile for profile in profiles}
    actor_lookup = {}
    for participant in scenario.get("participants", []):
        profile = deepcopy(profile_lookup[participant["preset_id"]])
        profile["id"] = participant["id"]
        profile["profile_id"] = participant["preset_id"]
        profile["name"] = participant.get("name", profile["name"])
        profile["route"] = participant.get("route", profile["route"])
        profile["launch_mode"] = participant.get("launch_mode", profile["launch_mode"])
        actor_lookup[participant["id"]] = profile

    plan = []
    for step in scenario.get("steps", []):
        actor = actor_lookup.get(step["actor_id"])
        step_mode = step.get("mode", "manual")
        planned_status = "pending"
        if mode == "manual":
            planned_status = "manual"
        elif mode == "assisted" and step_mode == "manual":
            planned_status = "manual"
        plan.append(
            {
                "id": step["id"],
                "title": step["title"],
                "actor_id": step["actor_id"],
                "actor_name": actor.get("name", step["actor_id"]) if actor else step["actor_id"],
                "mode": step_mode,
                "action": step.get("action", ""),
                "guidance": step.get("guidance", ""),
                "assertion": deepcopy(step.get("assertion", {})),
                "route": step.get("route", ""),
                "post_login_route": step.get("post_login_route", ""),
                "selector": step.get("selector", ""),
                "selector_index": step.get("selector_index"),
                "selector_key": step.get("selector_key", ""),
                "wait_for_selector": step.get("wait_for_selector", ""),
                "wait_for_selector_key": step.get("wait_for_selector_key", ""),
                "wait_for_text": step.get("wait_for_text", ""),
                "settle_ms": step.get("settle_ms"),
                "wait_ms": step.get("wait_ms"),
                "remember_as": step.get("remember_as", ""),
                "screenshot": bool(step.get("screenshot")),
                "tab_id": step.get("tab_id", ""),
                "target_tab_id": step.get("target_tab_id", ""),
                "checks": deepcopy(step.get("checks", [])),
                "planned_status": planned_status,
            }
        )
    return plan


class ScenarioRunner:
    def __init__(self, store, app_config: dict, selectors: dict) -> None:
        self.store = store
        self.app_config = app_config
        self.selectors = selectors
        self.engine = AutomationEngine()

    def run(
        self,
        *,
        scenario: dict,
        profiles: list[dict],
        mode: str,
        chrome_data_root: Path,
        chrome_path: str,
        launch_mode_override: str | None = None,
        keep_windows_open: bool = False,
        live_preservation_supported: bool = False,
        reusable_runtime_sessions: list[dict] | None = None,
        event_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        run_record = create_run_record(scenario, mode, scenario.get("project_id", "ncs"))
        artifact_dir = ensure_artifact_dir(run_record)
        plan = build_scenario_plan(scenario, profiles, mode)
        run_record["steps"] = []
        run_record["launch_mode"] = launch_mode_override or scenario.get("launch_mode") or self.app_config.get("default_launch_mode", "browser")
        run_record["options"] = {
            "keep_windows_open": keep_windows_open,
            "launch_mode": run_record["launch_mode"],
            "live_preservation_supported": live_preservation_supported,
        }
        run_record["actor_sessions"] = []
        run_record["best_evidence"] = []
        run_record["inspection_overview"] = {
            "keep_windows_open_requested": keep_windows_open,
            "live_preservation_supported": live_preservation_supported,
            "true_keep_open": False,
            "fallback_reopen_used": False,
        }
        reusable_runtime_by_profile = {
            bundle["runtime"].get("preset_id"): bundle
            for bundle in (reusable_runtime_sessions or [])
            if bundle.get("runtime", {}).get("preset_id")
        }
        self._emit(
            event_callback,
            {
                "type": "scenario_started",
                "scenario_id": run_record["scenario_id"],
                "scenario_name": run_record["scenario_name"],
                "mode": mode,
                "launch_mode": run_record["launch_mode"],
                "keep_windows_open": keep_windows_open,
                "live_preservation_supported": live_preservation_supported,
                "total_steps": len(plan),
            },
        )

        profile_lookup = {profile["id"]: profile for profile in profiles}
        actor_lookup = {}
        for participant in scenario.get("participants", []):
            actor_profile = deepcopy(profile_lookup[participant["preset_id"]])
            actor_profile["participant_id"] = participant["id"]
            actor_profile["name"] = participant.get("name", actor_profile["name"])
            actor_profile["route"] = participant.get("route", actor_profile["route"])
            actor_profile["launch_mode"] = launch_mode_override or participant.get("launch_mode", actor_profile["launch_mode"])
            actor_lookup[participant["id"]] = actor_profile

        launched_sessions = []
        actor_last_urls: dict[str, str] = {}
        actor_runtime_sessions: dict[str, dict] = {}
        previous_actor_id = ""
        for participant in scenario.get("participants", []):
            actor = actor_lookup[participant["id"]]
            url = resolve_url(self.app_config["base_url"], actor.get("route", actor.get("base_route", "#/")))
            actor_last_urls[actor["preset_id"]] = url
            if mode in {"manual", "assisted"}:
                command = build_launch_command(
                    chrome_path=chrome_path,
                    profile_dir=profile_data_dir(chrome_data_root, actor["preset_id"]),
                    url=url,
                    launch_mode=actor.get("launch_mode", "browser"),
                    window_size=self.app_config.get("default_window_size", "1400,940"),
                    new_window=True,
                )
                process = launch_chrome(command)
                launched_sessions.append(
                    {
                        "id": f"{actor['preset_id']}-{process.pid}",
                        "profile_id": actor["preset_id"],
                        "profile_name": actor["name"],
                        "pid": process.pid,
                        "url": url,
                        "launch_mode": actor.get("launch_mode", "browser"),
                        "launched_at": run_record["started_at"],
                    }
                )
                self._emit(
                    event_callback,
                    {
                        "type": "log",
                        "level": "info",
                        "message": f"Launched {actor['name']} in {actor.get('launch_mode', 'browser')} mode at {url}.",
                    },
                )

        active_sessions = self.store.load_active_sessions()
        active_sessions.extend(launched_sessions)
        self.store.save_active_sessions(active_sessions)

        manual_runtime = None
        automation_context = nullcontext(None)
        if self.engine.available and mode != "manual":
            if keep_windows_open and live_preservation_supported:
                manual_runtime = self.engine.start_playwright_runtime(
                    log_callback=lambda message: self._emit(
                        event_callback,
                        {"type": "log", "level": "info", "message": message},
                    ),
                )
                automation_context = nullcontext(manual_runtime["playwright"])
            else:
                automation_context = self.engine.playwright_runtime()

        with automation_context as playwright:
            for index, planned_step in enumerate(plan, start=1):
                actor = actor_lookup.get(planned_step["actor_id"])
                step_result = self._build_step_result(planned_step=planned_step, index=index)
                self._emit_step_event(
                    event_callback,
                    step_result=step_result,
                    total_steps=len(plan),
                    status="running",
                    message=f"Running {planned_step['title']}",
                )

                if mode == "manual":
                    step_result["status"] = "manual"
                    step_result["message"] = planned_step["guidance"] or "Manual operator action required."
                    step_result["reason"] = "manual-mode"
                    step_result["resolution"] = "manual-review"
                    run_record["steps"].append(step_result)
                    self._emit_step_event(
                        event_callback,
                        step_result=step_result,
                        total_steps=len(plan),
                        status=step_result["status"],
                        message=step_result["message"],
                    )
                    continue

                if planned_step["mode"] == "manual":
                    step_result["status"] = "manual"
                    step_result["message"] = planned_step["guidance"] or "Manual confirmation required."
                    step_result["reason"] = "manual-checkpoint"
                    step_result["resolution"] = "manual-review"
                    session = actor_runtime_sessions.get(actor["participant_id"])
                    if planned_step.get("screenshot") and session:
                        screenshot_path = str(
                            self.engine.capture_step_screenshot(
                                page=session["page"],
                                artifact_dir=artifact_dir,
                                step=planned_step,
                                status="manual-review",
                                step_index=index,
                                selectors=self.selectors,
                                timeout_ms=int(self.app_config.get("automation_timeout_ms", 15000)),
                            )
                        )
                        step_result["screenshot"] = screenshot_path
                        step_result["evidence_type"] = "manual-review"
                        step_result["best_evidence"] = True
                        step_result["current_url"] = getattr(session["page"], "url", "")
                    run_record["steps"].append(step_result)
                    self._emit(
                        event_callback,
                        {
                            "type": "log",
                            "level": "warning",
                            "message": f"Manual checkpoint: {planned_step['title']} requires operator confirmation.",
                        },
                    )
                    self._emit_step_event(
                        event_callback,
                        step_result=step_result,
                        total_steps=len(plan),
                        status=step_result["status"],
                        message=step_result["message"],
                    )
                    continue

                if not self.engine.available:
                    step_result["status"] = "blocked"
                    step_result["message"] = self.engine.describe()
                    step_result["reason"] = "automation-backend-unavailable"
                    step_result["resolution"] = "blocked"
                    run_record["steps"].append(step_result)
                    self._emit_step_event(
                        event_callback,
                        step_result=step_result,
                        total_steps=len(plan),
                        status=step_result["status"],
                        message=step_result["message"],
                    )
                    continue

                try:
                    runtime_session, continuity_note = self._ensure_actor_runtime_session(
                        actor=actor,
                        actor_runtime_sessions=actor_runtime_sessions,
                        previous_actor_id=previous_actor_id,
                        playwright=playwright,
                        chrome_path=chrome_path,
                        chrome_data_root=chrome_data_root,
                        runtime_handle=manual_runtime,
                        current_run_bundle_id=f"runtime::{run_record['id']}",
                        reusable_runtime_by_profile=reusable_runtime_by_profile,
                        event_callback=event_callback,
                    )
                    previous_actor_id = actor["participant_id"]
                    self._emit(
                        event_callback,
                        {
                            "type": "log",
                            "level": "info",
                            "message": continuity_note,
                        },
                    )
                    self._initialize_runtime_session(runtime_session)
                    page = self._page_for_step(runtime_session, planned_step)
                    execution = self.engine.execute_step(
                        actor=actor,
                        step={**planned_step, "_step_index": index},
                        page=page,
                        runtime_session=runtime_session,
                        base_url=self.app_config["base_url"],
                        selectors=self.selectors,
                        artifact_dir=artifact_dir,
                        timeout_ms=int(self.app_config.get("automation_timeout_ms", 15000)),
                        log_callback=lambda message: self._emit(
                            event_callback,
                            {"type": "log", "level": "info", "message": message},
                        ),
                    )
                    if isinstance(execution, tuple):
                        status, message = execution
                        execution = {
                            "status": status,
                            "message": message,
                            "reason": "assertion-passed" if status == "passed" else message,
                            "resolution": "executed" if status == "passed" else status,
                        }
                    status = execution.get("status", "failed")
                    message = execution.get("message", "")
                    screenshot_path = ""
                    if planned_step.get("screenshot"):
                        screenshot_path = str(
                            self.engine.capture_step_screenshot(
                                page=page,
                                artifact_dir=artifact_dir,
                                step=planned_step,
                                status=status,
                                step_index=index,
                                selectors=self.selectors,
                                timeout_ms=int(self.app_config.get("automation_timeout_ms", 15000)),
                            )
                        )
                        self._emit(
                            event_callback,
                            {"type": "log", "level": "info", "message": f"Captured success screenshot for {planned_step['title']}."},
                        )
                    step_result["status"] = status
                    step_result["message"] = message
                    step_result["screenshot"] = screenshot_path
                    current_page = self._page_for_step(runtime_session, {})
                    actor_last_urls[actor["preset_id"]] = execution.get("current_url") or current_page.url
                    step_result["current_url"] = execution.get("current_url") or current_page.url
                    step_result["reason"] = execution.get("reason", "assertion-passed")
                    step_result["resolution"] = execution.get("resolution", "executed")
                    step_result["failure_category"] = execution.get("failure_category", "")
                    step_result["artifact"] = execution.get("artifact_path", "")
                    step_result["observations"] = execution.get("observations", {})
                    step_result["evidence_type"] = "routine-step" if screenshot_path else ""
                    step_result["best_evidence"] = self._should_mark_best_evidence(plan=plan, step_index=index - 1, step_result=step_result)
                    runtime_session["steps"].append(planned_step["id"])
                    runtime_session["last_step_index"] = index
                except ActorSessionStartupError as exc:
                    step_result["status"] = "failed"
                    step_result["message"] = str(exc)
                    step_result["reason"] = exc.category
                    step_result["resolution"] = "failed"
                    step_result["failure_category"] = exc.category
                    step_result["evidence_type"] = "failure"
                    step_result["best_evidence"] = True
                    step_result["recovery_candidate"] = bool(exc.recoverable)
                    self._emit(
                        event_callback,
                        {
                            "type": "log",
                            "level": "warning" if exc.recoverable else "error",
                            "message": f"Startup issue for {planned_step['title']} [{exc.category}] on attempt {exc.attempts}.",
                        },
                    )
                except Exception as exc:  # noqa: BLE001 - surface honest operator feedback
                    failure_path = ""
                    failure_artifact = ""
                    failure_observations = {}
                    session = actor_runtime_sessions.get(actor["participant_id"])
                    if session:
                        try:
                            failure_path = str(
                                self.engine.capture_step_screenshot(
                                    page=session["page"],
                                    artifact_dir=artifact_dir,
                                    step=planned_step,
                                    status="failed",
                                    step_index=index,
                                    selectors=self.selectors,
                                    timeout_ms=int(self.app_config.get("automation_timeout_ms", 15000)),
                                )
                            )
                        except Exception:  # noqa: BLE001 - best-effort failure capture only
                            failure_path = ""
                        try:
                            failure_observations = self.engine.capture_state_snapshot(page=session["page"], runtime_session=session)
                            failure_artifact = str(
                                self.engine.write_state_snapshot(
                                    artifact_dir=artifact_dir,
                                    step=planned_step,
                                    step_index=index,
                                    snapshot=failure_observations,
                                    checks=[],
                                    failures=[str(exc)],
                                )
                            )
                        except Exception:  # noqa: BLE001 - failure evidence should stay best-effort
                            failure_observations = {}
                            failure_artifact = ""
                        actor_last_urls[actor["preset_id"]] = getattr(session.get("page"), "url", "") or actor_last_urls.get(actor["preset_id"], "")
                        step_result["current_url"] = actor_last_urls[actor["preset_id"]]
                    step_result["status"] = "failed"
                    step_result["message"] = str(exc)
                    step_result["screenshot"] = failure_path
                    step_result["reason"] = str(exc)
                    step_result["resolution"] = "failed"
                    step_result["failure_category"] = "execution-failed"
                    step_result["artifact"] = failure_artifact
                    step_result["observations"] = failure_observations
                    step_result["evidence_type"] = "failure"
                    step_result["best_evidence"] = True
                    self._emit(
                        event_callback,
                        {"type": "log", "level": "error", "message": f"Step {planned_step['title']} failed: {exc}"},
                    )

                run_record["steps"].append(step_result)
                self._emit_step_event(
                    event_callback,
                    step_result=step_result,
                    total_steps=len(plan),
                    status=step_result["status"],
                    message=step_result["message"],
                )

            if actor_runtime_sessions:
                run_record["actor_sessions"] = []
                for actor_index, session in enumerate(actor_runtime_sessions.values(), start=1):
                    self._initialize_runtime_session(session)
                    active_page = self._page_for_step(session, {})
                    final_url = actor_last_urls.get(session["preset_id"], "")
                    final_screenshot = str(
                        self.engine.capture_actor_state_screenshot(
                            page=active_page,
                            artifact_dir=artifact_dir,
                            actor_slug=session["participant_id"],
                            actor_index=actor_index,
                            timeout_ms=int(self.app_config.get("automation_timeout_ms", 15000)),
                        )
                    )
                    actor_session = {
                        "participant_id": session["participant_id"],
                        "preset_id": session["preset_id"],
                        "actor_name": session["actor_name"],
                        "kind": session.get("kind", "staff"),
                        "launch_mode": session.get("launch_mode", "browser"),
                        "steps": list(session.get("steps", [])),
                        "startup_state": session.get("startup_state", "fresh-launch"),
                        "startup_attempts": session.get("startup_attempts", 1),
                        "startup_recovered": bool(session.get("startup_recovered", False)),
                        "final_url": final_url,
                        "reused": len(session.get("steps", [])) > 1,
                        "kept_open": keep_windows_open,
                        "final_screenshot": final_screenshot,
                        "inspection_state": self._inspection_state_for_actor(
                            keep_windows_open=keep_windows_open,
                            live_preservation_supported=live_preservation_supported,
                        ),
                        "inspection_label": self._inspection_label_for_actor(
                            keep_windows_open=keep_windows_open,
                            live_preservation_supported=live_preservation_supported,
                        ),
                        "auth_state": self._auth_state_for_actor(
                            actor_kind=session.get("kind", "staff"),
                            final_url=final_url,
                            keep_windows_open=keep_windows_open,
                            live_preservation_supported=live_preservation_supported,
                        ),
                        "auth_label": self._auth_label_for_actor(
                            actor_kind=session.get("kind", "staff"),
                            final_url=final_url,
                            keep_windows_open=keep_windows_open,
                            live_preservation_supported=live_preservation_supported,
                        ),
                        "inspectable": bool(keep_windows_open),
                        "fallback_reason": self._fallback_reason_for_actor(
                            actor_kind=session.get("kind", "staff"),
                            keep_windows_open=keep_windows_open,
                            live_preservation_supported=live_preservation_supported,
                        ),
                    }
                    run_record["actor_sessions"].append(actor_session)
                    run_record["best_evidence"].append(
                        {
                            "type": "final-actor-state",
                            "actor": session["actor_name"],
                            "path": final_screenshot,
                            "label": f"{session['actor_name']} final state",
                        }
                    )
                    self._emit(
                        event_callback,
                        {"type": "log", "level": "info", "message": f"Captured final actor-state screenshot for {session['actor_name']}."},
                    )

            for step in run_record["steps"]:
                if step.get("best_evidence") and step.get("screenshot"):
                    run_record["best_evidence"].append(
                        {
                            "type": step.get("evidence_type") or "step",
                            "actor": step["actor"],
                            "path": step["screenshot"],
                            "label": step["title"],
                            "step_id": step["id"],
                        }
                    )

            preserved_runtime_sessions = []
            if keep_windows_open and live_preservation_supported and actor_runtime_sessions:
                preserved_runtime_sessions = list(actor_runtime_sessions.values())
                run_record["inspection_overview"]["true_keep_open"] = True
                self._emit(
                    event_callback,
                    {
                        "type": "log",
                        "level": "info",
                        "message": "Keeping live Playwright actor sessions open for post-run inspection.",
                    },
                )
            elif keep_windows_open and actor_runtime_sessions:
                run_record["inspection_overview"]["fallback_reopen_used"] = True
                reopened_sessions = self._reopen_actor_windows(
                    actor_lookup=actor_lookup,
                    actor_last_urls=actor_last_urls,
                    chrome_data_root=chrome_data_root,
                    chrome_path=chrome_path,
                    started_at=run_record["started_at"],
                    event_callback=event_callback,
                    actor_runtime_sessions=actor_runtime_sessions,
                )
                active_sessions = self.store.load_active_sessions()
                active_sessions.extend(reopened_sessions)
                self.store.save_active_sessions(active_sessions)
                if reopened_sessions:
                    self._emit(
                        event_callback,
                        {
                            "type": "log",
                            "level": "info",
                            "message": f"Reopened {len(reopened_sessions)} actor window(s) as an approximation because live preservation is not available in this execution mode.",
                        },
                    )

            if not (keep_windows_open and live_preservation_supported):
                for runtime_session in actor_runtime_sessions.values():
                    self.engine.close_actor_session(
                        runtime_session,
                        log_callback=lambda message: self._emit(
                            event_callback,
                            {"type": "log", "level": "info", "message": message},
                        ),
                    )

        if manual_runtime and not (keep_windows_open and live_preservation_supported and actor_runtime_sessions):
            self.engine.stop_playwright_runtime(
                manual_runtime,
                log_callback=lambda message: self._emit(
                    event_callback,
                    {"type": "log", "level": "info", "message": message},
                ),
            )

        finalize_run_record(run_record)
        write_run_artifacts(run_record, artifact_dir)

        history = self.store.load_run_history()
        history.insert(0, run_record)
        self.store.save_run_history(history[:50])
        self._emit(
            event_callback,
            {
                "type": "scenario_finished",
                "status": run_record["status"],
                "summary": run_record["summary"],
                "artifact_dir": run_record.get("artifact_dir", ""),
                "run_record": run_record,
                "preserved_runtime_sessions": preserved_runtime_sessions if keep_windows_open and live_preservation_supported else [],
            },
        )
        return run_record

    def _parse_window_size(self, value: str) -> tuple[int, int]:
        parts = [segment.strip() for segment in value.split(",", 1)]
        if len(parts) != 2:
            return (1400, 940)
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            return (1400, 940)

    def _build_step_result(self, *, planned_step: dict, index: int) -> dict:
        return {
            "id": planned_step["id"],
            "title": planned_step["title"],
            "actor": planned_step["actor_name"],
            "action": planned_step.get("action", ""),
            "mode": planned_step.get("mode", "manual"),
            "status": "pending",
            "message": "",
            "reason": "",
            "resolution": "pending",
            "failure_category": "",
            "recovery_candidate": False,
            "recovered": False,
            "recovered_by_step_id": "",
            "recovery_note": "",
            "guidance": planned_step["guidance"],
            "screenshot": "",
            "index": index,
            "current_url": "",
            "artifact": "",
            "observations": {},
            "evidence_type": "",
            "best_evidence": False,
        }

    def _should_mark_best_evidence(self, *, plan: list[dict], step_index: int, step_result: dict) -> bool:
        if step_result["status"] in {"failed", "manual", "blocked"}:
            return True
        if step_result.get("action") in {"staff_login", "patient_qr_login", "patient_create_call"}:
            return True
        next_actor_id = plan[step_index + 1]["actor_id"] if step_index + 1 < len(plan) else ""
        return next_actor_id != plan[step_index]["actor_id"]

    def _emit(self, callback, payload: dict) -> None:
        if callback:
            callback(payload)

    def _emit_step_event(self, callback, *, step_result: dict, total_steps: int, status: str, message: str) -> None:
        self._emit(
            callback,
            {
                "type": "step_update",
                "step_id": step_result["id"],
                "title": step_result["title"],
                "actor": step_result["actor"],
                "status": status,
                "message": message,
                "index": step_result["index"],
                "total_steps": total_steps,
                "screenshot": step_result.get("screenshot", ""),
                "current_url": step_result.get("current_url", ""),
                "artifact": step_result.get("artifact", ""),
                "reason": step_result.get("reason", ""),
                "resolution": step_result.get("resolution", ""),
                "action": step_result.get("action", ""),
            },
        )

    def _initialize_runtime_session(self, runtime_session: dict) -> None:
        runtime_session.setdefault("tabs", {"main": runtime_session["page"]})
        runtime_session.setdefault("active_tab_id", "main")
        runtime_session.setdefault("network_events", [])
        runtime_session.setdefault("state_memory", {})
        runtime_session.setdefault("_observed_pages", set())
        for tab_id, page in runtime_session.get("tabs", {}).items():
            self._attach_page_observers(runtime_session=runtime_session, page=page, tab_id=tab_id)

    def _page_for_step(self, runtime_session: dict, planned_step: dict):
        self._initialize_runtime_session(runtime_session)
        tab_id = planned_step.get("tab_id") or runtime_session.get("active_tab_id") or "main"
        page = runtime_session["tabs"].get(tab_id)
        if page is None:
            raise RuntimeError(f"Tab {tab_id!r} is not available for this actor session.")
        runtime_session["active_tab_id"] = tab_id
        return page

    def _attach_page_observers(self, *, runtime_session: dict, page, tab_id: str) -> None:
        if not hasattr(page, "on"):
            return

        observed_pages = runtime_session.setdefault("_observed_pages", set())
        page_identity = id(page)
        if page_identity in observed_pages:
            return

        def log_request_finished(request):
            try:
                url = request.url
            except Exception:
                return
            if "/api/v1/" not in url and "/broadcasting/auth" not in url and "/app/" not in url and "/sanctum/" not in url:
                return
            response = None
            try:
                response = request.response()
            except Exception:
                response = None
            runtime_session["network_events"] = (
                runtime_session.get("network_events", [])
                + [{
                    "tab_id": tab_id,
                    "kind": "request-finished",
                    "url": url,
                    "method": getattr(request, "method", ""),
                    "status": getattr(response, "status", None),
                }]
            )[-120:]

        def log_request_failed(request):
            try:
                url = request.url
            except Exception:
                return
            if "/api/v1/" not in url and "/broadcasting/auth" not in url and "/app/" not in url and "/sanctum/" not in url:
                return
            failure = None
            try:
                failure = request.failure()
            except Exception:
                failure = None
            runtime_session["network_events"] = (
                runtime_session.get("network_events", [])
                + [{
                    "tab_id": tab_id,
                    "kind": "request-failed",
                    "url": url,
                    "method": getattr(request, "method", ""),
                    "failure": getattr(failure, "error_text", None),
                }]
            )[-120:]

        page.on("requestfinished", log_request_finished)
        page.on("requestfailed", log_request_failed)
        observed_pages.add(page_identity)

    def _ensure_actor_runtime_session(
        self,
        *,
        actor: dict,
        actor_runtime_sessions: dict[str, dict],
        previous_actor_id: str,
        playwright,
        chrome_path: str,
        chrome_data_root: Path,
        runtime_handle: dict | None,
        current_run_bundle_id: str,
        reusable_runtime_by_profile: dict[str, dict],
        event_callback,
    ) -> tuple[dict, str]:
        existing = actor_runtime_sessions.get(actor["participant_id"])
        if existing:
            if previous_actor_id == actor["participant_id"]:
                return existing, f"Reusing the same live page for {actor['name']}."
            return existing, f"Switching back to the existing session for {actor['name']}."

        reusable = reusable_runtime_by_profile.pop(actor["preset_id"], None)
        if reusable:
            session = reusable["runtime"]
            session["actor_name"] = actor["name"]
            session["participant_id"] = actor["participant_id"]
            session["preset_id"] = actor["preset_id"]
            session["kind"] = actor.get("kind", "staff")
            session["steps"] = []
            session["startup_state"] = "reused-live-session"
            session["startup_attempts"] = 0
            session["startup_recovered"] = False
            session["runtime_handle"] = reusable.get("runtime_handle")
            session["runtime_bundle_id"] = reusable.get("runtime_bundle_id", current_run_bundle_id)
            actor_runtime_sessions[actor["participant_id"]] = session
            return session, f"Reusing an already-open preserved session for {actor['name']}."

        viewport = self._parse_window_size(self.app_config.get("default_window_size", "1400,940"))
        session = self.engine.open_actor_session(
            playwright=playwright,
            chrome_path=chrome_path,
            profile_dir=profile_data_dir(chrome_data_root, actor["preset_id"]),
            launch_mode=actor.get("launch_mode", "browser"),
            headless=self.app_config.get("headless_automation", False),
            viewport_size=viewport,
            log_callback=lambda message: self._emit(
                event_callback,
                {"type": "log", "level": "info", "message": message},
            ),
        )
        session["actor_name"] = actor["name"]
        session["participant_id"] = actor["participant_id"]
        session["preset_id"] = actor["preset_id"]
        session["kind"] = actor.get("kind", "staff")
        session["steps"] = []
        session["runtime_handle"] = runtime_handle
        session["runtime_bundle_id"] = current_run_bundle_id
        actor_runtime_sessions[actor["participant_id"]] = session
        if session.get("startup_recovered"):
            return session, f"Opened a new live session for {actor['name']} after recovering from a startup glitch."
        return session, f"Opened a new live session for {actor['name']}."

    def _reopen_actor_windows(
        self,
        *,
        actor_lookup: dict[str, dict],
        actor_last_urls: dict[str, str],
        chrome_data_root: Path,
        chrome_path: str,
        started_at: str,
        event_callback,
        actor_runtime_sessions: dict[str, dict],
    ) -> list[dict]:
        reopened_sessions: list[dict] = []
        for participant_id, runtime_session in actor_runtime_sessions.items():
            actor = actor_lookup[participant_id]
            target_url = actor_last_urls.get(actor["preset_id"]) or resolve_url(
                self.app_config["base_url"],
                actor.get("landing_route") or actor.get("route") or actor.get("base_route", "#/"),
            )
            command = build_launch_command(
                chrome_path=chrome_path,
                profile_dir=profile_data_dir(chrome_data_root, actor["preset_id"]),
                url=target_url,
                launch_mode=actor.get("launch_mode", "browser"),
                window_size=self.app_config.get("default_window_size", "1400,940"),
                new_window=True,
            )
            process = launch_chrome(command)
            reopened_sessions.append(
                {
                    "id": f"{actor['preset_id']}-{process.pid}",
                    "profile_id": actor["preset_id"],
                    "profile_name": actor["name"],
                    "pid": process.pid,
                    "url": target_url,
                    "launch_mode": actor.get("launch_mode", "browser"),
                    "launched_at": started_at,
                }
            )
            self._emit(
                event_callback,
                {
                    "type": "log",
                    "level": "info",
                    "message": f"Kept {actor['name']} open at {target_url} using a standard Chrome window.",
                },
            )
        return reopened_sessions

    def _inspection_state_for_actor(self, *, keep_windows_open: bool, live_preservation_supported: bool) -> str:
        if keep_windows_open and live_preservation_supported:
            return "live-preserved"
        if keep_windows_open:
            return "reopened-approximation"
        return "closed-after-run"

    def _inspection_label_for_actor(self, *, keep_windows_open: bool, live_preservation_supported: bool) -> str:
        if keep_windows_open and live_preservation_supported:
            return "Live preserved session"
        if keep_windows_open:
            return "Reopened approximation"
        return "Closed after run"

    def _auth_state_for_actor(
        self,
        *,
        actor_kind: str,
        final_url: str,
        keep_windows_open: bool,
        live_preservation_supported: bool,
    ) -> str:
        if keep_windows_open and live_preservation_supported:
            if actor_kind != "patient" and self._looks_like_staff_login(final_url):
                return "lost-before-finish"
            if actor_kind == "patient" and self._looks_like_patient_reauth(final_url):
                return "best-effort"
            return "preserved"
        if keep_windows_open:
            if actor_kind == "patient":
                return "best-effort"
            return "not-guaranteed"
        return "closed"

    def _auth_label_for_actor(
        self,
        *,
        actor_kind: str,
        final_url: str,
        keep_windows_open: bool,
        live_preservation_supported: bool,
    ) -> str:
        if keep_windows_open and live_preservation_supported:
            if actor_kind != "patient" and self._looks_like_staff_login(final_url):
                return "Live page preserved, but auth was not preserved"
            if actor_kind == "patient" and self._looks_like_patient_reauth(final_url):
                return "Live page preserved, but patient continuity needs re-entry"
            return "Live authenticated page preserved" if actor_kind != "patient" else "Live session preserved"
        if keep_windows_open:
            if actor_kind == "patient":
                return "Reopened route only; patient continuity is best-effort"
            return "Protected route reopened without preserved auth"
        return "Session closed after run"

    def _looks_like_staff_login(self, final_url: str) -> bool:
        return "/#/staff/login" in final_url or "/staff/login" in final_url

    def _looks_like_patient_reauth(self, final_url: str) -> bool:
        return "/#/patient/scan" in final_url or "/#/patient/session-expired" in final_url

    def _fallback_reason_for_actor(self, *, actor_kind: str, keep_windows_open: bool, live_preservation_supported: bool) -> str:
        if not keep_windows_open or live_preservation_supported:
            return ""
        if actor_kind == "patient":
            return "Live Playwright preservation was not available, so the lab reopened the final route for convenience."
        return "Live Playwright preservation was not available, so the lab reopened the protected route as an approximation and staff authentication was not guaranteed."


class StepExecutionError(RuntimeError):
    def __init__(self, message: str, screenshot_path: str = "", page_url: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.screenshot_path = screenshot_path
        self.page_url = page_url
