"""aegis doctor — workspace and environment health check.

When the aegis command is not on PATH it prints the one line to add to the
shell startup file (aegis_cli/pathcheck.py); it never edits dotfiles.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from aegis_cli.base import CommandCategory, AegisCommand

__all__ = ["run_doctor", "DoctorCommand"]



def _check_python_version() -> bool:
    """Check Python >= 3.9."""
    ok = sys.version_info >= (3, 9)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if ok:
        print(f"  ✅ Python {ver} (≥ 3.9)")
    else:
        print(f"  ❌ Python {ver} (requires ≥ 3.9)")
    return ok


def _check_zero_dependencies() -> bool:
    """Verify that the frontmatter engine is operational with zero dependencies."""
    from aegis_core.yaml import parse_frontmatter

    test_fm = "---\nid: test\ntype: wall\n---\n"
    ok = parse_frontmatter(test_fm) == {"id": "test", "type": "wall"}
    if ok:
        print("  ✅ zero-dependency runtime operational (pure standard library)")
    else:
        print("  ❌ frontmatter engine validation failed")
    return ok




def _check_platform(project_root: Path | None = None) -> str | None:
    """Detect AI platform; return platform name or None on failure."""
    from aegis_cli.init import detect_platform

    root = project_root or Path.cwd()
    platform = detect_platform(root)
    # Fallback: check home directory for global AI configs
    if platform == "unknown":
        platform = detect_platform(Path.home())
    if platform != "unknown":
        print(f"  ✅ Platform detected: {platform}")
        return platform
    print("  ❌ No AI platform detected")
    print("    Fix: Run 'aegis init' to initialize workspace governance rules.")
    return None


def _check_rules(platform: str | None, project_root: Path | None = None) -> bool:
    """Check that rules directory has ≥1 .md file."""
    if platform is None:
        print("  ❌ Rules check skipped (no platform)")
        print("    Fix: Run 'aegis init' to install starter rules.")
        return False
    from aegis_cli.init import get_rules_dir

    rules_dir = get_rules_dir(platform, project_root=project_root)
    md_files = [
        p for p in rules_dir.glob("*.md")
        if p.name.lower() not in ("readme.md", "claude.md")
    ] if rules_dir.is_dir() else []
    if md_files:
        print(f"  ✅ Rules installed ({len(md_files)} .md files in {rules_dir})")
        return True
    print(f"  ❌ No .md rules found in {rules_dir}")
    print("    Fix: Run 'aegis init' to install starter rules.")
    return False


def _check_evidence_dir(project_root: Path | None = None) -> bool:
    """Check .aegis/evidence/ exists and is writable (read-only check)."""
    base = project_root or Path.cwd()
    evidence = base / ".aegis" / "evidence"
    if evidence.is_dir():
        if os.access(str(evidence), os.W_OK):
            print(f"  ✅ Evidence directory writable ({evidence})")
            return True
        print(f"  ❌ Evidence directory not writable ({evidence})")
        print(f"    Fix: Verify write permissions on {evidence}.")
        return False
    # Directory doesn't exist — check if parent is writable
    parent = evidence.parent
    if parent.is_dir() and os.access(str(parent), os.W_OK):
        print(f"  ✅ Evidence directory can be created ({evidence})")
        return True
    print(f"  ❌ Evidence directory does not exist ({evidence})")
    print("    Fix: Run 'aegis init' to create workspace directories.")
    return False



def _check_cli_resolvable() -> bool:
    """Check that 'aegis' CLI is on PATH."""
    path = shutil.which("aegis")
    if path:
        print(f"  ✅ aegis CLI resolvable ({path})")
        return True
    print("  ❌ aegis CLI not found on PATH")
    from aegis_cli.pathcheck import build_hint, scripts_dir
    sdir = scripts_dir()
    only_soma = bool(
        sdir
        and not os.path.isfile(os.path.join(sdir, "aegis"))
        and not os.path.isfile(os.path.join(sdir, "aegis.exe"))
        and (os.path.isfile(os.path.join(sdir, "soma")) or os.path.isfile(os.path.join(sdir, "soma.exe")))
    )
    hint = build_hint(cmd_name="soma" if only_soma else "aegis")
    if hint:
        print("\n".join("    " + line for line in hint.splitlines()))
    return False


# ── MCP launcher ─────────────────────────────────────────────────────────────

# MCP configs start the server as `python3 -m aegis_mcp`. The import probe runs
# without -I so user site-packages count, but drops the implicit CWD entry so
# doctor never imports (executes) a aegis_mcp that happens to sit in the cwd.
_IMPORT_PROBE = "import sys; sys.path[:1] = [p for p in sys.path[:1] if p]; __import__('aegis_mcp')"


def probe_mcp_launcher(path_env: str | None = None,
                       timeout: float = 10.0) -> tuple[str, str]:
    """Resolve `python3` from PATH like an MCP host and classify it.

    Returns (status, detail); status is one of ok, missing, store_stub,
    broken, no_soma_mcp.
    """
    path_env = os.environ.get("PATH", "") if path_env is None else path_env
    exe = shutil.which("python3", path=path_env)
    if not exe:
        return "missing", "python3 is not on PATH"

    def _run(argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run([exe, *argv], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, errors="replace",
                              timeout=timeout)

    try:
        proc = _run(["-I", "-S", "-c", "import sys; print(sys.version_info[0])"])
    except subprocess.TimeoutExpired:
        return "broken", f"{exe} timed out after {timeout:g}s"
    except OSError as exc:
        return "broken", f"{exe} could not be started: {exc}"
    out = proc.stdout.strip()
    # The App Installer stub exits 49, or prints a Store message and nothing
    # on stdout, instead of running Python.
    store_msg = "microsoft store" in (proc.stdout + proc.stderr).lower()
    if proc.returncode == 49 or (not out and store_msg):
        return "store_stub", exe
    if proc.returncode != 0 or out != "3":
        err = (proc.stderr.strip() or out)[:200]
        return "broken", f"{exe} exited {proc.returncode}: {err}"

    try:
        imp = _run(["-c", _IMPORT_PROBE])
    except subprocess.TimeoutExpired:
        return "broken", f"{exe} timed out after {timeout:g}s importing aegis_mcp"
    except OSError as exc:
        return "broken", f"{exe} could not be started: {exc}"
    if imp.returncode != 0:
        return "no_soma_mcp", exe
    return "ok", exe


def _check_mcp_launcher(path_env: str | None = None) -> bool:
    """Advisory: report whether `python3 -m aegis_mcp` would start."""
    status, detail = probe_mcp_launcher(path_env)
    if status == "ok":
        print(f"  ✅ MCP launcher: python3 ({detail}) runs and imports aegis_mcp")
        return True
    if status == "missing":
        print("  ⚠️  MCP launcher: python3 not found on PATH. MCP configs start the\n"
              "      server with `python3 -m aegis_mcp`; install Python 3 from python.org\n"
              "      or put it on PATH (only needed if you use the MCP server).")
    elif status == "store_stub":
        print(f"  ⚠️  MCP launcher: {detail} is the Windows Store App Installer stub, not Python.\n"
              "      Fix: Settings > Apps > Advanced app settings > App execution aliases:\n"
              "      turn off python.exe and python3.exe, then install Python from python.org\n"
              "      (or make sure the real python3 comes first on PATH).")
    elif status == "no_soma_mcp":
        print(f"  ⚠️  MCP launcher: {detail} runs but cannot import aegis_mcp.\n"
              f"      Install it for that interpreter: {detail} -m pip install --user aegis-guardrails")
    else:
        print(f"  ⚠️  MCP launcher: {detail}")
    return False


def _check_ast_drivers(project_root: Path | None = None, fix: bool = False) -> bool:
    """Check configured AST drivers in .aegis/slots.yaml and verify their binaries."""
    import shlex
    from aegis_core.skills.slots import SlotRegistry
    from aegis_core.ast.detect import detect_project_languages, provision_ast_driver_slots
    from aegis_core.ast.runner import resolve_driver_executable

    ws_root = Path(project_root or Path.cwd())
    slots_path = ws_root / ".aegis" / "slots.yaml"

    detected_langs = detect_project_languages(ws_root)
    non_py_langs = {k: v for k, v in detected_langs.items() if k != "python"}

    if not slots_path.is_file():
        if non_py_langs:
            if fix:
                new_slots, created = provision_ast_driver_slots(ws_root, detected_langs, copy_drivers=True)
                if created:
                    print(f"  ✅ Fixed: Auto-provisioned AST drivers in .aegis/slots.yaml for {', '.join(k.title() for k in sorted(non_py_langs))}")
            else:
                missing_exts = sorted(set().union(*(d.get("extensions", []) for d in non_py_langs.values())))
                ext_str = ", ".join(missing_exts) if missing_exts else ", ".join(non_py_langs.keys())
                print(f"  ⚠️  AST drivers: unconfigured driver for detected source language(s): {ext_str}. Run 'aegis doctor --fix' to provision.")
                return False
        if not slots_path.is_file():
            print("  ✅ AST drivers: native Python stdlib (in-process)")
            return True

    try:
        registry = SlotRegistry.load(ws_root)
    except Exception as exc:
        print(f"  ❌ AST drivers: failed to load slots.yaml: {exc}")
        return False

    ast_drivers: dict[str, str] = {}
    for slot_name, slot_val in registry.to_dict().items():
        if slot_name == "ast_driver":
            ast_drivers["default"] = str(slot_val)
        elif slot_name.startswith("ast_driver_"):
            ext = slot_name[len("ast_driver_"):]
            ast_drivers[f".{ext}"] = str(slot_val)

    missing: list[str] = []
    for lang, l_info in non_py_langs.items():
        for ext in l_info.get("extensions", []):
            if ext not in ast_drivers and "default" not in ast_drivers:
                missing.append(ext)

    if missing:
        if fix:
            new_slots, created = provision_ast_driver_slots(ws_root, detected_langs, copy_drivers=True)
            if created:
                print(f"  ✅ Fixed: Auto-provisioned missing AST driver slots in .aegis/slots.yaml: {', '.join(missing)}")
                registry = SlotRegistry.load(ws_root)
                for slot_name, slot_val in registry.to_dict().items():
                    if slot_name.startswith("ast_driver_"):
                        ext = slot_name[len("ast_driver_"):]
                        ast_drivers[f".{ext}"] = str(slot_val)
        else:
            print(f"  ⚠️  AST drivers: unconfigured driver for detected source extension(s): {', '.join(missing)}. Run 'aegis doctor --fix' to provision.")
            return False


    if not ast_drivers:
        print("  ✅ AST drivers: native Python stdlib (in-process)")
        return True

    all_resolvable = True
    for ext, cmd in sorted(ast_drivers.items()):
        parts = (
            shlex.split(cmd)
            if os.name != "nt"
            else [p.strip('"') for p in shlex.split(cmd, posix=False)]
        )
        if not parts:
            continue
        bin_name = parts[0]
        found = resolve_driver_executable(bin_name)
        if found:
            print(f"  ✅ AST driver ({ext}): {bin_name} resolvable ({found})")
        else:
            print(f"  ⚠️  AST driver ({ext}): executable '{bin_name}' not found on PATH")
            all_resolvable = False

    return all_resolvable


# ── Pre-commit hook ──────────────────────────────────────────────────────────

def _check_precommit_hook(project_root: Path | None = None) -> bool | None:
    """True for a current hook block, False for an older one, None if absent.

    Blocks before the current format resolved aegis through PATH, $VIRTUAL_ENV
    or the repository's .venv, so repository code could run on commit.
    """
    from aegis_cli.hooks.management import hook_status

    st = hook_status(project_root)
    if not st["managed_by_aegis"]:
        return None
    if st["status"] == "installed":
        print(f"  ✅ Pre-commit hook is current ({st['hook_file']})")
        return True
    print(f"  ❌ Pre-commit hook uses an old block (format {st['format_version']}, {st['hook_file']}).\n"
          "      It can run an aegis found on PATH or in the repository instead of\n"
          "      the one you installed. Re-run `aegis hook install` to refresh it.")
    return False


def run_doctor(args: argparse.Namespace) -> int:
    """Run all health checks. Returns 0 if all pass, 1 otherwise."""
    import contextlib
    import io
    from aegis_cli.ui.theme import strip_ansi
    from aegis_core.workspace import Workspace

    ws_obj = getattr(args, "ws", None) or Workspace.resolve(
        getattr(args, "workspace", None) or getattr(args, "_project_root", None)
    )
    ws = ws_obj.root
    use_json = bool(getattr(args, "json", False) or getattr(args, "format", None) == "json")

    if getattr(args, "drivers", False):
        if not use_json:
            print(f"aegis doctor — AST driver health check ({ws}):\n")
        fix = getattr(args, "fix", False)
        ok = _check_ast_drivers(ws, fix=fix)
        return 0 if ok else 1

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf) if use_json else contextlib.nullcontext():
        if not use_json:
            print(f"aegis doctor — running health checks ({ws}):\n")
        results: list[bool] = []

        results.append(_check_python_version())
        results.append(_check_zero_dependencies())
        platform = _check_platform(ws)
        results.append(platform is not None)
        results.append(_check_rules(platform, ws))
        results.append(_check_evidence_dir(ws))
        results.append(_check_cli_resolvable())
        hook_ok = _check_precommit_hook(ws)
        if hook_ok is not None:
            results.append(hook_ok)
        fix = getattr(args, "fix", False)
        # Advisory: report configured AST drivers (polyglot drivers are optional)
        ast_ok = _check_ast_drivers(ws, fix=fix)
        # Advisory: only MCP users need it, so it does not fail the run.
        mcp_ok = _check_mcp_launcher()

    passed = sum(results)
    total = len(results)
    failed = total - passed
    warnings = (0 if ast_ok else 1) + (0 if mcp_ok else 1)

    if use_json:
        payload = {
            "workspace": str(ws),
            "passed": passed,
            "warnings": warnings,
            "failed": failed,
            "total": total,
            "ok": failed == 0,
            "details": [
                strip_ansi(line.strip())
                for line in buf.getvalue().splitlines()
                if line.strip()
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0 if all(results) else 1

    warn_label = "warning" if warnings == 1 else "warnings"
    print(f"\n{passed}/{total} checks passed ({passed} passed, {warnings} {warn_label}, {failed} failed).")
    return 0 if all(results) else 1



class DoctorCommand(AegisCommand):
    """Command for system health and governance audit."""

    name = "doctor"
    category = CommandCategory.SETUP
    help = "System health and governance audit"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Automatically repair detected issues (pre-commit hooks, missing AST drivers)",
        )
        parser.add_argument(
            "--drivers",
            action="store_true",
            help="Run only AST driver and language detection health check",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_doctor(args)
