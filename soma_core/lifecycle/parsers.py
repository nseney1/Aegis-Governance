"""Backward-compatibility forwarding shim for aegis_core.lifecycle.parsers."""
from __future__ import annotations

import importlib
import sys

_mod = importlib.import_module("aegis_core.lifecycle.parsers")
sys.modules[__name__] = _mod

for _k, _v in _mod.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v

if hasattr(_mod, "__all__"):
    __all__ = _mod.__all__


def __getattr__(name: str):
    return getattr(_mod, name)
