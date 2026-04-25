import shutil
import subprocess
from pathlib import Path


COMMON_CHROME_PATHS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
]


def detect_chrome_path() -> str:
    for candidate in COMMON_CHROME_PATHS:
        if candidate.exists():
            return str(candidate)
    return ""


def slugify_profile_id(value: str) -> str:
    slug = []
    for character in value.lower():
        if character.isalnum():
            slug.append(character)
        elif character in {" ", "-", "_"}:
            slug.append("-")
    normalized = "".join(slug).strip("-")
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized or "profile"


def resolve_url(base_url: str, route: str) -> str:
    if route.startswith("http://") or route.startswith("https://"):
        return route
    base = base_url.rstrip("/")
    route_part = route if route.startswith("/") or route.startswith("#") else f"/{route}"
    return f"{base}/{route_part.lstrip('/')}" if not route_part.startswith("#") else f"{base}/{route_part}"


def profile_data_dir(chrome_data_root: Path, profile_id: str) -> Path:
    return chrome_data_root / slugify_profile_id(profile_id)


def is_safe_child(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def build_launch_command(
    chrome_path: str,
    profile_dir: Path,
    url: str,
    launch_mode: str = "browser",
    window_size: str = "1400,940",
    new_window: bool = True,
):
    command = [
        chrome_path,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
    ]

    if window_size:
        command.append(f"--window-size={window_size}")

    if new_window:
        command.append("--new-window")

    if launch_mode == "app":
        command.append(f"--app={url}")
    else:
        command.append(url)

    return command


def pid_is_running(pid: int) -> bool:
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
        capture_output=True,
        text=True,
        check=False,
    )
    return str(pid) in completed.stdout


def launch_chrome(command):
    return subprocess.Popen(command)


def close_pid(pid: int) -> bool:
    completed = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def reset_profile_dir(profile_dir: Path, chrome_root: Path) -> None:
    if not is_safe_child(chrome_root, profile_dir):
        raise ValueError("Profile reset target is outside the lab chrome-data root.")
    if profile_dir.exists():
        shutil.rmtree(profile_dir)


def delete_profile_dir(profile_dir: Path, chrome_root: Path) -> None:
    reset_profile_dir(profile_dir, chrome_root)
