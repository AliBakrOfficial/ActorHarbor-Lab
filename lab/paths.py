from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = LAB_ROOT / "data"
RUNTIME_DIR = LAB_ROOT / "runtime"
CHROME_DATA_DIR = RUNTIME_DIR / "chrome-data"
STATE_DIR = RUNTIME_DIR / "state"
ARTIFACTS_DIR = RUNTIME_DIR / "artifacts"
ACTIVE_SESSIONS_FILE = STATE_DIR / "active_sessions.json"
RUN_HISTORY_FILE = STATE_DIR / "run_history.json"
APP_CONFIG_FILE = DATA_DIR / "app_config.json"
PROJECTS_FILE = DATA_DIR / "projects.json"
PRESETS_FILE = DATA_DIR / "presets.json"
PROFILES_FILE = DATA_DIR / "profiles.json"
SCENARIOS_FILE = DATA_DIR / "scenarios.json"
SELECTOR_MAPS_FILE = DATA_DIR / "selector_maps.json"


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    CHROME_DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
