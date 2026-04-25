import json
from copy import deepcopy
from pathlib import Path

from .defaults import (
    DEFAULT_APP_CONFIG,
    DEFAULT_PRESETS,
    DEFAULT_PROFILES,
    DEFAULT_PROJECTS,
    DEFAULT_SCENARIOS,
    DEFAULT_SELECTOR_MAPS,
)
from .paths import (
    ACTIVE_SESSIONS_FILE,
    APP_CONFIG_FILE,
    PRESETS_FILE,
    PROFILES_FILE,
    PROJECTS_FILE,
    RUN_HISTORY_FILE,
    SCENARIOS_FILE,
    SELECTOR_MAPS_FILE,
    ensure_directories,
)


def _merge_missing(payload: dict, defaults: dict) -> dict:
    normalized = deepcopy(payload)
    for key, value in defaults.items():
        if key not in normalized:
            normalized[key] = deepcopy(value)
    return normalized


def _normalize_preset(preset: dict) -> dict:
    metadata = deepcopy(preset.get("metadata", {}))
    return {
        "id": preset["id"],
        "project_id": preset.get("project_id", "ncs"),
        "name": preset.get("name", preset["id"]),
        "kind": preset.get("kind", "staff"),
        "role": preset.get("role", "custom"),
        "route": preset.get("route", "#/"),
        "base_route": preset.get("base_route", preset.get("route", "#/")),
        "landing_route": preset.get("landing_route", preset.get("route", "#/")),
        "launch_mode": preset.get("launch_mode", "browser"),
        "login_email": preset.get("login_email", metadata.get("email", "")),
        "login_password": preset.get("login_password", metadata.get("password", "")),
        "qr_token": preset.get("qr_token", metadata.get("qr_token", "")),
        "locale": preset.get("locale", "en-US"),
        "theme": preset.get("theme", "system"),
        "tags": deepcopy(preset.get("tags", [])),
        "notes": preset.get("notes", ""),
        "metadata": metadata,
    }


def _normalize_profile(profile: dict) -> dict:
    metadata = deepcopy(profile.get("metadata", {}))
    route = profile.get("route", "#/")
    return {
        "id": profile["id"],
        "project_id": profile.get("project_id", "ncs"),
        "name": profile.get("name", profile["id"]),
        "preset_id": profile.get("preset_id", ""),
        "kind": profile.get("kind", "staff"),
        "role": profile.get("role", "custom"),
        "route": route,
        "base_route": profile.get("base_route", route),
        "landing_route": profile.get("landing_route", route),
        "launch_mode": profile.get("launch_mode", "browser"),
        "login_email": profile.get("login_email", metadata.get("email", "")),
        "login_password": profile.get("login_password", metadata.get("password", "")),
        "qr_token": profile.get("qr_token", metadata.get("qr_token", "")),
        "locale": profile.get("locale", "en-US"),
        "theme": profile.get("theme", "system"),
        "tags": deepcopy(profile.get("tags", [])),
        "notes": profile.get("notes", ""),
        "metadata": metadata,
    }


def _normalize_scenario(scenario: dict) -> dict:
    return {
        "id": scenario["id"],
        "project_id": scenario.get("project_id", "ncs"),
        "name": scenario.get("name", scenario["id"]),
        "summary": scenario.get("summary", scenario.get("description", "")),
        "description": scenario.get("description", ""),
        "goal": scenario.get("goal", ""),
        "supported_modes": deepcopy(scenario.get("supported_modes", ["manual"])),
        "default_mode": scenario.get("default_mode", "manual"),
        "participants": deepcopy(scenario.get("participants", scenario.get("items", []))),
        "steps": deepcopy(scenario.get("steps", [])),
    }


class LabConfigStore:
    def __init__(self) -> None:
        ensure_directories()
        self._bootstrap_file(APP_CONFIG_FILE, DEFAULT_APP_CONFIG)
        self._bootstrap_file(PROJECTS_FILE, DEFAULT_PROJECTS)
        self._bootstrap_file(PRESETS_FILE, DEFAULT_PRESETS)
        self._bootstrap_file(PROFILES_FILE, DEFAULT_PROFILES)
        self._bootstrap_file(SCENARIOS_FILE, DEFAULT_SCENARIOS)
        self._bootstrap_file(SELECTOR_MAPS_FILE, DEFAULT_SELECTOR_MAPS)
        self._bootstrap_file(ACTIVE_SESSIONS_FILE, [])
        self._bootstrap_file(RUN_HISTORY_FILE, [])

    def _bootstrap_file(self, path: Path, default_value) -> None:
        if path.exists():
            return
        path.write_text(json.dumps(default_value, indent=2), encoding="utf-8")

    def _load(self, path: Path, fallback):
        if not path.exists():
            return deepcopy(fallback)
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, path: Path, payload) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_app_config(self):
        payload = self._load(APP_CONFIG_FILE, DEFAULT_APP_CONFIG)
        normalized = _merge_missing(payload, DEFAULT_APP_CONFIG)
        if normalized != payload:
            self.save_app_config(normalized)
        return normalized

    def save_app_config(self, config) -> None:
        self._save(APP_CONFIG_FILE, config)

    def load_projects(self):
        return self._load(PROJECTS_FILE, DEFAULT_PROJECTS)

    def save_projects(self, projects) -> None:
        self._save(PROJECTS_FILE, projects)

    def load_presets(self):
        presets = [_normalize_preset(item) for item in self._load(PRESETS_FILE, DEFAULT_PRESETS)]
        self._save(PRESETS_FILE, presets)
        return presets

    def save_presets(self, presets) -> None:
        self._save(PRESETS_FILE, [_normalize_preset(item) for item in presets])

    def load_profiles(self):
        profiles = [_normalize_profile(item) for item in self._load(PROFILES_FILE, DEFAULT_PROFILES)]
        self._save(PROFILES_FILE, profiles)
        return profiles

    def save_profiles(self, profiles) -> None:
        self._save(PROFILES_FILE, [_normalize_profile(item) for item in profiles])

    def load_scenarios(self):
        scenarios = [_normalize_scenario(item) for item in self._load(SCENARIOS_FILE, DEFAULT_SCENARIOS)]
        self._save(SCENARIOS_FILE, scenarios)
        return scenarios

    def save_scenarios(self, scenarios) -> None:
        self._save(SCENARIOS_FILE, [_normalize_scenario(item) for item in scenarios])

    def load_selector_maps(self):
        return self._load(SELECTOR_MAPS_FILE, DEFAULT_SELECTOR_MAPS)

    def save_selector_maps(self, selector_maps) -> None:
        self._save(SELECTOR_MAPS_FILE, selector_maps)

    def load_active_sessions(self):
        return self._load(ACTIVE_SESSIONS_FILE, [])

    def save_active_sessions(self, sessions) -> None:
        self._save(ACTIVE_SESSIONS_FILE, sessions)

    def load_run_history(self):
        return self._load(RUN_HISTORY_FILE, [])

    def save_run_history(self, history) -> None:
        self._save(RUN_HISTORY_FILE, history)
