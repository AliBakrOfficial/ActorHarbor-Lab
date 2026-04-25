from copy import deepcopy


DEFAULT_APP_CONFIG = {
    "base_url": "http://127.0.0.1:9200",
    "chrome_path": "",
    "default_launch_mode": "browser",
    "default_window_size": "1400,940",
    "default_new_window": True,
    "default_positioning": {
        "split_lr": [
            {"x": 0, "y": 0, "width": 960, "height": 1040},
            {"x": 960, "y": 0, "width": 960, "height": 1040},
        ],
        "grid_2x2": [
            {"x": 0, "y": 0, "width": 960, "height": 520},
            {"x": 960, "y": 0, "width": 960, "height": 520},
            {"x": 0, "y": 520, "width": 960, "height": 520},
            {"x": 960, "y": 520, "width": 960, "height": 520},
        ],
    },
    "current_project": "ncs",
    "artifacts_open_after_run": False,
    "keep_windows_open_after_run": False,
    "headless_automation": False,
    "automation_timeout_ms": 15000,
    "screenshot_settle_ms": 250,
}


DEFAULT_PROJECTS = [
    {
        "id": "ncs",
        "name": "Nursing Call System",
        "adapter": "ncs",
        "description": "Seeded local multi-role rehearsal adapter for the NCS demo environment.",
        "base_url": "http://127.0.0.1:9200",
        "api_base_url": "http://127.0.0.1:8000/api/v1",
    }
]


DEFAULT_SELECTOR_MAPS = {
    "ncs": {
        "staff_login": {
            "email": 'input[type="email"], input[name="email"], input[autocomplete="username"]',
            "password": 'input[type="password"], input[name="password"], input[autocomplete="current-password"]',
            "submit": 'button[type="submit"]',
        },
        "patient_scan": {
            "manual_trigger": ".patient-scan-shell__manual-trigger",
            "token": 'input[type="text"]',
            "submit": 'button[type="submit"]',
        },
        "patient_welcome": {
            "help_link": 'a[href="#/patient/services"]',
        },
        "patient_services": {
            "service_card": ".patient-service-card",
            "confirm_submit": '.q-dialog .bg-primary, .q-dialog button[type="submit"]',
        },
        "nurse_calls": {
            "page_ready": 'body',
        },
        "global": {
            "page_ready": "body",
        },
    }
}


def _preset(
    preset_id: str,
    name: str,
    kind: str,
    role: str,
    route: str,
    *,
    login_email: str = "",
    login_password: str = "",
    qr_token: str = "",
    bed_label: str = "",
    landing_route: str = "",
    tags=None,
    scope: str = "",
):
    return {
        "id": preset_id,
        "project_id": "ncs",
        "name": name,
        "kind": kind,
        "role": role,
        "route": route,
        "base_route": route,
        "landing_route": landing_route or route,
        "launch_mode": "browser",
        "login_email": login_email,
        "login_password": login_password,
        "qr_token": qr_token,
        "locale": "en-US",
        "theme": "system",
        "tags": tags or [],
        "notes": "",
        "metadata": {
            "bed_label": bed_label,
            "scope": scope,
        },
    }


