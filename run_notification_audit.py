from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from lab.chrome_manager import delete_profile_dir, pid_is_running, profile_data_dir
from lab.config_store import LabConfigStore
from lab.paths import CHROME_DATA_DIR
from lab.scenario_runner import ScenarioRunner


def _http_ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=5) as response:
            return 200 <= getattr(response, "status", 0) < 500
    except (OSError, URLError):
        return False


def ensure_environment_ready(store: LabConfigStore, app_config: dict) -> None:
    if not _http_ready(app_config["base_url"]):
        raise RuntimeError(f"Frontend base URL is not reachable: {app_config['base_url']}")

    projects = {project["id"]: project for project in store.load_projects()}
    current_project = projects.get(app_config.get("current_project", "ncs"), {})
    api_health_url = current_project.get("api_base_url", "http://127.0.0.1:8000/api/v1").rstrip("/") + "/health"
    if not _http_ready(api_health_url):
        raise RuntimeError(f"Backend health URL is not reachable: {api_health_url}")


def build_scenarios() -> list[dict]:
    return [
        {
            "id": "er5a-a-outside-calls",
            "project_id": "ncs",
            "name": "ER-5a A Outside Calls",
            "default_mode": "automated",
            "participants": [
                {"id": "nurse", "name": "Nurse ER", "preset_id": "nurse-er", "route": "#/staff/login"},
                {"id": "patient", "name": "Patient ER-101-A", "preset_id": "patient-er101a", "route": "#/patient/scan"},
                {"id": "helper", "name": "Nurse Float", "preset_id": "nurse-float", "route": "#/staff/login"},
            ],
            "steps": [
                {"id": "nurse-login", "title": "Log in nurse on calls route", "actor_id": "nurse", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "nurse-open-performance", "title": "Move nurse to non-calls route", "actor_id": "nurse", "mode": "automated", "action": "navigate", "route": "#/nurse/performance", "assertion": {"type": "url_contains", "value": "/#/nurse/performance"}},
                {"id": "nurse-baseline-state", "title": "Capture outside-calls cleanup baseline", "actor_id": "nurse", "mode": "automated", "action": "assert_state", "remember_as": "outside_calls_baseline", "checks": [{"kind": "url_contains", "value": "/#/nurse/performance"}, {"kind": "selector_absent", "value": ".staff-shell-layout__lifecycle-cta"}]},
                {"id": "patient-login", "title": "Start patient session", "actor_id": "patient", "mode": "automated", "action": "patient_qr_login", "route": "#/patient/scan", "assertion": {"type": "url_contains", "value": "/#/patient/welcome"}},
                {"id": "patient-open-services", "title": "Open patient services", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/services"}, "wait_for_selector_key": "patient_services.service_card"},
                {"id": "patient-create-call", "title": "Create actionable call", "actor_id": "patient", "mode": "automated", "action": "patient_create_call", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/calls/"}, "screenshot": True},
                {
                    "id": "nurse-cta-state",
                    "title": "Validate CTA and badge outside calls page",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/performance"},
                        {"kind": "selector_visible", "value": ".staff-shell-layout__lifecycle-cta"},
                        {"kind": "selector_visible", "value": ".staff-shell-layout__lifecycle-progress"},
                        {"kind": "badge_count_at_least", "value": 1},
                    ],
                    "screenshot": True,
                },
                {"id": "helper-login", "title": "Log in helper nurse", "actor_id": "helper", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "helper-accept", "title": "Accept call from another actor", "actor_id": "helper", "mode": "automated", "action": "click", "selector": ".operational-call-card__actions .q-btn", "selector_index": 0, "wait_ms": 900, "screenshot": True},
                {"id": "nurse-settle", "title": "Let outside-calls lifecycle settle", "actor_id": "nurse", "mode": "automated", "action": "wait", "wait_ms": 1200},
                {
                    "id": "nurse-cleanup-state",
                    "title": "Validate CTA cleanup after call becomes non-actionable",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/performance"},
                        {"kind": "selector_absent", "value": ".staff-shell-layout__lifecycle-cta"},
                        {"kind": "badge_count_matches_memory", "value": "outside_calls_baseline"},
                    ],
                    "screenshot": True,
                },
            ],
        },
        {
            "id": "er5a-b-inside-calls",
            "project_id": "ncs",
            "name": "ER-5a B Inside Calls",
            "default_mode": "automated",
            "participants": [
                {"id": "nurse", "name": "Nurse ER", "preset_id": "nurse-er", "route": "#/staff/login"},
                {"id": "patient", "name": "Patient ER-101-A", "preset_id": "patient-er101a", "route": "#/patient/scan"},
                {"id": "helper", "name": "Nurse Float", "preset_id": "nurse-float", "route": "#/staff/login"},
            ],
            "steps": [
                {"id": "nurse-login-calls", "title": "Log in nurse on calls page", "actor_id": "nurse", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "patient-login", "title": "Start patient session", "actor_id": "patient", "mode": "automated", "action": "patient_qr_login", "route": "#/patient/scan", "assertion": {"type": "url_contains", "value": "/#/patient/welcome"}},
                {"id": "patient-open-services", "title": "Open patient services", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/services"}, "wait_for_selector_key": "patient_services.service_card"},
                {"id": "patient-create-call", "title": "Create actionable call", "actor_id": "patient", "mode": "automated", "action": "patient_create_call", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/calls/"}, "screenshot": True},
                {
                    "id": "nurse-highlight-state",
                    "title": "Validate highlight-only behavior on calls page",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/calls"},
                        {"kind": "selector_absent", "value": ".q-notification"},
                        {"kind": "highlighted_count_at_least", "value": 1},
                        {"kind": "call_cards_count_at_least", "value": 1},
                    ],
                    "screenshot": True,
                },
                {"id": "helper-login", "title": "Log in helper nurse", "actor_id": "helper", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "helper-accept", "title": "Accept call from another actor", "actor_id": "helper", "mode": "automated", "action": "click", "selector": ".operational-call-card__actions .q-btn", "selector_index": 0, "wait_ms": 900, "screenshot": True},
                {"id": "nurse-cleanup-wait", "title": "Let calls-page cleanup settle", "actor_id": "nurse", "mode": "automated", "action": "wait", "wait_ms": 1200},
                {
                    "id": "nurse-post-accept-state",
                    "title": "Validate highlight cleanup after another actor accepts",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/calls"},
                        {"kind": "selector_absent", "value": ".q-notification"},
                        {"kind": "highlighted_count_exact", "value": 0},
                    ],
                    "screenshot": True,
                },
            ],
        },
        {
            "id": "er5a-c-same-user-two-tabs",
            "project_id": "ncs",
            "name": "ER-5a C Same User Two Tabs",
            "default_mode": "automated",
            "participants": [
                {"id": "nurse", "name": "Nurse ER", "preset_id": "nurse-er", "route": "#/staff/login"},
                {"id": "patient", "name": "Patient ER-101-A", "preset_id": "patient-er101a", "route": "#/patient/scan"},
            ],
            "steps": [
                {"id": "nurse-login-calls", "title": "Log in nurse on calls page", "actor_id": "nurse", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "nurse-open-performance", "title": "Move nurse to performance page", "actor_id": "nurse", "mode": "automated", "action": "navigate", "route": "#/nurse/performance", "assertion": {"type": "url_contains", "value": "/#/nurse/performance"}},
                {"id": "nurse-open-calls-tab", "title": "Open calls tab for same user", "actor_id": "nurse", "mode": "automated", "action": "open_tab", "target_tab_id": "calls", "route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "nurse-return-performance", "title": "Return to performance tab", "actor_id": "nurse", "mode": "automated", "action": "activate_tab", "tab_id": "main"},
                {"id": "patient-login", "title": "Start patient session", "actor_id": "patient", "mode": "automated", "action": "patient_qr_login", "route": "#/patient/scan", "assertion": {"type": "url_contains", "value": "/#/patient/welcome"}},
                {"id": "patient-open-services", "title": "Open patient services", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/services"}, "wait_for_selector_key": "patient_services.service_card"},
                {"id": "patient-create-call", "title": "Create actionable call", "actor_id": "patient", "mode": "automated", "action": "patient_create_call", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/calls/"}, "screenshot": True},
                {
                    "id": "nurse-performance-state",
                    "title": "Validate CTA on non-calls tab",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "tab_id": "main",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/performance"},
                        {"kind": "selector_visible", "value": ".staff-shell-layout__lifecycle-cta"},
                        {"kind": "badge_count_at_least", "value": 1},
                    ],
                    "screenshot": True,
                },
                {"id": "nurse-open-calls-active", "title": "Switch to calls tab", "actor_id": "nurse", "mode": "automated", "action": "activate_tab", "tab_id": "calls"},
                {
                    "id": "nurse-calls-tab-state",
                    "title": "Validate highlight-only on calls tab",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "tab_id": "calls",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/calls"},
                        {"kind": "selector_absent", "value": ".q-notification"},
                        {"kind": "highlighted_count_at_least", "value": 1},
                    ],
                    "screenshot": True,
                },
            ],
        },
        {
            "id": "er5a-d-hidden-visible",
            "project_id": "ncs",
            "name": "ER-5a D Hidden Visible",
            "default_mode": "automated",
            "participants": [
                {"id": "nurse", "name": "Nurse ER", "preset_id": "nurse-er", "route": "#/staff/login"},
                {"id": "patient", "name": "Patient ER-101-A", "preset_id": "patient-er101a", "route": "#/patient/scan"},
                {"id": "helper", "name": "Nurse Float", "preset_id": "nurse-float", "route": "#/staff/login"},
            ],
            "steps": [
                {"id": "nurse-login-calls", "title": "Log in nurse on calls page", "actor_id": "nurse", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "nurse-open-performance", "title": "Move nurse to performance page", "actor_id": "nurse", "mode": "automated", "action": "navigate", "route": "#/nurse/performance", "assertion": {"type": "url_contains", "value": "/#/nurse/performance"}},
                {"id": "nurse-hidden-baseline", "title": "Capture hidden-visible cleanup baseline", "actor_id": "nurse", "mode": "automated", "action": "assert_state", "remember_as": "hidden_visible_baseline", "checks": [{"kind": "url_contains", "value": "/#/nurse/performance"}, {"kind": "selector_absent", "value": ".staff-shell-layout__lifecycle-cta"}]},
                {"id": "nurse-open-calls-tab", "title": "Open calls tab", "actor_id": "nurse", "mode": "automated", "action": "open_tab", "target_tab_id": "calls", "route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "nurse-hide-performance", "title": "Keep performance tab hidden", "actor_id": "nurse", "mode": "automated", "action": "activate_tab", "tab_id": "calls"},
                {
                    "id": "nurse-hidden-check",
                    "title": "Verify performance tab is hidden",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "tab_id": "main",
                    "checks": [
                        {"kind": "visibility_state", "value": "hidden"},
                        {"kind": "url_contains", "value": "/#/nurse/performance"},
                    ],
                    "screenshot": True,
                },
                {"id": "patient-login", "title": "Start patient session", "actor_id": "patient", "mode": "automated", "action": "patient_qr_login", "route": "#/patient/scan", "assertion": {"type": "url_contains", "value": "/#/patient/welcome"}},
                {"id": "patient-open-services", "title": "Open patient services", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/services"}, "wait_for_selector_key": "patient_services.service_card"},
                {"id": "patient-create-call", "title": "Create actionable call", "actor_id": "patient", "mode": "automated", "action": "patient_create_call", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/calls/"}},
                {"id": "helper-login", "title": "Log in helper nurse", "actor_id": "helper", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "helper-accept", "title": "Accept call while target tab is hidden", "actor_id": "helper", "mode": "automated", "action": "click", "selector": ".operational-call-card__actions .q-btn", "selector_index": 0, "wait_ms": 900},
                {"id": "nurse-show-performance", "title": "Return to performance tab", "actor_id": "nurse", "mode": "automated", "action": "activate_tab", "tab_id": "main"},
                {
                    "id": "nurse-visible-clean-state",
                    "title": "Validate stale cleanup after returning to visible tab",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "tab_id": "main",
                    "checks": [
                        {"kind": "visibility_state", "value": "visible"},
                        {"kind": "url_contains", "value": "/#/nurse/performance"},
                        {"kind": "selector_absent", "value": ".staff-shell-layout__lifecycle-cta"},
                        {"kind": "badge_count_matches_memory", "value": "hidden_visible_baseline"},
                    ],
                    "screenshot": True,
                },
            ],
        },
        {
            "id": "er5a-e-refresh-reconnect",
            "project_id": "ncs",
            "name": "ER-5a E Refresh Reconnect",
            "default_mode": "automated",
            "participants": [
                {"id": "nurse", "name": "Nurse ER", "preset_id": "nurse-er", "route": "#/staff/login"},
                {"id": "patient", "name": "Patient ER-101-A", "preset_id": "patient-er101a", "route": "#/patient/scan"},
            ],
            "steps": [
                {"id": "nurse-login-calls", "title": "Log in nurse on calls page", "actor_id": "nurse", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "patient-login", "title": "Start patient session", "actor_id": "patient", "mode": "automated", "action": "patient_qr_login", "route": "#/patient/scan", "assertion": {"type": "url_contains", "value": "/#/patient/welcome"}},
                {"id": "patient-open-services", "title": "Open patient services", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/services"}, "wait_for_selector_key": "patient_services.service_card"},
                {"id": "patient-create-call", "title": "Create actionable call", "actor_id": "patient", "mode": "automated", "action": "patient_create_call", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/calls/"}},
                {
                    "id": "nurse-pre-refresh-state",
                    "title": "Capture pre-refresh queue state",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/calls"},
                        {"kind": "call_cards_count_at_least", "value": 1},
                        {"kind": "highlighted_count_at_least", "value": 1},
                    ],
                    "screenshot": True,
                },
                {"id": "nurse-reload", "title": "Reload nurse calls page", "actor_id": "nurse", "mode": "automated", "action": "reload", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}, "screenshot": True},
                {
                    "id": "nurse-post-refresh-state",
                    "title": "Validate refreshed queue state without duplicate CTA",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/calls"},
                        {"kind": "call_cards_count_at_least", "value": 1},
                        {"kind": "selector_absent", "value": ".q-notification"},
                    ],
                    "screenshot": True,
                },
            ],
        },
        {
            "id": "er5a-f-fast-race",
            "project_id": "ncs",
            "name": "ER-5a F Fast Race",
            "default_mode": "automated",
            "participants": [
                {"id": "nurse", "name": "Nurse ER", "preset_id": "nurse-er", "route": "#/staff/login"},
                {"id": "patient", "name": "Patient ER-101-A", "preset_id": "patient-er101a", "route": "#/patient/scan"},
                {"id": "helper", "name": "Nurse Float", "preset_id": "nurse-float", "route": "#/staff/login"},
            ],
            "steps": [
                {"id": "nurse-login", "title": "Log in nurse on non-calls route", "actor_id": "nurse", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/performance", "assertion": {"type": "url_contains", "value": "/#/nurse/performance"}},
                {"id": "patient-login", "title": "Start patient session", "actor_id": "patient", "mode": "automated", "action": "patient_qr_login", "route": "#/patient/scan", "assertion": {"type": "url_contains", "value": "/#/patient/welcome"}},
                {"id": "patient-open-services", "title": "Open patient services", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/services"}},
                {"id": "patient-create-call", "title": "Create actionable call", "actor_id": "patient", "mode": "automated", "action": "patient_create_call", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/calls/"}},
                {"id": "helper-login", "title": "Log in helper nurse", "actor_id": "helper", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/nurse/calls", "assertion": {"type": "url_contains", "value": "/#/nurse/calls"}},
                {"id": "helper-accept", "title": "Accept call quickly", "actor_id": "helper", "mode": "automated", "action": "click", "selector": ".operational-call-card__actions .q-btn", "selector_index": 0, "wait_ms": 350},
                {"id": "helper-complete", "title": "Complete call quickly", "actor_id": "helper", "mode": "automated", "action": "click", "selector": "button:has-text(\"Complete call\")", "wait_ms": 500},
                {"id": "nurse-race-settle", "title": "Allow race cleanup to settle", "actor_id": "nurse", "mode": "automated", "action": "wait", "wait_ms": 1400},
                {
                    "id": "nurse-race-clean-state",
                    "title": "Validate ghost CTA cleanup after fast race",
                    "actor_id": "nurse",
                    "mode": "automated",
                    "action": "assert_state",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/nurse/performance"},
                        {"kind": "selector_absent", "value": ".staff-shell-layout__lifecycle-cta"},
                        {"kind": "text_absent", "value": "Open calls"},
                        {"kind": "badge_count_exact", "value": 0},
                    ],
                    "screenshot": True,
                },
            ],
        },
        {
            "id": "er5a-g1-supervisor-outside",
            "project_id": "ncs",
            "name": "ER-5a G1 Supervisor Outside Calls",
            "default_mode": "automated",
            "participants": [
                {"id": "hospital", "name": "Hospital Supervisor", "preset_id": "supervisor-hospital", "route": "#/staff/login"},
                {"id": "department", "name": "Department Supervisor", "preset_id": "supervisor-department", "route": "#/staff/login"},
                {"id": "patient", "name": "Patient ER-101-A", "preset_id": "patient-er101a", "route": "#/patient/scan"},
            ],
            "steps": [
                {"id": "hospital-login-dashboard", "title": "Log in hospital supervisor on dashboard", "actor_id": "hospital", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/supervisor/dashboard", "assertion": {"type": "url_contains", "value": "/#/supervisor/dashboard"}},
                {"id": "department-login-calls", "title": "Log in department supervisor on calls page", "actor_id": "department", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/supervisor/calls", "assertion": {"type": "url_contains", "value": "/#/supervisor/calls"}},
                {"id": "patient-login", "title": "Start patient session", "actor_id": "patient", "mode": "automated", "action": "patient_qr_login", "route": "#/patient/scan", "assertion": {"type": "url_contains", "value": "/#/patient/welcome"}},
                {"id": "patient-open-services", "title": "Open patient services", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/services"}, "wait_for_selector_key": "patient_services.service_card"},
                {"id": "patient-create-call", "title": "Create call for escalation", "actor_id": "patient", "mode": "automated", "action": "patient_create_call", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/calls/"}},
                {"id": "department-open-escalate", "title": "Open manual escalation dialog", "actor_id": "department", "mode": "automated", "action": "click", "selector": ".operational-call-card__actions .q-btn", "selector_index": 1, "wait_ms": 500},
                {"id": "department-confirm-escalate", "title": "Confirm manual escalation", "actor_id": "department", "mode": "automated", "action": "click", "selector": ".supervisor-action-card--warning .q-btn", "selector_index": 0, "wait_ms": 1200, "screenshot": True},
                {
                    "id": "hospital-cta-state",
                    "title": "Validate supervisor CTA outside calls page",
                    "actor_id": "hospital",
                    "mode": "automated",
                    "action": "assert_state",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/supervisor/dashboard"},
                        {"kind": "selector_visible", "value": ".staff-shell-layout__lifecycle-cta"},
                        {"kind": "badge_count_at_least", "value": 1},
                    ],
                    "screenshot": True,
                },
            ],
        },
        {
            "id": "er5a-g2-supervisor-inside",
            "project_id": "ncs",
            "name": "ER-5a G2 Supervisor Inside Calls",
            "default_mode": "automated",
            "participants": [
                {"id": "hospital", "name": "Hospital Supervisor", "preset_id": "supervisor-hospital", "route": "#/staff/login"},
                {"id": "department", "name": "Department Supervisor", "preset_id": "supervisor-department", "route": "#/staff/login"},
                {"id": "patient", "name": "Patient ER-101-A", "preset_id": "patient-er101a", "route": "#/patient/scan"},
            ],
            "steps": [
                {"id": "hospital-login-calls", "title": "Log in hospital supervisor on calls page", "actor_id": "hospital", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/supervisor/calls", "assertion": {"type": "url_contains", "value": "/#/supervisor/calls"}},
                {"id": "department-login-calls", "title": "Log in department supervisor on calls page", "actor_id": "department", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/supervisor/calls", "assertion": {"type": "url_contains", "value": "/#/supervisor/calls"}},
                {"id": "patient-login", "title": "Start patient session", "actor_id": "patient", "mode": "automated", "action": "patient_qr_login", "route": "#/patient/scan", "assertion": {"type": "url_contains", "value": "/#/patient/welcome"}},
                {"id": "patient-open-services", "title": "Open patient services", "actor_id": "patient", "mode": "automated", "action": "navigate", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/services"}, "wait_for_selector_key": "patient_services.service_card"},
                {"id": "patient-create-call", "title": "Create call for escalation", "actor_id": "patient", "mode": "automated", "action": "patient_create_call", "route": "#/patient/services", "assertion": {"type": "url_contains", "value": "/#/patient/calls/"}},
                {"id": "department-open-escalate", "title": "Open manual escalation dialog", "actor_id": "department", "mode": "automated", "action": "click", "selector": ".operational-call-card__actions .q-btn", "selector_index": 1, "wait_ms": 500},
                {"id": "department-confirm-escalate", "title": "Confirm manual escalation", "actor_id": "department", "mode": "automated", "action": "click", "selector": ".supervisor-action-card--warning .q-btn", "selector_index": 0, "wait_ms": 1200, "screenshot": True},
                {
                    "id": "hospital-highlight-state",
                    "title": "Validate highlight-only supervisor behavior on calls page",
                    "actor_id": "hospital",
                    "mode": "automated",
                    "action": "assert_state",
                    "checks": [
                        {"kind": "url_contains", "value": "/#/supervisor/calls"},
                        {"kind": "selector_absent", "value": ".q-notification"},
                        {"kind": "highlighted_count_at_least", "value": 1},
                        {"kind": "call_cards_count_at_least", "value": 1},
                    ],
                    "screenshot": True,
                },
            ],
        },
    ]


def reset_scenario_profiles(store: LabConfigStore, scenario: dict) -> None:
    participant_profile_ids = {participant["preset_id"] for participant in scenario.get("participants", [])}
    active_sessions = [session for session in store.load_active_sessions() if int(session.get("pid", 0)) and pid_is_running(int(session["pid"]))]
    store.save_active_sessions(active_sessions)
    busy_profiles = sorted({session["profile_id"] for session in active_sessions if session["profile_id"] in participant_profile_ids})
    if busy_profiles:
        raise RuntimeError(f"Cannot reset profiles while active sessions are still tracked: {', '.join(busy_profiles)}")
    for profile_id in participant_profile_ids:
        delete_profile_dir(profile_data_dir(CHROME_DATA_DIR, profile_id), CHROME_DATA_DIR)


def run_audit(args) -> dict:
    store = LabConfigStore()
    app_config = store.load_app_config()
    if args.base_url:
        app_config["base_url"] = args.base_url
    if args.chrome_path:
        app_config["chrome_path"] = args.chrome_path
    if args.headless:
        app_config["headless_automation"] = True

    chrome_path = app_config.get("chrome_path", "")
    if not chrome_path or not Path(chrome_path).exists():
        raise RuntimeError(f"A valid Chrome path is required. Current value: {chrome_path!r}")

    ensure_environment_ready(store, app_config)

    selector_maps = store.load_selector_maps()
    profiles = store.load_profiles()
    scenarios = build_scenarios()
    if args.only:
        requested = {item.strip() for item in args.only.split(",") if item.strip()}
        scenarios = [scenario for scenario in scenarios if scenario["id"] in requested]

    runner = ScenarioRunner(
        store,
        app_config,
        selector_maps.get("ncs", {}),
    )

    results = []
    for scenario in scenarios:
        if args.reset_profiles:
            reset_scenario_profiles(store, scenario)
        run_record = runner.run(
            scenario=scenario,
            profiles=profiles,
            mode="automated",
            chrome_data_root=CHROME_DATA_DIR,
            chrome_path=chrome_path,
            keep_windows_open=args.keep_open,
        )
        results.append(
            {
                "scenario_id": scenario["id"],
                "name": scenario["name"],
                "status": run_record.get("status"),
                "summary": run_record.get("summary"),
                "artifact_dir": run_record.get("artifact_dir"),
            }
        )

    return {
        "results": results,
        "all_passed": all(item["status"] == "passed" for item in results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ER-5a notification lifecycle runtime audit matrix.")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--chrome-path", default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--reset-profiles", action="store_true")
    parser.add_argument("--only", default=None, help="Comma-separated scenario ids to run.")
    args = parser.parse_args()

    payload = run_audit(args)
    print(json.dumps(payload, indent=2))
    return 0 if payload["all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
