import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lab.automation.engine import ActorSessionStartupError, AutomationEngine
from lab.config_store import LabConfigStore
from lab.defaults import DEFAULT_APP_CONFIG
from lab.run_history import delete_run_artifact_dir, finalize_run_record, prune_run_history, write_run_artifacts
from run_notification_audit import ensure_environment_ready
from lab.scenario_runner import ScenarioRunner, build_scenario_plan


class _FakeLocator:
    def __init__(self, page=None, selector="") -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def wait_for(self, **_kwargs):
        if self.page and self.selector and self.selector not in self.page.visible_selectors:
            raise RuntimeError(f"Selector not visible: {self.selector}")
        return None

    def fill(self, value):
        if self.page is not None:
            self.page.fills[self.selector] = value
        return None

    def click(self):
        if self.page is not None:
            self.page.handle_click(self.selector)
        return None


class _FakePage:
    def __init__(self) -> None:
        self.saved_paths = []
        self.url = "about:blank"
        self.visible_selectors = set()
        self.body_text = ""
        self.fills = {}
        self.route_behaviors = {}
        self.submit_redirect = ""
        self.post_submit_route_behaviors = {}
        self.last_wait_timeout = 0
        self.event_handlers = {}
        self.visibility_state = "visible"
        self.hidden = False
        self.notification_texts = []
        self.lifecycle_banner_texts = []
        self.highlighted_call_ids = []
        self.call_card_ids = []
        self.call_card_texts = []
        self.calls_badges = []
        self.local_storage_keys = []
        self.session_storage_keys = []
        self.context = None
        self.timeout_hooks = []

    def wait_for_load_state(self, *_args, **_kwargs):
        return None

    def locator(self, selector):
        return _FakeLocator(self, selector)

    def wait_for_timeout(self, ms):
        self.last_wait_timeout = ms
        if self.timeout_hooks:
            hook = self.timeout_hooks.pop(0)
            hook()
        return None

    def screenshot(self, *, path, **_kwargs):
        Path(path).write_text("fake image", encoding="utf-8")
        self.saved_paths.append(path)

    def on(self, event_name, handler):
        self.event_handlers.setdefault(event_name, []).append(handler)

    def bring_to_front(self):
        self.visibility_state = "visible"
        self.hidden = False
        if self.context:
            for page in self.context.pages:
                if page is self:
                    continue
                page.visibility_state = "hidden"
                page.hidden = True

    def goto(self, url, **_kwargs):
        behavior = self.route_behaviors.get(url, {})
        self.url = behavior.get("url", url)
        self.visible_selectors = set(behavior.get("visible_selectors", set()))
        self.body_text = behavior.get("body_text", self.body_text)
        return None

    def reload(self, **_kwargs):
        return None

    def wait_for_function(self, _script, arg=None, timeout=None):
        if arg and arg in self.url:
            return None
        if arg and arg in self.body_text:
            return None
        raise RuntimeError(f"Condition not satisfied for {arg}")

    def evaluate(self, script):
        if "localStorage?.clear" in script:
            self.local_storage_keys = []
            self.session_storage_keys = []
            return None
        return {
            "url": self.url,
            "staffShellVisible": ".staff-shell-layout" in self.visible_selectors,
            "staffLoginFormVisible": 'input[type="email"]' in self.visible_selectors and 'input[type="password"]' in self.visible_selectors,
            "visibilityState": self.visibility_state,
            "hidden": self.hidden,
            "notifications": list(self.notification_texts),
            "lifecycleBanners": list(self.lifecycle_banner_texts),
            "highlightedCallIds": list(self.highlighted_call_ids),
            "callCardIds": list(self.call_card_ids),
            "callCardTexts": list(self.call_card_texts),
            "callsBadges": list(self.calls_badges),
            "localStorageKeys": list(self.local_storage_keys),
            "sessionStorageKeys": list(self.session_storage_keys),
            "staffUserHintPresent": "ncs.staff.user" in self.local_storage_keys,
            "staffAuthModeHintPresent": "ncs.staff.auth_mode" in self.local_storage_keys,
            "patientSessionHintPresent": "ncs.patient.session" in self.local_storage_keys,
        }

    def handle_click(self, selector):
        if selector == 'button[type="submit"]' and self.submit_redirect:
            self.url = self.submit_redirect
            self.visible_selectors = set()
            self.body_text = "Protected page"
            for route, behavior in self.post_submit_route_behaviors.items():
                self.route_behaviors[route] = dict(behavior)


class _FakeContext:
    def __init__(self) -> None:
        first = _FakePage()
        first.context = self
        self.pages = [first]
        self.cookie_items = []

    def new_page(self):
        page = _FakePage()
        page.context = self
        self.pages.append(page)
        return page

    def cookies(self):
        return list(self.cookie_items)

    def clear_cookies(self):
        self.cookie_items = []


