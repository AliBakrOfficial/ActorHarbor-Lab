from __future__ import annotations

from ..defaults import DEFAULT_PRESETS, DEFAULT_SCENARIOS, DEFAULT_SELECTOR_MAPS
from .base_adapter import BaseProjectAdapter


class NCSProjectAdapter(BaseProjectAdapter):
    project_id = "ncs"
    name = "Nursing Call System"
    description = "Standalone adapter for the NCS demo seeder identities, QR tokens, and multi-role routes."

    def get_seed_reference_lines(self) -> list[str]:
        return [
            "Source: ncs-backend/database/seeders/PilotDemoSeeder.php",
            "Default password: Password123!",
            "Patients: DEMO-ER-101-A / B, DEMO-ER-102-A, DEMO-MW-201-A / B",
            "Staff: super.admin@ncs-demo.test, admin@aura-demo.test, hospital.supervisor@aura-demo.test, department.supervisor@aura-demo.test, nurse.er@aura-demo.test, nurse.medical@aura-demo.test, nurse.float@aura-demo.test",
        ]

    def get_default_presets(self) -> list[dict]:
        return DEFAULT_PRESETS

    def get_default_scenarios(self) -> list[dict]:
        return DEFAULT_SCENARIOS

    def get_selector_map(self) -> dict:
        return DEFAULT_SELECTOR_MAPS["ncs"]
