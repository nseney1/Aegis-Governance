"""Backward-compatibility forwarding shim for aegis_cli.cli."""
from __future__ import annotations

import importlib
import sys

_mod = importlib.import_module("aegis_cli.cli")
sys.modules[__name__] = _mod

for _k, _v in _mod.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v

if hasattr(_mod, "__all__"):
    __all__ = _mod.__all__


def _build_parser(prog: str = "soma"):
    return _mod._build_parser(prog=prog)


def __getattr__(name: str):
    return getattr(_mod, name)


if __name__ == "__main__":
    sys.exit(_mod.main())