DEFAULT_PRESETS = [
    _preset(
        "patient-er101a",
        "Patient ER-101-A",
        "patient",
        "patient",
        "#/patient/scan",
        qr_token="DEMO-ER-101-A",
        bed_label="ER-101-A",
        landing_route="#/patient/welcome",
        tags=["patient", "qr", "emergency"],
    ),
    _preset(
        "patient-er101b",
        "Patient ER-101-B",
        "patient",
        "patient",
        "#/patient/scan",
        qr_token="DEMO-ER-101-B",
        bed_label="ER-101-B",
        landing_route="#/patient/welcome",
        tags=["patient", "qr", "emergency"],
    ),
    _preset(
        "patient-er102a",
        "Patient ER-102-A",
        "patient",
        "patient",
        "#/patient/scan",
        qr_token="DEMO-ER-102-A",
        bed_label="ER-102-A",
        landing_route="#/patient/welcome",
        tags=["patient", "qr", "emergency"],
    ),
    _preset(
        "patient-mw201a",
        "Patient MW-201-A",
        "patient",
        "patient",
        "#/patient/scan",
        qr_token="DEMO-MW-201-A",
        bed_label="MW-201-A",
        landing_route="#/patient/welcome",
        tags=["patient", "qr", "medical"],
    ),
    _preset(
        "patient-mw201b",
        "Patient MW-201-B",
        "patient",
        "patient",
        "#/patient/scan",
        qr_token="DEMO-MW-201-B",
        bed_label="MW-201-B",
        landing_route="#/patient/welcome",
        tags=["patient", "qr", "medical"],
    ),
    _preset(
        "nurse-er",
        "Nurse ER",
        "staff",
        "nurse",
        "#/staff/login",
        login_email="nurse.er@aura-demo.test",
        login_password="Password123!",
        landing_route="#/nurse/calls",
        tags=["staff", "nurse", "emergency"],
        scope="Emergency Department",
    ),
    _preset(
        "nurse-medical",
        "Nurse Medical",
        "staff",
        "nurse",
        "#/staff/login",
        login_email="nurse.medical@aura-demo.test",
        login_password="Password123!",
        landing_route="#/nurse/calls",
        tags=["staff", "nurse", "medical"],
        scope="Medical Ward",
    ),
    _preset(
        "nurse-float",
        "Nurse Float",
        "staff",
        "nurse",
        "#/staff/login",
        login_email="nurse.float@aura-demo.test",
        login_password="Password123!",
        landing_route="#/nurse/calls",
        tags=["staff", "nurse", "float"],
        scope="ER-101-A",
    ),
    _preset(
        "supervisor-hospital",
        "Hospital Supervisor",
        "staff",
        "hospital_supervisor",
        "#/staff/login",
        login_email="hospital.supervisor@aura-demo.test",
        login_password="Password123!",
        landing_route="#/supervisor/calls",
        tags=["staff", "supervisor", "hospital"],
    ),
    _preset(
        "supervisor-department",
        "Department Supervisor",
        "staff",
        "department_supervisor",
        "#/staff/login",
        login_email="department.supervisor@aura-demo.test",
        login_password="Password123!",
        landing_route="#/supervisor/calls",
        tags=["staff", "supervisor", "department"],
        scope="Emergency Department",
    ),
    _preset(
        "admin-main",
        "Admin",
        "staff",
        "admin",
        "#/staff/login",
        login_email="admin@aura-demo.test",
        login_password="Password123!",
        landing_route="#/admin/beds",
        tags=["staff", "admin"],
    ),
    _preset(
        "super-admin",
        "Super Admin",
        "staff",
        "super_admin",
        "#/staff/login",
        login_email="super.admin@ncs-demo.test",
        login_password="Password123!",
        landing_route="#/super-admin/hospitals",
        tags=["staff", "platform", "super-admin"],
    ),
]


DEFAULT_PROFILES = [
    {
        "id": preset["id"],
        "project_id": preset["project_id"],
        "name": preset["name"],
        "preset_id": preset["id"],
        "kind": preset["kind"],
        "role": preset["role"],
        "route": preset["route"],
        "base_route": preset["base_route"],
        "landing_route": preset["landing_route"],
        "launch_mode": preset["launch_mode"],
        "login_email": preset["login_email"],
        "login_password": preset["login_password"],
        "qr_token": preset["qr_token"],
        "locale": preset["locale"],
        "theme": preset["theme"],
        "tags": deepcopy(preset["tags"]),
        "notes": preset["notes"],
        "metadata": deepcopy(preset["metadata"]),
    }
    for preset in DEFAULT_PRESETS
]


