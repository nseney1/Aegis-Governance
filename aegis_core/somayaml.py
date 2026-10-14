"""Backwards-compatibility proxy for soma_core.somayaml / aegis_core.somayaml.

All core functionality has migrated to aegis_core.yaml.
"""
from __future__ import annotations

import aegis_core.yaml as _yaml_mod
from aegis_core.yaml import *  # noqa: F401, F403

# Re-export all module symbols including internal parser routines
for _name in dir(_yaml_mod):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_yaml_mod, _name)

__all__ = [name for name in dir(_yaml_mod) if not name.startswith("__")]
