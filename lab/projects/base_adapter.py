from __future__ import annotations

from abc import ABC, abstractmethod


class BaseProjectAdapter(ABC):
    """Project-specific mapping layer for the generic simulation-lab core.

    The core owns orchestration, history, artifacts, and UI behavior.
    Adapters own application-specific knowledge such as routes, selectors,
    presets, and seeded scenario definitions.
    """

    project_id: str = ""
    name: str = ""
    description: str = ""

    @abstractmethod
    def get_seed_reference_lines(self) -> list[str]:
        """Return short operator-facing seed/reference lines for the current project."""
        raise NotImplementedError

    @abstractmethod
    def get_default_presets(self) -> list[dict]:
        """Return adapter-owned default presets for actors/roles."""
        raise NotImplementedError

    @abstractmethod
    def get_default_scenarios(self) -> list[dict]:
        """Return adapter-owned default scenario definitions."""
        raise NotImplementedError

    @abstractmethod
    def get_selector_map(self) -> dict:
        """Return adapter-owned selector groups keyed by surface."""
        raise NotImplementedError

    def describe_preset(self, preset: dict) -> str:
        details = [
            f"Name: {preset.get('name', '-')}",
            f"Role: {preset.get('role', '-')}",
            f"Route: {preset.get('route', '-')}",
        ]
        if preset.get("login_email"):
            details.append(f"Email: {preset['login_email']}")
        if preset.get("qr_token"):
            details.append(f"QR token: {preset['qr_token']}")
        return "\n".join(details)
