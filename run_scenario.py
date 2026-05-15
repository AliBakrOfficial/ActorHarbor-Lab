from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lab.chrome_manager import delete_profile_dir, pid_is_running, profile_data_dir
from lab.config_store import LabConfigStore
from lab.paths import CHROME_DATA_DIR
from lab.scenario_runner import ScenarioRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Local SaaS Lab scenario from the CLI.")
    parser.add_argument("scenario_id", help="Scenario id from data/scenarios.json")
    parser.add_argument("--mode", choices=["manual", "assisted", "automated"], default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--chrome-path", default=None)
    parser.add_argument("--launch-mode", choices=["browser", "app"], default=None)
    parser.add_argument("--headless", action="store_true", help="Run Playwright automation in headless mode.")
    parser.add_argument("--keep-open", action="store_true", help="Reopen participant windows after automated execution finishes.")
    parser.add_argument("--reset-profiles", action="store_true", help="Reset the scenario participant profiles before running.")
    args = parser.parse_args()

    store = LabConfigStore()
    app_config = store.load_app_config()
    selector_maps = store.load_selector_maps()
    scenarios = store.load_scenarios()
    profiles = store.load_profiles()

    scenario = next((item for item in scenarios if item["id"] == args.scenario_id), None)
    if scenario is None:
        print(json.dumps({"error": f"Scenario {args.scenario_id!r} was not found."}, indent=2))
        return 1

    if args.base_url:
        app_config["base_url"] = args.base_url
    if args.chrome_path:
        app_config["chrome_path"] = args.chrome_path
    if args.headless:
        app_config["headless_automation"] = True

    chrome_path = app_config.get("chrome_path", "")
    if not chrome_path or not Path(chrome_path).exists():
        print(json.dumps({"error": "A valid Chrome path is required.", "chrome_path": chrome_path}, indent=2))
        return 1

    if args.reset_profiles:
        participant_profile_ids = {participant["preset_id"] for participant in scenario.get("participants", [])}
        active_sessions = [session for session in store.load_active_sessions() if int(session.get("pid", 0)) and pid_is_running(int(session["pid"]))]
        store.save_active_sessions(active_sessions)
        busy_profiles = sorted({session["profile_id"] for session in active_sessions if session["profile_id"] in participant_profile_ids})
        if busy_profiles:
            print(json.dumps({"error": "Cannot reset profiles while active sessions are still tracked.", "profiles": busy_profiles}, indent=2))
            return 1
        for profile_id in participant_profile_ids:
            delete_profile_dir(profile_data_dir(CHROME_DATA_DIR, profile_id), CHROME_DATA_DIR)

    runner = ScenarioRunner(
        store,
        app_config,
        selector_maps.get(scenario.get("project_id", "ncs"), {}),
    )
    run_record = runner.run(
        scenario=scenario,
        profiles=profiles,
        mode=args.mode or scenario.get("default_mode", "assisted"),
        chrome_data_root=CHROME_DATA_DIR,
        chrome_path=chrome_path,
        launch_mode_override=args.launch_mode,
        keep_windows_open=args.keep_open,
    )
    print(json.dumps(run_record, indent=2))
    return 0 if run_record.get("status") in {"passed", "manual-review"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