class LabHardeningTests(unittest.TestCase):
    def _workspace_temp_dir(self) -> Path:
        root = Path.cwd() / "runtime" / "test-artifacts"
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"case-{uuid.uuid4().hex}"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def test_default_app_config_includes_operator_hardening_options(self):
        self.assertIn("keep_windows_open_after_run", DEFAULT_APP_CONFIG)
        self.assertIn("artifacts_open_after_run", DEFAULT_APP_CONFIG)

    def test_build_scenario_plan_preserves_remember_as_metadata(self):
        scenario = {
            "participants": [{"id": "nurse", "preset_id": "nurse-er"}],
            "steps": [
                {
                    "id": "baseline",
                    "title": "Capture baseline",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "remember_as": "outside_calls_baseline",
                }
            ],
        }
        profiles = [{"id": "nurse-er", "name": "Nurse ER", "preset_id": "nurse-er", "route": "#/staff/login", "launch_mode": "browser"}]

        plan = build_scenario_plan(scenario, profiles, "automated")

        self.assertEqual("outside_calls_baseline", plan[0]["remember_as"])

    def test_operator_run_options_persist_in_app_config(self):
        store = LabConfigStore()
        original = store.load_app_config()
        try:
            config = dict(original)
            config["keep_windows_open_after_run"] = True
            config["artifacts_open_after_run"] = True
            store.save_app_config(config)

            reloaded = store.load_app_config()
            self.assertTrue(reloaded["keep_windows_open_after_run"])
            self.assertTrue(reloaded["artifacts_open_after_run"])
        finally:
            store.save_app_config(original)

    def test_prune_run_history_can_delete_artifacts_inside_lab_root(self):
        tmp = self._workspace_temp_dir()
        try:
            artifact_root = Path(tmp) / "artifacts"
            artifact_dir = artifact_root / "20260425-120000" / "demo"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "summary.json").write_text("{}", encoding="utf-8")
            history = [{"id": "demo-1", "artifact_dir": str(artifact_dir)}]

            with patch("lab.run_history.ARTIFACTS_DIR", artifact_root):
                kept, removed = prune_run_history(history, ["demo-1"], delete_artifacts=True)

            self.assertEqual([], kept)
            self.assertEqual(1, removed)
            self.assertFalse(artifact_dir.exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_delete_run_artifact_dir_rejects_paths_outside_lab_root(self):
        tmp = self._workspace_temp_dir()
        try:
            artifact_root = Path(tmp) / "artifacts"
            artifact_root.mkdir(parents=True)
            outside = Path(tmp) / "outside-artifact"
            outside.mkdir(parents=True)

            with patch("lab.run_history.ARTIFACTS_DIR", artifact_root):
                with self.assertRaises(ValueError):
                    delete_run_artifact_dir(outside)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_capture_step_screenshot_uses_index_and_status_in_file_name(self):
        engine = AutomationEngine()
        page = _FakePage()
        tmp = self._workspace_temp_dir()
        try:
            screenshot = engine.capture_step_screenshot(
                page=page,
                artifact_dir=tmp,
                step={"id": "admin-login", "assertion": {}, "wait_for_selector": ""},
                status="passed",
                step_index=3,
                selectors={},
                timeout_ms=1000,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual("03-admin-login-passed.png", screenshot.name)

    def test_staff_login_skips_when_actor_is_already_authenticated(self):
        engine = AutomationEngine()
        page = _FakePage()
        context = _FakeContext()
        context.cookie_items = [
            {"name": "XSRF-TOKEN"},
            {"name": "ncs_session"},
        ]
        page.context = context
        page.url = "http://127.0.0.1:9200/#/admin/beds"
        page.local_storage_keys = ["ncs.staff.user", "ncs.staff.auth_mode"]
        page.visible_selectors = {".staff-shell-layout"}
        result = engine.execute_step(
            actor={"name": "Admin", "landing_route": "#/admin/beds", "login_email": "admin@test", "login_password": "x"},
            step={
                "id": "admin-login",
                "action": "staff_login",
                "route": "#/staff/login",
                "post_login_route": "#/admin/beds",
                "assertion": {"type": "url_contains", "value": "/#/admin/beds"},
            },
            page=page,
            base_url="http://127.0.0.1:9200",
            selectors={"staff_login": {"email": 'input[type="email"]', "password": 'input[type="password"]', "submit": 'button[type="submit"]'}},
            artifact_dir=Path.cwd(),
            timeout_ms=1000,
        )
        self.assertEqual("passed", result["status"])
        self.assertEqual("skipped-because-already-authenticated", result["resolution"])

    def test_staff_login_executes_when_login_form_is_present(self):
        engine = AutomationEngine()
        page = _FakePage()
        context = _FakeContext()
        context.cookie_items = [
            {"name": "XSRF-TOKEN"},
            {"name": "ncs_session"},
        ]
        page.context = context
        protected_url = "http://127.0.0.1:9200/#/admin/beds"
        redirect_login_url = "http://127.0.0.1:9200/#/staff/login?redirect=/admin/beds"
        plain_login_url = "http://127.0.0.1:9200/#/staff/login"
        page.route_behaviors[protected_url] = {
            "url": redirect_login_url,
            "visible_selectors": {'input[type="email"]', 'input[type="password"]', 'button[type="submit"]'},
            "body_text": "Login",
        }
        page.route_behaviors[plain_login_url] = {
            "url": plain_login_url,
            "visible_selectors": {'input[type="email"]', 'input[type="password"]', 'button[type="submit"]'},
            "body_text": "Login",
        }
        page.submit_redirect = protected_url
        page.timeout_hooks.append(
            lambda: (
                page.visible_selectors.add(".staff-shell-layout"),
                page.local_storage_keys.extend(["ncs.staff.user", "ncs.staff.auth_mode"])
            )
        )
        result = engine.execute_step(
            actor={"name": "Admin", "landing_route": "#/admin/beds", "login_email": "admin@test", "login_password": "secret"},
            step={
                "id": "admin-login",
                "action": "staff_login",
                "route": "#/staff/login",
                "post_login_route": "#/admin/beds",
                "assertion": {"type": "url_contains", "value": "/#/admin/beds"},
            },
            page=page,
            base_url="http://127.0.0.1:9200",
            selectors={"staff_login": {"email": 'input[type="email"]', "password": 'input[type="password"]', "submit": 'button[type="submit"]'}},
            artifact_dir=Path.cwd(),
            timeout_ms=1000,
        )
        self.assertEqual("passed", result["status"])
        self.assertEqual("executed", result["resolution"])
        self.assertEqual(protected_url, page.url)

    def test_staff_login_reprobes_protected_surface_after_intermediate_post_submit_route(self):
        engine = AutomationEngine()
        page = _FakePage()
        context = _FakeContext()
        context.cookie_items = [
            {"name": "XSRF-TOKEN"},
            {"name": "ncs_session"},
        ]
        page.context = context
        protected_url = "http://127.0.0.1:9200/#/nurse/calls"
        redirect_login_url = "http://127.0.0.1:9200/#/staff/login?redirect=/nurse/calls"
        plain_login_url = "http://127.0.0.1:9200/#/staff/login"
        page.route_behaviors[protected_url] = {
            "url": redirect_login_url,
            "visible_selectors": {'input[type="email"]', 'input[type="password"]', 'button[type="submit"]'},
            "body_text": "Login",
        }
        page.route_behaviors[plain_login_url] = {
            "url": plain_login_url,
            "visible_selectors": {'input[type="email"]', 'input[type="password"]', 'button[type="submit"]'},
            "body_text": "Login",
        }
        page.submit_redirect = "http://127.0.0.1:9200/#/splash"
        page.post_submit_route_behaviors[protected_url] = {
            "url": protected_url,
            "visible_selectors": {".staff-shell-layout"},
            "body_text": "Calls surface",
        }
        page.timeout_hooks.append(
            lambda: page.local_storage_keys.extend(["ncs.staff.user", "ncs.staff.auth_mode"])
        )
        result = engine.execute_step(
            actor={"name": "Nurse", "landing_route": "#/nurse/calls", "login_email": "nurse@test", "login_password": "secret"},
            step={
                "id": "nurse-login",
                "action": "staff_login",
                "route": "#/staff/login",
                "post_login_route": "#/nurse/calls",
                "assertion": {"type": "url_contains", "value": "/#/nurse/calls"},
            },
            page=page,
            base_url="http://127.0.0.1:9200",
            selectors={"staff_login": {"email": 'input[type="email"]', "password": 'input[type="password"]', "submit": 'button[type="submit"]'}},
            artifact_dir=Path.cwd(),
            timeout_ms=1000,
        )
        self.assertEqual("passed", result["status"])
        self.assertEqual(protected_url, page.url)

    def test_staff_login_waits_for_browser_session_hints_before_declaring_success(self):
        engine = AutomationEngine()
        page = _FakePage()
        context = _FakeContext()
        context.cookie_items = [
            {"name": "XSRF-TOKEN"},
            {"name": "ncs_session"},
        ]
        page.context = context
        protected_url = "http://127.0.0.1:9200/#/nurse/calls"
        redirect_login_url = "http://127.0.0.1:9200/#/staff/login?redirect=/nurse/calls"
        plain_login_url = "http://127.0.0.1:9200/#/staff/login"
        page.route_behaviors[protected_url] = {
            "url": redirect_login_url,
            "visible_selectors": {'input[type="email"]', 'input[type="password"]', 'button[type="submit"]'},
            "body_text": "Login",
        }
        page.route_behaviors[plain_login_url] = {
            "url": plain_login_url,
            "visible_selectors": {'input[type="email"]', 'input[type="password"]', 'button[type="submit"]'},
            "body_text": "Login",
        }
        page.submit_redirect = protected_url
        page.post_submit_route_behaviors[protected_url] = {
            "url": protected_url,
            "visible_selectors": {".staff-shell-layout"},
            "body_text": "Calls surface",
        }
        page.timeout_hooks.append(
            lambda: page.local_storage_keys.extend(["ncs.staff.user", "ncs.staff.auth_mode"])
        )

        result = engine.execute_step(
            actor={"name": "Nurse", "landing_route": "#/nurse/calls", "login_email": "nurse@test", "login_password": "secret"},
            step={
                "id": "nurse-login",
                "action": "staff_login",
                "route": "#/staff/login",
                "post_login_route": "#/nurse/calls",
                "assertion": {"type": "url_contains", "value": "/#/nurse/calls"},
            },
            page=page,
            runtime_session={"network_events": []},
            base_url="http://127.0.0.1:9200",
            selectors={"staff_login": {"email": 'input[type="email"]', "password": 'input[type="password"]', "submit": 'button[type="submit"]'}},
            artifact_dir=Path.cwd(),
            timeout_ms=1000,
        )

        self.assertEqual("passed", result["status"])
        self.assertIn("ncs.staff.user", page.local_storage_keys)

    def test_finalize_run_record_marks_auth_contamination_as_validation_invalid(self):
        run_record = {
            "scenario_name": "Auth contamination demo",
            "steps": [
                {
                    "status": "failed",
                    "reason": "Staff authentication did not stabilize on the protected surface for Nurse ER.",
                    "message": "",
                    "current_url": "http://127.0.0.1:9200/#/staff/login?redirect=/nurse/calls",
                    "observations": {"auth_surface": "staff-login"},
                    "index": 1,
                    "actor": "Nurse ER",
                    "id": "nurse-login",
                }
            ],
            "actor_sessions": [
                {
                    "actor_name": "Nurse ER",
                    "final_url": "http://127.0.0.1:9200/#/staff/login?redirect=/nurse/calls",
                }
            ],
        }

        finalized = finalize_run_record(run_record)

        self.assertEqual("validation-invalid", finalized["status"])
        self.assertIn("auth/session contamination", finalized["summary"])
        self.assertIn("staff-auth-not-stabilized", finalized["validation_invalid_reasons"])

    def test_patient_qr_login_reprobes_authenticated_surface_after_delayed_transition(self):
        engine = AutomationEngine()
        page = _FakePage()
        context = _FakeContext()
        context.cookie_items = [
            {"name": "XSRF-TOKEN"},
            {"name": "ncs_session"},
        ]
        page.context = context
        scan_url = "http://127.0.0.1:9200/#/patient/scan"
        welcome_url = "http://127.0.0.1:9200/#/patient/welcome"
        services_url = "http://127.0.0.1:9200/#/patient/services"
        page.route_behaviors[scan_url] = {
            "url": scan_url,
            "visible_selectors": {'input[type="text"]', 'button[type="submit"]'},
            "body_text": "Scan",
        }
        page.submit_redirect = scan_url
        page.post_submit_route_behaviors[welcome_url] = {
            "url": welcome_url,
            "body_text": "Welcome",
        }
        page.post_submit_route_behaviors[services_url] = {
            "url": services_url,
            "body_text": "Services",
        }
        page.timeout_hooks.append(
            lambda: page.local_storage_keys.append("ncs.patient.session")
        )
        result = engine.execute_step(
            actor={"name": "Patient", "landing_route": "#/patient/welcome", "qr_token": "DEMO-ER-101-A"},
            step={
                "id": "patient-login",
                "action": "patient_qr_login",
                "route": "#/patient/scan",
                "assertion": {"type": "url_contains", "value": "/#/patient/welcome"},
            },
            page=page,
            runtime_session={
                "network_events": [
                    {
                        "tab_id": "main",
                        "kind": "request-finished",
                        "url": "http://127.0.0.1:8000/api/v1/patient/session/init",
                        "method": "POST",
                        "status": 200,
                    }
                ]
            },
            base_url="http://127.0.0.1:9200",
            selectors={"patient_scan": {"token": 'input[type="text"]', "submit": 'button[type="submit"]'}},
            artifact_dir=Path.cwd(),
            timeout_ms=1000,
        )
        self.assertEqual("passed", result["status"])
        self.assertEqual(welcome_url, page.url)

    def test_patient_qr_login_retries_once_after_retryable_bootstrap_failure(self):
        engine = AutomationEngine()
        page = _FakePage()
        context = _FakeContext()
        context.cookie_items = [
            {"name": "XSRF-TOKEN"},
            {"name": "ncs_session"},
        ]
        page.context = context
        scan_url = "http://127.0.0.1:9200/#/patient/scan"
        welcome_url = "http://127.0.0.1:9200/#/patient/welcome"
        services_url = "http://127.0.0.1:9200/#/patient/services"
        page.route_behaviors[scan_url] = {
            "url": scan_url,
            "visible_selectors": {'input[type="text"]', 'button[type="submit"]'},
            "body_text": "Scan",
        }
        page.submit_redirect = "http://127.0.0.1:9200/#/patient/session-expired"
        page.timeout_hooks.extend(
            [
                lambda: setattr(page, "submit_redirect", welcome_url),
                lambda: page.local_storage_keys.append("ncs.patient.session"),
            ]
        )
        result = engine.execute_step(
            actor={"name": "Patient", "landing_route": "#/patient/welcome", "qr_token": "DEMO-ER-101-A"},
            step={
                "id": "patient-login",
                "action": "patient_qr_login",
                "route": "#/patient/scan",
                "assertion": {"type": "url_contains", "value": "/#/patient/welcome"},
            },
            page=page,
            runtime_session={
                "network_events": [
                    {
                        "tab_id": "main",
                        "kind": "request-failed",
                        "url": "http://127.0.0.1:8000/sanctum/csrf-cookie",
                        "method": "GET",
                        "failure": None,
                    },
                    {
                        "tab_id": "main",
                        "kind": "request-failed",
                        "url": "http://127.0.0.1:8000/api/v1/patient/session/init",
                        "method": "POST",
                        "failure": None,
                    },
                ]
            },
            base_url="http://127.0.0.1:9200",
            selectors={"patient_scan": {"token": 'input[type="text"]', "submit": 'button[type="submit"]'}},
            artifact_dir=Path.cwd(),
            timeout_ms=1000,
        )

        self.assertEqual("passed", result["status"])
        self.assertEqual(welcome_url, page.url)

    def test_patient_navigate_stabilizes_before_waiting_for_services_selector(self):
        engine = AutomationEngine()
        page = _FakePage()
        context = _FakeContext()
        context.cookie_items = [
            {"name": "XSRF-TOKEN"},
            {"name": "ncs_session"},
        ]
        page.context = context
        services_url = "http://127.0.0.1:9200/#/patient/services"
        page.route_behaviors[services_url] = {
            "url": services_url,
            "visible_selectors": {".patient-service-card"},
            "body_text": "Services",
        }
        page.local_storage_keys = ["ncs.patient.session"]

        result = engine.execute_step(
            actor={"name": "Patient", "kind": "patient", "landing_route": "#/patient/welcome"},
            step={
                "id": "patient-open-services",
                "action": "navigate",
                "route": "#/patient/services",
                "wait_for_selector_key": "patient_services.service_card",
                "assertion": {"type": "url_contains", "value": "/#/patient/services"},
            },
            page=page,
            runtime_session={
                "network_events": [
                    {
                        "tab_id": "main",
                        "kind": "request-finished",
                        "url": "http://127.0.0.1:8000/api/v1/patient/session/init",
                        "method": "POST",
                        "status": 200,
                    }
                ]
            },
            base_url="http://127.0.0.1:9200",
            selectors={"patient_services": {"service_card": ".patient-service-card"}},
            artifact_dir=Path.cwd(),
            timeout_ms=1000,
        )

        self.assertEqual("passed", result["status"])
        self.assertEqual(services_url, page.url)

    def test_capture_step_screenshot_uses_step_settle_ms(self):
        engine = AutomationEngine()
        page = _FakePage()
        tmp = self._workspace_temp_dir()
        try:
            engine.capture_step_screenshot(
                page=page,
                artifact_dir=tmp,
                step={"id": "reports-open", "assertion": {}, "wait_for_selector": "", "settle_ms": 700},
                status="passed",
                step_index=1,
                selectors={},
                timeout_ms=1000,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(700, page.last_wait_timeout)

    def test_assert_state_can_compare_badge_count_to_remembered_baseline(self):
        engine = AutomationEngine()
        page = _FakePage()
        page.url = "http://127.0.0.1:9200/#/nurse/performance"
        page.calls_badges = ["3"]
        runtime_session = {"network_events": [], "state_memory": {}}
        tmp = self._workspace_temp_dir()
        try:
            baseline = engine.execute_step(
                actor={"name": "Nurse"},
                step={
                    "id": "baseline",
                    "action": "assert_state",
                    "_step_index": 1,
                    "remember_as": "outside_calls_baseline",
                    "checks": [{"kind": "url_contains", "value": "/#/nurse/performance"}],
                },
                page=page,
                runtime_session=runtime_session,
                base_url="http://127.0.0.1:9200",
                selectors={},
                artifact_dir=tmp,
                timeout_ms=1000,
            )
            result = engine.execute_step(
                actor={"name": "Nurse"},
                step={
                    "id": "cleanup",
                    "action": "assert_state",
                    "_step_index": 2,
                    "checks": [{"kind": "badge_count_matches_memory", "value": "outside_calls_baseline"}],
                },
                page=page,
                runtime_session=runtime_session,
                base_url="http://127.0.0.1:9200",
                selectors={},
                artifact_dir=tmp,
                timeout_ms=1000,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertEqual("passed", baseline["status"])
        self.assertEqual("passed", result["status"])

    def test_finalize_run_record_marks_stale_queue_contamination_as_validation_invalid(self):
        run_record = {
            "scenario_name": "Stale queue demo",
            "steps": [
                {
                    "status": "failed",
                    "reason": "state-assertions-failed",
                    "message": "calls badge count was 4, expected baseline 3 from outside_calls_baseline",
                    "current_url": "http://127.0.0.1:9200/#/nurse/performance",
                    "observations": {"auth_surface": "app-surface"},
                    "index": 3,
                    "actor": "Nurse ER",
                    "id": "cleanup",
                }
            ],
            "actor_sessions": [
                {
                    "actor_name": "Nurse ER",
                    "final_url": "http://127.0.0.1:9200/#/nurse/performance",
                }
            ],
        }

        finalized = finalize_run_record(run_record)

        self.assertEqual("validation-invalid", finalized["status"])
        self.assertIn("stale-queue-contamination", finalized["validation_invalid_reasons"])

    def test_assert_state_writes_snapshot_artifact(self):
        engine = AutomationEngine()
        page = _FakePage()
        page.url = "http://127.0.0.1:9200/#/nurse/performance"
        page.lifecycle_banner_texts = ["New call request\nOpen calls"]
        page.calls_badges = ["1"]
        context = _FakeContext()
        context.cookie_items = [
            {"name": "XSRF-TOKEN"},
            {"name": "ncs_session"},
            {"name": "other-cookie"},
        ]
        page.context = context
        tmp = self._workspace_temp_dir()
        try:
            result = engine.execute_step(
                actor={"name": "Nurse"},
                step={
                    "id": "nurse-cta",
                    "action": "assert_state",
                    "_step_index": 4,
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/performance"},
                        {"kind": "text_present", "value": "Open calls"},
                        {"kind": "badge_count_at_least", "value": 1},
                    ],
                },
                page=page,
                runtime_session={"network_events": []},
                base_url="http://127.0.0.1:9200",
                selectors={},
                artifact_dir=tmp,
                timeout_ms=1000,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertEqual("passed", result["status"])
        self.assertTrue(result["artifact_path"].endswith("04-nurse-cta-state.json"))
        self.assertIn("XSRF-TOKEN", result["observations"]["session_cookie_names"])
        self.assertIn("ncs_session", result["observations"]["session_cookie_names"])

    def test_environment_ready_checks_frontend_and_backend(self):
        store = _DummyStore()
        app_config = dict(DEFAULT_APP_CONFIG)
        with patch("run_notification_audit._http_ready", side_effect=[True, True]):
            ensure_environment_ready(store, app_config)

    def test_open_tab_registers_new_tab_in_runtime_session(self):
        engine = AutomationEngine()
        context = _FakeContext()
        context.cookie_items = [
            {"name": "XSRF-TOKEN"},
            {"name": "ncs_session"},
        ]
        context.pages[0].local_storage_keys = ["ncs.staff.user", "ncs.staff.auth_mode"]
        context.pages[0].visible_selectors = {".staff-shell-layout"}
        runtime_session = {"context": context, "tabs": {"main": context.pages[0]}, "active_tab_id": "main", "network_events": []}
        fresh_tab = context.new_page

        def new_page_with_auth():
            page = fresh_tab()
            page.local_storage_keys = ["ncs.staff.user", "ncs.staff.auth_mode"]
            page.visible_selectors = {".staff-shell-layout"}
            return page

        context.new_page = new_page_with_auth
        result = engine.execute_step(
            actor={"name": "Nurse"},
            step={
                "id": "open-calls-tab",
                "action": "open_tab",
                "route": "#/nurse/calls",
                "target_tab_id": "calls",
                "assertion": {"type": "url_contains", "value": "/#/nurse/calls"},
            },
            page=context.pages[0],
            runtime_session=runtime_session,
            base_url="http://127.0.0.1:9200",
            selectors={},
            artifact_dir=Path.cwd(),
            timeout_ms=1000,
        )

        self.assertEqual("passed", result["status"])
        self.assertIn("calls", runtime_session["tabs"])
        self.assertEqual("calls", runtime_session["active_tab_id"])

    def test_open_actor_session_retries_once_for_recoverable_launch_issue(self):
        engine = AutomationEngine()
        calls = {"count": 0}

        def fake_launch(**_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("Protocol error (Browser.getWindowForTarget): Browser window not found")
            return _FakeContext()

        with patch.object(engine, "_launch_persistent_context", side_effect=fake_launch):
            session = engine.open_actor_session(
                playwright=SimpleNamespace(chromium=object()),
                chrome_path="chrome.exe",
                profile_dir=Path.cwd(),
                launch_mode="browser",
                headless=False,
                viewport_size=(1280, 720),
            )

        self.assertEqual(2, calls["count"])
        self.assertTrue(session["startup_recovered"])
        self.assertEqual(2, session["startup_attempts"])

    def test_open_actor_session_raises_structured_error_for_unrecoverable_issue(self):
        engine = AutomationEngine()
        with patch.object(engine, "_launch_persistent_context", side_effect=RuntimeError("Executable doesn't exist")):
            with self.assertRaises(ActorSessionStartupError) as raised:
                engine.open_actor_session(
                    playwright=SimpleNamespace(chromium=object()),
                    chrome_path="missing.exe",
                    profile_dir=Path.cwd(),
                    launch_mode="browser",
                    headless=False,
                    viewport_size=(1280, 720),
                )
        self.assertEqual("launch-failed", raised.exception.category)
        self.assertFalse(raised.exception.recoverable)

    def test_same_actor_steps_reuse_one_live_session(self):
        runner = ScenarioRunner(_DummyStore(), dict(DEFAULT_APP_CONFIG), {})
        fake_engine = _FakeContinuityEngine()
        runner.engine = fake_engine
        temp_dir = self._workspace_temp_dir()
        scenario = {
            "id": "single-actor",
            "name": "Single Actor",
            "project_id": "ncs",
            "participants": [{"id": "admin", "name": "Admin", "preset_id": "admin-main", "route": "#/staff/login", "launch_mode": "browser"}],
            "steps": [
                {"id": "step-1", "title": "First", "actor_id": "admin", "mode": "automated", "action": "navigate", "route": "#/one"},
                {"id": "step-2", "title": "Second", "actor_id": "admin", "mode": "automated", "action": "navigate", "route": "#/two"},
            ],
        }
        profiles = [{"id": "admin-main", "name": "Admin", "preset_id": "admin-main", "route": "#/staff/login", "launch_mode": "browser"}]
        try:
            with patch("lab.scenario_runner.ensure_artifact_dir", side_effect=lambda run_record: _fake_artifact_dir(run_record, temp_dir)):
                with patch("lab.scenario_runner.write_run_artifacts", lambda *_args, **_kwargs: None):
                    run_record = runner.run(
                        scenario=scenario,
                        profiles=profiles,
                        mode="automated",
                        chrome_data_root=temp_dir,
                        chrome_path="chrome.exe",
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(1, fake_engine.open_session_count)
        self.assertEqual(1, len({page_id for _, _, page_id in fake_engine.step_calls}))
        self.assertEqual("passed", run_record["status"])
        self.assertTrue(run_record["actor_sessions"][0]["reused"])

    def test_actor_switch_opens_new_session_and_reuses_when_switching_back(self):
        runner = ScenarioRunner(_DummyStore(), dict(DEFAULT_APP_CONFIG), {})
        fake_engine = _FakeContinuityEngine()
        runner.engine = fake_engine
        temp_dir = self._workspace_temp_dir()
        scenario = {
            "id": "multi-actor",
            "name": "Multi Actor",
            "project_id": "ncs",
            "participants": [
                {"id": "patient", "name": "Patient", "preset_id": "patient-er101a", "route": "#/patient/scan", "launch_mode": "browser"},
                {"id": "nurse", "name": "Nurse", "preset_id": "nurse-er", "route": "#/staff/login", "launch_mode": "browser"},
            ],
            "steps": [
                {"id": "patient-1", "title": "Patient First", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/scan"},
                {"id": "nurse-1", "title": "Nurse First", "actor_id": "nurse", "mode": "automated", "action": "navigate", "route": "#/staff/login"},
                {"id": "patient-2", "title": "Patient Again", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/services"},
            ],
        }
        profiles = [
            {"id": "patient-er101a", "name": "Patient", "preset_id": "patient-er101a", "route": "#/patient/scan", "launch_mode": "browser"},
            {"id": "nurse-er", "name": "Nurse", "preset_id": "nurse-er", "route": "#/staff/login", "launch_mode": "browser"},
        ]
        try:
            with patch("lab.scenario_runner.ensure_artifact_dir", side_effect=lambda run_record: _fake_artifact_dir(run_record, temp_dir)):
                with patch("lab.scenario_runner.write_run_artifacts", lambda *_args, **_kwargs: None):
                    run_record = runner.run(
                        scenario=scenario,
                        profiles=profiles,
                        mode="automated",
                        chrome_data_root=temp_dir,
                        chrome_path="chrome.exe",
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(2, fake_engine.open_session_count)
        patient_page_ids = [page_id for actor_id, _, page_id in fake_engine.step_calls if actor_id == "patient-er101a"]
        nurse_page_ids = [page_id for actor_id, _, page_id in fake_engine.step_calls if actor_id == "nurse-er"]
        self.assertEqual(1, len(set(patient_page_ids)))
        self.assertEqual(1, len(set(nurse_page_ids)))
        self.assertNotEqual(patient_page_ids[0], nurse_page_ids[0])
        self.assertEqual("passed", run_record["status"])

    def test_runner_reuses_preserved_runtime_session_before_launching_new_one(self):
        runner = ScenarioRunner(_DummyStore(), dict(DEFAULT_APP_CONFIG), {})
        fake_engine = _FakeContinuityEngine()
        runner.engine = fake_engine
        temp_dir = self._workspace_temp_dir()
        preserved_runtime = {
            "context": object(),
            "page": _FakePage(),
            "profile_dir": temp_dir / "admin-main",
            "launch_mode": "browser",
            "actor_name": "Admin",
            "participant_id": "old-admin",
            "preset_id": "admin-main",
            "kind": "staff",
            "steps": ["old-step"],
        }
        scenario = {
            "id": "reuse-runtime",
            "name": "Reuse Runtime",
            "project_id": "ncs",
            "participants": [{"id": "admin", "name": "Admin", "preset_id": "admin-main", "route": "#/staff/login", "launch_mode": "browser"}],
            "steps": [{"id": "admin-1", "title": "Admin", "actor_id": "admin", "mode": "automated", "action": "navigate", "route": "#/admin/beds"}],
        }
        profiles = [{"id": "admin-main", "name": "Admin", "preset_id": "admin-main", "route": "#/staff/login", "launch_mode": "browser"}]
        try:
            with patch("lab.scenario_runner.ensure_artifact_dir", side_effect=lambda run_record: _fake_artifact_dir(run_record, temp_dir)):
                with patch("lab.scenario_runner.write_run_artifacts", lambda *_args, **_kwargs: None):
                    run_record = runner.run(
                        scenario=scenario,
                        profiles=profiles,
                        mode="automated",
                        chrome_data_root=temp_dir,
                        chrome_path="chrome.exe",
                        reusable_runtime_sessions=[{"runtime": preserved_runtime, "runtime_handle": object(), "runtime_bundle_id": "runtime::old"}],
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(0, fake_engine.open_session_count)
        self.assertEqual("reused-live-session", run_record["actor_sessions"][0]["startup_state"])
        self.assertEqual("passed", run_record["status"])

    def test_keep_open_reopens_all_actor_windows_used_by_scenario(self):
        store = _DummyStore()
        runner = ScenarioRunner(store, dict(DEFAULT_APP_CONFIG), {})
        fake_engine = _FakeContinuityEngine()
        runner.engine = fake_engine
        temp_dir = self._workspace_temp_dir()
        scenario = {
            "id": "keep-open",
            "name": "Keep Open",
            "project_id": "ncs",
            "participants": [
                {"id": "patient", "name": "Patient", "preset_id": "patient-er101a", "route": "#/patient/scan", "launch_mode": "browser"},
                {"id": "nurse", "name": "Nurse", "preset_id": "nurse-er", "route": "#/staff/login", "launch_mode": "browser"},
            ],
            "steps": [
                {"id": "patient-1", "title": "Patient", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/scan"},
                {"id": "nurse-1", "title": "Nurse", "actor_id": "nurse", "mode": "automated", "action": "navigate", "route": "#/staff/login"},
            ],
        }
        profiles = [
            {"id": "patient-er101a", "name": "Patient", "preset_id": "patient-er101a", "route": "#/patient/scan", "launch_mode": "browser"},
            {"id": "nurse-er", "name": "Nurse", "preset_id": "nurse-er", "route": "#/staff/login", "launch_mode": "browser"},
        ]
        try:
            with patch("lab.scenario_runner.ensure_artifact_dir", side_effect=lambda run_record: _fake_artifact_dir(run_record, temp_dir)):
                with patch("lab.scenario_runner.write_run_artifacts", lambda *_args, **_kwargs: None):
                    with patch("lab.scenario_runner.launch_chrome", side_effect=[SimpleNamespace(pid=101), SimpleNamespace(pid=202)]):
                        run_record = runner.run(
                            scenario=scenario,
                            profiles=profiles,
                            mode="automated",
                            chrome_data_root=temp_dir,
                            chrome_path="chrome.exe",
                            keep_windows_open=True,
                        )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        tracked = store.load_active_sessions()
        self.assertEqual(2, len(tracked))
        self.assertTrue(all(session["profile_id"] in {"patient-er101a", "nurse-er"} for session in tracked))
        self.assertTrue(all(session["kept_open"] for session in run_record["actor_sessions"]))
        self.assertTrue(all(session["inspection_state"] == "reopened-approximation" for session in run_record["actor_sessions"]))
        self.assertTrue(run_record["inspection_overview"]["fallback_reopen_used"])

    def test_keep_open_preserves_live_actor_sessions_when_supported(self):
        store = _DummyStore()
        runner = ScenarioRunner(store, dict(DEFAULT_APP_CONFIG), {})
        fake_engine = _FakeContinuityEngine()
        runner.engine = fake_engine
        temp_dir = self._workspace_temp_dir()
        scenario = {
            "id": "live-preserved",
            "name": "Live Preserved",
            "project_id": "ncs",
            "participants": [{"id": "admin", "name": "Admin", "preset_id": "admin-main", "route": "#/staff/login", "launch_mode": "browser"}],
            "steps": [
                {"id": "admin-1", "title": "Admin Login", "actor_id": "admin", "mode": "automated", "action": "staff_login", "route": "#/staff/login"},
                {"id": "admin-2", "title": "Admin Beds", "actor_id": "admin", "mode": "automated", "action": "navigate", "route": "#/admin/beds"},
            ],
        }
        profiles = [{"id": "admin-main", "name": "Admin", "preset_id": "admin-main", "kind": "staff", "route": "#/staff/login", "launch_mode": "browser"}]
        captured_events = []
        try:
            with patch("lab.scenario_runner.ensure_artifact_dir", side_effect=lambda run_record: _fake_artifact_dir(run_record, temp_dir)):
                with patch("lab.scenario_runner.write_run_artifacts", lambda *_args, **_kwargs: None):
                    run_record = runner.run(
                        scenario=scenario,
                        profiles=profiles,
                        mode="automated",
                        chrome_data_root=temp_dir,
                        chrome_path="chrome.exe",
                        keep_windows_open=True,
                        live_preservation_supported=True,
                        event_callback=lambda event: captured_events.append(event),
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(0, fake_engine.closed_sessions)
        self.assertEqual(1, fake_engine.started_runtimes)
        self.assertEqual(0, fake_engine.stopped_runtimes)
        self.assertTrue(run_record["inspection_overview"]["true_keep_open"])
        self.assertEqual("live-preserved", run_record["actor_sessions"][0]["inspection_state"])
        self.assertEqual("preserved", run_record["actor_sessions"][0]["auth_state"])
        finish_event = next(event for event in captured_events if event.get("type") == "scenario_finished")
        self.assertEqual(1, len(finish_event.get("preserved_runtime_sessions", [])))
        self.assertIsNotNone(finish_event.get("preserved_runtime_sessions", [])[0].get("runtime_handle"))

    def test_live_preservation_labels_staff_auth_loss_truthfully(self):
        runner = ScenarioRunner(_DummyStore(), dict(DEFAULT_APP_CONFIG), {})
        fake_engine = _FakeContinuityEngine()
        runner.engine = fake_engine
        temp_dir = self._workspace_temp_dir()
        scenario = {
            "id": "staff-login-state",
            "name": "Staff Login State",
            "project_id": "ncs",
            "participants": [{"id": "supervisor", "name": "Supervisor", "preset_id": "supervisor-hospital", "route": "#/staff/login", "launch_mode": "browser"}],
            "steps": [
                {"id": "supervisor-login", "title": "Supervisor Login", "actor_id": "supervisor", "mode": "automated", "action": "navigate", "route": "#/staff/login?redirect=/supervisor/calls"},
            ],
        }
        profiles = [{"id": "supervisor-hospital", "name": "Supervisor", "preset_id": "supervisor-hospital", "kind": "staff", "route": "#/staff/login", "launch_mode": "browser"}]
        try:
            with patch("lab.scenario_runner.ensure_artifact_dir", side_effect=lambda run_record: _fake_artifact_dir(run_record, temp_dir)):
                with patch("lab.scenario_runner.write_run_artifacts", lambda *_args, **_kwargs: None):
                    run_record = runner.run(
                        scenario=scenario,
                        profiles=profiles,
                        mode="automated",
                        chrome_data_root=temp_dir,
                        chrome_path="chrome.exe",
                        keep_windows_open=True,
                        live_preservation_supported=True,
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        actor_session = run_record["actor_sessions"][0]
        self.assertEqual("live-preserved", actor_session["inspection_state"])
        self.assertEqual("lost-before-finish", actor_session["auth_state"])
        self.assertIn("auth was not preserved", actor_session["auth_label"])

    def test_manual_review_step_creates_manual_evidence_and_best_evidence(self):
        runner = ScenarioRunner(_DummyStore(), dict(DEFAULT_APP_CONFIG), {})
        fake_engine = _FakeContinuityEngine()
        runner.engine = fake_engine
        temp_dir = self._workspace_temp_dir()
        scenario = {
            "id": "manual-evidence",
            "name": "Manual Evidence",
            "project_id": "ncs",
            "participants": [{"id": "patient", "name": "Patient", "preset_id": "patient-er101a", "route": "#/patient/scan", "launch_mode": "browser"}],
            "steps": [
                {"id": "patient-open", "title": "Open", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/scan", "screenshot": True},
                {"id": "manual-check", "title": "Manual Check", "actor_id": "patient", "mode": "manual", "action": "manual_checkpoint", "guidance": "Confirm visually.", "screenshot": True},
            ],
        }
        profiles = [{"id": "patient-er101a", "name": "Patient", "preset_id": "patient-er101a", "route": "#/patient/scan", "launch_mode": "browser"}]
        try:
            with patch("lab.scenario_runner.ensure_artifact_dir", side_effect=lambda run_record: _fake_artifact_dir(run_record, temp_dir)):
                with patch("lab.scenario_runner.write_run_artifacts", lambda *_args, **_kwargs: None):
                    run_record = runner.run(
                        scenario=scenario,
                        profiles=profiles,
                        mode="automated",
                        chrome_data_root=temp_dir,
                        chrome_path="chrome.exe",
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        manual_step = next(step for step in run_record["steps"] if step["id"] == "manual-check")
        self.assertEqual("manual", manual_step["status"])
        self.assertEqual("manual-review", manual_step["evidence_type"])
        self.assertTrue(manual_step["best_evidence"])
        self.assertTrue(manual_step["screenshot"])

    def test_write_run_artifacts_includes_best_evidence_and_actor_summary(self):
        temp_dir = self._workspace_temp_dir()
        run_record = {
            "id": "demo-1",
            "scenario_name": "Demo",
            "scenario_id": "demo",
            "mode": "automated",
            "launch_mode": "browser",
            "status": "manual-review",
            "started_at": "2026-04-25 21:00:00",
            "ended_at": "2026-04-25 21:00:10",
            "artifact_dir": str(temp_dir),
            "steps": [
                {
                    "id": "login",
                    "title": "Login",
                    "actor": "Admin",
                    "action": "staff_login",
                    "mode": "automated",
                    "status": "passed",
                    "message": "Logged in",
                    "reason": "assertion-passed",
                    "current_url": "http://127.0.0.1:9200/#/admin/beds",
                    "screenshot": str(temp_dir / "01-login-passed.png"),
                    "index": 1,
                    "evidence_type": "routine-step",
                    "best_evidence": True,
                },
                {
                    "id": "manual",
                    "title": "Manual Check",
                    "actor": "Admin",
                    "action": "manual_checkpoint",
                    "mode": "manual",
                    "status": "manual",
                    "message": "Confirm KPIs",
                    "reason": "manual-checkpoint",
                    "current_url": "http://127.0.0.1:9200/#/reports",
                    "screenshot": str(temp_dir / "02-manual-review.png"),
                    "index": 2,
                    "evidence_type": "manual-review",
                    "best_evidence": True,
                },
            ],
            "actor_sessions": [
                {
                    "actor_name": "Admin",
                    "steps": ["login", "manual"],
                    "reused": True,
                    "kept_open": False,
                    "final_url": "http://127.0.0.1:9200/#/reports",
                    "final_screenshot": str(temp_dir / "actor-01-admin-final-state.png"),
                    "inspection_state": "closed-after-run",
                    "inspection_label": "Closed after run",
                    "auth_state": "closed",
                    "auth_label": "Session closed after run",
                    "inspectable": False,
                    "fallback_reason": "",
                }
            ],
            "best_evidence": [
                {"type": "manual-review", "actor": "Admin", "path": str(temp_dir / "02-manual-review.png"), "label": "Manual Check"},
            ],
            "inspection_overview": {
                "keep_windows_open_requested": False,
                "live_preservation_supported": True,
                "true_keep_open": False,
                "fallback_reopen_used": False,
            },
            "summary": "Demo finished with manual-review.",
        }
        finalize_run_record(run_record)
        try:
            write_run_artifacts(run_record, temp_dir)
            summary_md = (temp_dir / "summary.md").read_text(encoding="utf-8")
            step_log = (temp_dir / "step-log.json").read_text(encoding="utf-8")
            evidence_index = (temp_dir / "evidence-index.json").read_text(encoding="utf-8")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertIn("Best Evidence", summary_md)
        self.assertIn("Actor Sessions", summary_md)
        self.assertIn("manual-review", summary_md)
        self.assertIn("Inspection Overview", summary_md)
        self.assertIn("Session closed after run", summary_md)
        self.assertIn("inspection_state", evidence_index)
        self.assertIn("auth_label", evidence_index)
        self.assertIn('"best_evidence": true', step_log)
        self.assertIn("final_screenshot", evidence_index)

    def test_finalize_run_record_marks_recovered_failure_as_passed_with_recovery(self):
        run_record = {
            "scenario_name": "Recovered Run",
            "steps": [
                {"id": "login", "title": "Login", "actor": "Admin", "status": "failed", "index": 1, "resolution": "failed"},
                {"id": "open", "title": "Open", "actor": "Admin", "status": "passed", "index": 2, "resolution": "executed"},
            ],
        }
        finalize_run_record(run_record)
        self.assertEqual("passed-with-recovery", run_record["status"])
        self.assertTrue(run_record["steps"][0]["recovered"])
        self.assertEqual("open", run_record["steps"][0]["recovered_by_step_id"])

    def test_finalize_run_record_keeps_manual_review_when_recovery_happened_before_manual_checkpoint(self):
        run_record = {
            "scenario_name": "Recovered Manual Run",
            "steps": [
                {"id": "login", "title": "Login", "actor": "Admin", "status": "failed", "index": 1, "resolution": "failed"},
                {"id": "open", "title": "Open", "actor": "Admin", "status": "passed", "index": 2, "resolution": "executed"},
                {"id": "manual", "title": "Manual", "actor": "Admin", "status": "manual", "index": 3, "resolution": "manual-review"},
            ],
        }
        finalize_run_record(run_record)
        self.assertEqual("manual-review", run_record["status"])
        self.assertTrue(run_record["recovery_overview"]["recovery_occurred"])


class _DummyStore:
    def __init__(self) -> None:
        self._history = []
        self._active_sessions = []
        self._projects = [{"id": "ncs", "api_base_url": "http://127.0.0.1:8000/api/v1"}]

    def load_active_sessions(self):
        return list(self._active_sessions)

    def save_active_sessions(self, sessions) -> None:
        self._active_sessions = list(sessions)

    def load_run_history(self):
        return list(self._history)

    def save_run_history(self, history) -> None:
        self._history = list(history)

    def load_projects(self):
        return list(self._projects)


class _FakeContinuityEngine:
    available = True
    backend_name = "fake"

    def __init__(self) -> None:
        self.open_session_count = 0
        self.step_calls = []
        self.closed_sessions = 0
        self.started_runtimes = 0
        self.stopped_runtimes = 0

    def describe(self) -> str:
        return "Fake engine"

    @contextmanager
    def playwright_runtime(self):
        yield object()

    def start_playwright_runtime(self, log_callback=None):
        self.started_runtimes += 1
        if log_callback:
            log_callback("Started fake Playwright runtime.")
        return {"controller": object(), "playwright": object()}

    def stop_playwright_runtime(self, _runtime, log_callback=None):
        self.stopped_runtimes += 1
        if log_callback:
            log_callback("Stopped fake Playwright runtime.")

    def open_actor_session(self, **kwargs):
        self.open_session_count += 1
        return {
            "context": object(),
            "page": _FakePage(),
            "profile_dir": kwargs["profile_dir"],
            "launch_mode": kwargs["launch_mode"],
        }

    def execute_step(self, *, actor, step, page, base_url, **_kwargs):
        page.url = f"{base_url.rstrip('/')}/{step.get('route', '#/').lstrip('/')}"
        self.step_calls.append((actor["preset_id"], step["id"], id(page)))
        return "passed", f"Executed {step['id']}"

    def capture_step_screenshot(self, *, artifact_dir, step, status, step_index, **_kwargs):
        path = artifact_dir / f"{step_index:02d}-{step['id']}-{status}.png"
        path.write_text("fake", encoding="utf-8")
        return path

    def capture_actor_state_screenshot(self, *, artifact_dir, actor_slug, actor_index, **_kwargs):
        path = artifact_dir / f"actor-{actor_index:02d}-{actor_slug}-final-state.png"
        path.write_text("fake", encoding="utf-8")
        return path

    def close_actor_session(self, _session, log_callback=None):
        self.closed_sessions += 1
        if log_callback:
            log_callback("Closed fake actor session.")


def _fake_artifact_dir(run_record: dict, temp_root: Path) -> Path:
    artifact_dir = temp_root / run_record["scenario_id"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_record["artifact_dir"] = str(artifact_dir)
    return artifact_dir


if __name__ == "__main__":
    unittest.main()
