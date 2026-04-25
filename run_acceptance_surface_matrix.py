from __future__ import annotations

import json
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

from lab.config_store import LabConfigStore
from lab.paths import ARTIFACTS_DIR, CHROME_DATA_DIR


VARIANTS = [
    {"locale": "ar", "theme": "dark"},
    {"locale": "ar", "theme": "light"},
    {"locale": "en-US", "theme": "dark"},
    {"locale": "en-US", "theme": "light"},
]

SURFACES = [
    {
        "id": "patient-completed-rating",
        "preset_id": "patient-er101a",
        "login_kind": "patient",
        "route": "#/patient/calls/69/completed",
    },
    {
        "id": "supervisor-call-detail",
        "preset_id": "supervisor-hospital",
        "login_kind": "staff",
        "route": "#/supervisor/calls/69",
    },
    {
        "id": "admin-beds",
        "preset_id": "admin-main",
        "login_kind": "staff",
        "route": "#/admin/beds",
    },
    {
        "id": "reports-overview",
        "preset_id": "admin-main",
        "login_kind": "staff",
        "route": "#/reports",
    },
    {
        "id": "super-admin-hospitals",
        "preset_id": "super-admin",
        "login_kind": "staff",
        "route": "#/super-admin/hospitals",
    },
]


def resolve_url(base_url: str, route: str) -> str:
    base = base_url.rstrip("/")
    if route.startswith("http://") or route.startswith("https://"):
        return route
    if route.startswith("#"):
        return f"{base}/{route}"
    if route.startswith("/"):
        return f"{base}{route}"
    return f"{base}/{route}"


def main() -> int:
    store = LabConfigStore()
    app_config = store.load_app_config()
    presets = {item["id"]: item for item in store.load_presets()}
    selectors = store.load_selector_maps()["ncs"]
    base_url = app_config["base_url"]
    chrome_path = app_config["chrome_path"]
    artifact_root = ARTIFACTS_DIR / "r2-acceptance-matrix"
    artifact_root.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []

    with sync_playwright() as playwright:
        for surface in SURFACES:
            preset = presets[surface["preset_id"]]
            for variant in VARIANTS:
                variant_id = f"{surface['id']}--{variant['locale']}--{variant['theme']}"
                profile_dir = CHROME_DATA_DIR / f"r2-{variant_id}"
                output_dir = artifact_root / surface["id"]
                output_dir.mkdir(parents=True, exist_ok=True)
                record = {
                    "surface": surface["id"],
                    "preset_id": surface["preset_id"],
                    "locale": variant["locale"],
                    "theme": variant["theme"],
                    "status": "failed",
                    "route": surface["route"],
                    "final_url": "",
                    "body_file": "",
                    "screenshot": "",
                    "error": "",
                }
                try:
                    if profile_dir.exists():
                        shutil.rmtree(profile_dir)
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        executable_path=chrome_path or None,
                        headless=False,
                        viewport={"width": 1400, "height": 940},
                        args=["--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble"],
                    )
                    try:
                        context.add_init_script(
                            script=f"""
                            (() => {{
                              localStorage.setItem('ncs.locale', {variant['locale']!r})
                              localStorage.setItem('ncs.theme', {variant['theme']!r})
                            }})()
                            """
                        )
                        page = context.pages[0] if context.pages else context.new_page()

                        if surface["login_kind"] == "staff":
                            page.goto(resolve_url(base_url, "#/staff/login"), wait_until="domcontentloaded")
                            page.locator(selectors["staff_login"]["email"]).first.fill(preset["login_email"])
                            page.locator(selectors["staff_login"]["password"]).first.fill(preset["login_password"])
                            page.locator(selectors["staff_login"]["submit"]).first.click()
                            page.wait_for_timeout(2200)
                        else:
                            page.goto(resolve_url(base_url, "#/patient/scan"), wait_until="domcontentloaded")
                            page.locator(selectors["patient_scan"]["manual_trigger"]).click()
                            page.locator(selectors["patient_scan"]["token"]).first.fill(preset["qr_token"])
                            page.locator(selectors["patient_scan"]["submit"]).first.click()
                            page.wait_for_timeout(2200)

                        target_url = resolve_url(base_url, surface["route"])
                        page.goto(target_url, wait_until="domcontentloaded")
                        page.wait_for_timeout(1800)

                        screenshot_path = output_dir / f"{variant['locale']}--{variant['theme']}.png"
                        body_path = output_dir / f"{variant['locale']}--{variant['theme']}.txt"
                        meta_path = output_dir / f"{variant['locale']}--{variant['theme']}.json"

                        page.screenshot(path=str(screenshot_path), full_page=False)
                        body_text = page.locator("body").inner_text()
                        body_path.write_text(body_text, encoding="utf-8")

                        record.update(
                            {
                                "status": "captured",
                                "final_url": page.url,
                                "body_file": str(body_path),
                                "screenshot": str(screenshot_path),
                            }
                        )
                        meta_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                    finally:
                        context.close()
                except Exception as exc:  # noqa: BLE001
                    record["error"] = str(exc)
                    error_path = output_dir / f"{variant['locale']}--{variant['theme']}--error.json"
                    error_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                summary.append(record)

    (artifact_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
