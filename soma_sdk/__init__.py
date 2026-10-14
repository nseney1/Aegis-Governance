"""Backward-compatibility forwarding shim for aegis_sdk."""
from __future__ import annotations
__version__ = "2.0.0"

import importlib
import sys

_mod = importlib.import_module("aegis_sdk")
sys.modules[__name__] = _mod

for _k, _v in _mod.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v

if hasattr(_mod, "__all__"):
    __all__ = _mod.__all__


def __getattr__(name: str):
    return getattr(_mod, name)