DEFAULT_SCENARIOS = [
    {
        "id": "patient-nurse-realtime",
        "project_id": "ncs",
        "name": "Patient <-> Nurse Realtime",
        "summary": "Rehearse a patient QR entry against the ER nurse surface.",
        "description": "Uses a patient bed token plus the ER nurse login to walk through the core assistance request flow.",
        "goal": "Validate that the patient entry and nurse monitoring flow is reachable and observable.",
        "supported_modes": ["manual", "assisted", "automated"],
        "default_mode": "assisted",
        "participants": [
            {"id": "patient", "name": "Patient ER-101-A", "preset_id": "patient-er101a", "route": "#/patient/scan", "launch_mode": "browser"},
            {"id": "nurse", "name": "Nurse ER", "preset_id": "nurse-er", "route": "#/staff/login", "launch_mode": "browser"},
        ],
        "steps": [
            {
                "id": "patient-open-scan",
                "title": "Open patient scan route",
                "actor_id": "patient",
                "mode": "automated",
                "action": "navigate",
                "route": "#/patient/scan",
                "assertion": {"type": "url_contains", "value": "/#/patient/scan"},
                "screenshot": True,
                "guidance": "Patient window should land on the QR/session entry page.",
            },
            {
                "id": "patient-submit-token",
                "title": "Submit patient QR token",
                "actor_id": "patient",
                "mode": "automated",
                "action": "patient_qr_login",
                "assertion": {"type": "url_contains", "value": "/#/patient/welcome"},
                "screenshot": True,
                "guidance": "Submit the seeded QR token and reach the patient welcome surface.",
            },
            {
                "id": "patient-open-services",
                "title": "Open patient services flow",
                "actor_id": "patient",
                "mode": "automated",
                "action": "navigate",
                "route": "#/patient/services",
                "assertion": {"type": "url_contains", "value": "/#/patient/services"},
                "screenshot": True,
                "guidance": "Open the service request surface from the welcome page.",
            },
            {
                "id": "patient-create-call",
                "title": "Create a patient service call",
                "actor_id": "patient",
                "mode": "automated",
                "action": "patient_create_call",
                "route": "#/patient/services",
                "assertion": {"type": "url_contains", "value": "/#/patient/calls/"},
                "screenshot": True,
                "guidance": "Select the first service card and confirm the request dialog.",
            },
            {
                "id": "nurse-login",
                "title": "Log in as ER nurse",
                "actor_id": "nurse",
                "mode": "automated",
                "action": "staff_login",
                "route": "#/staff/login",
                "post_login_route": "#/nurse/calls",
                "settle_ms": 500,
                "assertion": {"type": "url_contains", "value": "/#/"},
                "screenshot": True,
                "guidance": "Use seeded nurse credentials and confirm the nurse surface becomes reachable.",
            },
            {
                "id": "nurse-review-calls",
                "title": "Reach nurse calls surface",
                "actor_id": "nurse",
                "mode": "automated",
                "action": "navigate",
                "route": "#/nurse/calls",
                "assertion": {"type": "body_contains", "value": "ER-101-A"},
                "screenshot": True,
                "guidance": "Nurse should reach the calls page and see the patient bed in the active calls list.",
            },
            {
                "id": "human-flow-checkpoint",
                "title": "Confirm patient-to-nurse interaction manually",
                "actor_id": "nurse",
                "mode": "manual",
                "action": "manual_checkpoint",
                "guidance": "Operator confirms whether the patient request becomes visible to the nurse and notes any realtime behavior.",
                "screenshot": True,
            },
        ],
    },
    {
        "id": "supervisor-oversight",
        "project_id": "ncs",
        "name": "Supervisor Scenario",
        "summary": "Validate department and hospital supervisor visibility.",
        "description": "Opens both supervisor roles and guides the operator through calls oversight surfaces.",
        "goal": "Ensure both supervisor actors can authenticate and review the oversight pages.",
        "supported_modes": ["manual", "assisted", "automated"],
        "default_mode": "assisted",
        "participants": [
            {"id": "department", "name": "Department Supervisor", "preset_id": "supervisor-department", "route": "#/staff/login", "launch_mode": "browser"},
            {"id": "hospital", "name": "Hospital Supervisor", "preset_id": "supervisor-hospital", "route": "#/staff/login", "launch_mode": "browser"},
        ],
        "steps": [
            {"id": "department-login", "title": "Log in as department supervisor", "actor_id": "department", "mode": "assisted", "action": "staff_login", "route": "#/staff/login", "assertion": {"type": "url_contains", "value": "/#/"}, "screenshot": True, "guidance": "Use seeded emergency department supervisor credentials."},
            {"id": "department-calls", "title": "Open department calls oversight", "actor_id": "department", "mode": "automated", "action": "navigate", "route": "#/supervisor/calls", "assertion": {"type": "url_contains", "value": "/#/supervisor/calls"}, "screenshot": True, "guidance": "Department supervisor should reach the calls page."},
            {"id": "hospital-login", "title": "Log in as hospital supervisor", "actor_id": "hospital", "mode": "assisted", "action": "staff_login", "route": "#/staff/login", "assertion": {"type": "url_contains", "value": "/#/"}, "screenshot": True, "guidance": "Use seeded hospital supervisor credentials."},
            {"id": "hospital-dashboard", "title": "Open hospital oversight surface", "actor_id": "hospital", "mode": "automated", "action": "navigate", "route": "#/supervisor/dashboard", "assertion": {"type": "url_contains", "value": "/#/supervisor"}, "screenshot": True, "guidance": "Hospital supervisor should reach the supervisory dashboard or calls area."},
        ],
    },
    {
        "id": "admin-operations",
        "project_id": "ncs",
        "name": "Admin Scenario",
        "summary": "Validate admin login, beds, and patient sessions surfaces.",
        "description": "Uses the hospital admin preset to review key admin operations pages.",
        "goal": "Ensure seeded admin can access the main hospital operations surfaces.",
        "supported_modes": ["manual", "assisted", "automated"],
        "default_mode": "assisted",
        "participants": [
            {"id": "admin", "name": "Admin", "preset_id": "admin-main", "route": "#/staff/login", "launch_mode": "browser"},
        ],
        "steps": [
            {"id": "admin-login", "title": "Log in as admin", "actor_id": "admin", "mode": "assisted", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/admin/beds", "settle_ms": 500, "assertion": {"type": "url_contains", "value": "/#/"}, "screenshot": True, "guidance": "Use the seeded admin account."},
            {"id": "admin-beds", "title": "Open beds management", "actor_id": "admin", "mode": "automated", "action": "navigate", "route": "#/admin/beds", "assertion": {"type": "body_contains", "value": "ER-101-A"}, "wait_for_text": "ER-101-A", "settle_ms": 500, "screenshot": True, "guidance": "Admin beds page should be reachable and seeded bed data should be visible."},
            {"id": "admin-sessions", "title": "Open patient sessions", "actor_id": "admin", "mode": "automated", "action": "navigate", "route": "#/admin/patient-sessions", "assertion": {"type": "body_contains", "value": "ER-101-A"}, "wait_for_text": "ER-101-A", "settle_ms": 500, "screenshot": True, "guidance": "Admin patient session page should be reachable and seeded sessions should be visible."},
        ],
    },
    {
        "id": "super-admin-platform",
        "project_id": "ncs",
        "name": "Super-admin Scenario",
        "summary": "Validate platform-level access to hospitals and admin directory surfaces.",
        "description": "Uses the seeded super-admin identity to reach SaaS platform views.",
        "goal": "Ensure super-admin can access the platform surfaces needed for SaaS simulation.",
        "supported_modes": ["manual", "assisted", "automated"],
        "default_mode": "assisted",
        "participants": [
            {"id": "platform", "name": "Super Admin", "preset_id": "super-admin", "route": "#/staff/login", "launch_mode": "browser"},
        ],
        "steps": [
            {"id": "platform-login", "title": "Log in as super-admin", "actor_id": "platform", "mode": "assisted", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/super-admin/hospitals", "settle_ms": 500, "assertion": {"type": "url_contains", "value": "/#/"}, "screenshot": True, "guidance": "Use the seeded platform super-admin account."},
            {"id": "platform-hospitals", "title": "Open hospitals surface", "actor_id": "platform", "mode": "automated", "action": "navigate", "route": "#/super-admin/hospitals", "assertion": {"type": "url_contains", "value": "/#/super-admin/hospitals"}, "settle_ms": 500, "screenshot": True, "guidance": "Hospitals page should open."},
            {"id": "platform-admins", "title": "Open admins directory", "actor_id": "platform", "mode": "automated", "action": "navigate", "route": "#/super-admin/admins", "assertion": {"type": "url_contains", "value": "/#/super-admin"}, "settle_ms": 500, "screenshot": True, "guidance": "Super-admin admin directory page should open."},
        ],
    },
    {
        "id": "reports-validation",
        "project_id": "ncs",
        "name": "Reports Scenario",
        "summary": "Validate the reports surface under an authenticated admin actor.",
        "description": "Reaches the reports surface and captures an artifact for later review.",
        "goal": "Make reports validation repeatable as part of local SaaS simulation rehearsals.",
        "supported_modes": ["manual", "assisted", "automated"],
        "default_mode": "assisted",
        "participants": [
            {"id": "reports-admin", "name": "Admin", "preset_id": "admin-main", "route": "#/staff/login", "launch_mode": "browser"},
        ],
        "steps": [
            {"id": "reports-login", "title": "Authenticate admin", "actor_id": "reports-admin", "mode": "automated", "action": "staff_login", "route": "#/staff/login", "post_login_route": "#/reports", "settle_ms": 500, "assertion": {"type": "url_contains", "value": "/#/"}, "screenshot": True, "guidance": "Log in before opening reports."},
            {"id": "reports-open", "title": "Open reports surface", "actor_id": "reports-admin", "mode": "automated", "action": "navigate", "route": "#/reports", "assertion": {"type": "url_contains", "value": "/#/reports"}, "settle_ms": 700, "screenshot": True, "guidance": "Reports page should become reachable and screenshot-worthy."},
            {"id": "reports-manual-review", "title": "Review reports filters or KPIs manually", "actor_id": "reports-admin", "mode": "manual", "action": "manual_checkpoint", "guidance": "Operator confirms that reports data loads and records observations in notes.", "screenshot": True},
        ],
    },
]


def legacy_metadata_for_display(preset_or_profile: dict) -> dict:
    metadata = deepcopy(preset_or_profile.get("metadata", {}))
    if preset_or_profile.get("login_email"):
        metadata["email"] = preset_or_profile["login_email"]
    if preset_or_profile.get("login_password"):
        metadata["password"] = preset_or_profile["login_password"]
    if preset_or_profile.get("qr_token"):
        metadata["qr_token"] = preset_or_profile["qr_token"]
    if preset_or_profile.get("landing_route"):
        metadata["landing_route"] = preset_or_profile["landing_route"]
    return metadata
