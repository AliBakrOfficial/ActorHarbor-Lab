import tempfile
import unittest
from pathlib import Path

from lab.chrome_manager import build_launch_command, is_safe_child, profile_data_dir, resolve_url, slugify_profile_id
from lab.config_store import LabConfigStore
from lab.defaults import DEFAULT_APP_CONFIG, DEFAULT_PROJECTS, DEFAULT_SELECTOR_MAPS
from lab.paths import (
    ACTIVE_SESSIONS_FILE,
    APP_CONFIG_FILE,
    PRESETS_FILE,
    PROFILES_FILE,
    PROJECTS_FILE,
    RUN_HISTORY_FILE,
    SCENARIOS_FILE,
    SELECTOR_MAPS_FILE,
)
from lab.projects import get_adapter
from lab.run_history import create_run_record, ensure_artifact_dir, finalize_run_record
from lab.scenario_runner import build_scenario_plan
from lab.scenario_runner import ScenarioRunner


class LabEvolutionTests(unittest.TestCase):
    def test_slugify_profile_id_is_stable(self):
        self.assertEqual(slugify_profile_id("Patient ER-101-A"), "patient-er-101-a")

    def test_profile_data_dir_is_lab_owned(self):
        root = Path(tempfile.gettempdir()) / "chrome-data-root"
        target = profile_data_dir(root, "nurse-er")
        self.assertTrue(is_safe_child(root, target))

    def test_resolve_url_supports_hash_routes(self):
        self.assertEqual(resolve_url("http://127.0.0.1:9200", "#/staff/login"), "http://127.0.0.1:9200/#/staff/login")

    def test_build_launch_command_supports_app_mode(self):
        command = build_launch_command(
            chrome_path="chrome.exe",
            profile_dir=Path("runtime/chrome-data/nurse-er"),
            url="http://127.0.0.1:9200/#/staff/login",
            launch_mode="app",
            window_size="1200,800",
        )
        self.assertIn("--app=http://127.0.0.1:9200/#/staff/login", command)
        self.assertIn("--user-data-dir=runtime\\chrome-data\\nurse-er", command)

    def test_config_store_bootstraps_json_files(self):
        LabConfigStore()
        for path in [
            APP_CONFIG_FILE,
            PROJECTS_FILE,
            PRESETS_FILE,
            PROFILES_FILE,
            SCENARIOS_FILE,
            SELECTOR_MAPS_FILE,
            ACTIVE_SESSIONS_FILE,
            RUN_HISTORY_FILE,
        ]:
            self.assertTrue(path.exists(), str(path))

    def test_default_app_config_shape(self):
        self.assertEqual(DEFAULT_APP_CONFIG["base_url"], "http://127.0.0.1:9200")
        self.assertEqual(DEFAULT_APP_CONFIG["current_project"], "ncs")

    def test_default_project_and_selector_maps_exist(self):
        self.assertEqual(DEFAULT_PROJECTS[0]["adapter"], "ncs")
        self.assertIn("staff_login", DEFAULT_SELECTOR_MAPS["ncs"])

    def test_adapter_registry_resolves_ncs(self):
        adapter = get_adapter("ncs")
        self.assertEqual(adapter.project_id, "ncs")
        self.assertGreaterEqual(len(adapter.get_default_scenarios()), 5)

    def test_scenario_plan_expands_participants_and_steps(self):
        store = LabConfigStore()
        scenario = next(item for item in store.load_scenarios() if item["id"] == "patient-nurse-realtime")
        plan = build_scenario_plan(scenario, store.load_profiles(), "assisted")
        self.assertTrue(any(step["actor_id"] == "patient" for step in plan))
        self.assertTrue(any(step["mode"] == "manual" for step in plan))

    def test_selector_map_contains_automation_targets(self):
        selector_map = DEFAULT_SELECTOR_MAPS["ncs"]
        self.assertIn("patient_scan", selector_map)
        self.assertIn("patient_services", selector_map)
        self.assertIn("nurse_calls", selector_map)

    def test_patient_nurse_scenario_contains_real_automation_steps(self):
        store = LabConfigStore()
        scenario = next(item for item in store.load_scenarios() if item["id"] == "patient-nurse-realtime")
        plan = build_scenario_plan(scenario, store.load_profiles(), "automated")
        actions = {step["action"] for step in plan}
        self.assertIn("patient_qr_login", actions)
        self.assertIn("patient_create_call", actions)
        self.assertIn("staff_login", actions)

    def test_admin_scenario_contains_real_automation_steps(self):
        store = LabConfigStore()
        scenario = next(item for item in store.load_scenarios() if item["id"] == "admin-operations")
        plan = build_scenario_plan(scenario, store.load_profiles(), "automated")
        actions = {step["action"] for step in plan}
        self.assertIn("staff_login", actions)
        self.assertIn("navigate", actions)

    def test_scenario_runner_engine_reports_backend_honestly(self):
        store = LabConfigStore()
        runner = ScenarioRunner(store, DEFAULT_APP_CONFIG, DEFAULT_SELECTOR_MAPS["ncs"])
        self.assertIn(runner.engine.backend_name, {"playwright", "unavailable"})
        self.assertIsInstance(runner.engine.describe(), str)

    def test_run_record_lifecycle(self):
        scenario = {"id": "demo", "name": "Demo Scenario"}
        run_record = create_run_record(scenario, "manual", "ncs")
        artifact_dir = ensure_artifact_dir(run_record)
        run_record["steps"] = [{"title": "Demo", "status": "manual", "message": "Manual review"}]
        finalized = finalize_run_record(run_record)
        self.assertEqual(finalized["status"], "manual-review")
        self.assertTrue(artifact_dir.exists())


if __name__ == "__main__":
    unittest.main()
