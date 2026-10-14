"""Compatibility aliases connecting legacy soma_* imports to canonical aegis_* packages."""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from typing import Any

_SOMA_PACKAGES = ("soma_core", "soma_cli", "soma_sdk", "soma_mcp")


class _SomaAliasLoader(importlib.abc.Loader):
    """Loader that delegates module creation to canonical aegis_* packages."""

    def __init__(self, target_name: str, target_spec: Any = None) -> None:
        self.target_name = target_name
        self.target_spec = target_spec

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> Any:
        mod = importlib.import_module(self.target_name)
        sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module: Any) -> None:
        if self.target_spec is not None:
            # Restore the canonical target module's original spec so package resources
            # for aegis_* remain completely undisturbed
            module.__spec__ = self.target_spec


_RELOCATED_MODULES = {
    "aegis_core.verification_jobs": "aegis_core.verification.jobs",
    "aegis_core.arbitration": "aegis_core.proposals",
}


class _SomaAliasFinder(importlib.abc.MetaPathFinder):
    """MetaPathFinder that intercepts soma_* imports and routes to aegis_*."""

    def find_spec(
        self,
        fullname: str,
        path: list[str] | None,
        target: Any | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname in _RELOCATED_MODULES:
            target_name = _RELOCATED_MODULES[fullname]
            try:
                import importlib.util
                target_spec = importlib.util.find_spec(target_name)
            except Exception:
                target_spec = None
            loader = _SomaAliasLoader(target_name, target_spec)
            return importlib.machinery.ModuleSpec(fullname, loader, is_package=False)

        for pkg in _SOMA_PACKAGES:
            if fullname == pkg or fullname.startswith(pkg + "."):
                if fullname.endswith(".__main__"):
                    return None
                target_name = "aegis_" + fullname[5:]
                target_name = _RELOCATED_MODULES.get(target_name, target_name)
                try:
                    import importlib.util
                    target_spec = importlib.util.find_spec(target_name)
                except Exception:
                    target_spec = None
                loader = _SomaAliasLoader(target_name, target_spec)
                is_pkg = "." not in fullname
                spec = importlib.machinery.ModuleSpec(fullname, loader, is_package=is_pkg)
                if target_spec and target_spec.submodule_search_locations:
                    spec.submodule_search_locations = list(target_spec.submodule_search_locations)
                    spec.origin = target_spec.origin
                return spec
        return None


_INSTALLED = False


def install_compat_aliases() -> None:
    """Install MetaPathFinder intercepting soma_* and routing to aegis_*."""
    global _INSTALLED
    if not _INSTALLED:
        for finder in sys.meta_path:
            if isinstance(finder, _SomaAliasFinder):
                _INSTALLED = True
                return
        sys.meta_path.insert(0, _SomaAliasFinder())
        _INSTALLED = True


# Auto-install on module import
install_compat_aliases()

__all__ = ["install_compat_aliases"]
