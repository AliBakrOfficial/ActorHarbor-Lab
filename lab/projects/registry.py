from __future__ import annotations

from .ncs_adapter import NCSProjectAdapter


_ADAPTERS = {
    "ncs": NCSProjectAdapter(),
}


def get_adapter(project_id: str):
    return _ADAPTERS[project_id]


def list_adapters():
    return list(_ADAPTERS.values())
