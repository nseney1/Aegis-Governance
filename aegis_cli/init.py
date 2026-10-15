"""soma init — Set up governance for this project.

Detects platform and project type, installs starter rules.
"""
from __future__ import annotations

import argparse
import importlib.resources
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from aegis_cli.base import CommandCategory, AegisCommand

__all__ = ["run_init", "InitCommand"]

# ── Starter Pack ────────────────────────────────────────────────────────────
# The 5 rules that deliver immediate value on any project, any language.
# Keys are the rule stems — files are bundled in aegis_cli/starter_rules/.

STARTER_RULES = [
    "providence",
    "destructive-ops",
    "testing",
    "cost-optimization",
    "git-workflow",
]

MINIMAL_RULES = ["providence", "destructive-ops"]


def _get_starter_rule_path(name: str) -> Path | None:
    """Resolve the path to a bundled starter rule file.

    Uses importlib.resources to find files inside the aegis_cli package,
    falling back to direct filesystem resolution relative to this file.
    """
    try:
        ref = importlib.resources.files("aegis_cli") / "starter_rules" / f"{name}.md"
        path = Path(str(ref))
        if path.is_file():
            return path
    except (TypeError, FileNotFoundError, AttributeError):
        pass

    fallback = Path(__file__).resolve().parent / "starter_rules" / f"{name}.md"
    if fallback.is_file():
        return fallback

    return None


# ── Detection & Platform Rules Directory (Delegated to aegis_cli.platforms) ──

from aegis_cli.platforms import detect_platform, get_rules_dir


def detect_project_type(project_root: Path) -> str:
    """Detect the project type from config files.

    Returns: 'python' | 'javascript' | 'rust' | 'go' | 'dotnet' | 'unknown'
    """
    project_root = Path(project_root)
    checks = [
        (["pyproject.toml", "setup.py", "setup.cfg"], "python"),
        (["package.json"], "javascript"),
        (["Cargo.toml"], "rust"),
        (["go.mod"], "go"),
    ]
    for files, lang in checks:
        for f in files:
            if (project_root / f).exists():
                return lang
    return "unknown"


# ── Pre-commit Hook (Delegated to aegis_cli.hooks) ───────────────────────────

from aegis_cli.hooks import (
    _AEGIS_HOOK_END,
    _AEGIS_HOOK_START,
    _SOMA_HOOK_END,
    _SOMA_HOOK_START,
    AEGIS_HOOK_FORMAT,
    SOMA_HOOK_FORMAT,
    _replace_hook_block,
    generate_hook_block,
    install_hook,
)
_hook_block = generate_hook_block


# ── Installation ────────────────────────────────────────────────────────────

def check_existing_install(project_root: Path) -> bool:
    """Check if Aegis is already installed in this project."""
    return (Path(project_root) / ".aegis").is_dir()


def _get_soma_root() -> Path:
    """Find the Soma source root (repo root with genome/ dir).

    Tries importlib.resources (works for editable installs) then falls
    back to CWD.
    """
    try:
        pkg_root = Path(str(importlib.resources.files("aegis_cli"))).parent
        if (pkg_root / "rules").is_dir():
            return pkg_root
        if (pkg_root / "genome").is_dir():
            return pkg_root
    except (TypeError, FileNotFoundError):
        pass
    return Path.cwd()


def _discover_full_rules() -> list[Path]:
    """Discover all canonical rule .md files for the full preset.

    Scans rules/ (or genome/) and .oracles/, skipping META.md and README.md.
    """
    soma_root = _get_soma_root()
    rules_dir = (soma_root / "rules") if (soma_root / "rules").is_dir() else (soma_root / "genome")
    if not rules_dir.is_dir():
        return []

    skip = {"META.md", "README.md"}
    results: list[Path] = []

    # Top-level rules/*.md
    for f in sorted(rules_dir.glob("*.md")):
        if f.is_file() and f.name not in skip:
            results.append(f)

    # .oracles/*.md
    oracles_dir = rules_dir / ".oracles"
    if oracles_dir.is_dir():
        for f in sorted(oracles_dir.glob("*.md")):
            if f.is_file() and f.name not in skip:
                results.append(f)

    return results


def install_rules(
    rules_dir: Path,
    preset: str = "standard",
    dry_run: bool = False,
    force: bool = False,
) -> list[str]:
    """Install rules to the target directory based on the chosen preset.

    Args:
        rules_dir: Target directory for rules.
        preset: One of 'minimal', 'standard', 'full'.
        dry_run: If True, only print what would be done.
        force: If True, overwrite existing rules.

    Returns:
        List of installed rule names.
    """
    if preset == "full":
        sources = _discover_full_rules()
        return _copy_rule_files(rules_dir, sources, force=force, dry_run=dry_run)
    elif preset == "minimal":
        names = MINIMAL_RULES
    else:  # standard
        names = STARTER_RULES

    return _install_named_rules(rules_dir, names, force=force, dry_run=dry_run)


def _install_named_rules(
    rules_dir: Path,
    names: list[str],
    force: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Install named rules from the starter_rules bundle."""
    installed = []
    for name in names:
        source = _get_starter_rule_path(name)
        if source is None:
            print(f"  ⚠️  {name}: source not found")
            continue

        dest = rules_dir / f"{name}.md"
        if dest.is_symlink():
            print(f"  ⚠️  {name}: skipped (destination is a symlink)")
            continue
        if dest.exists() and not force:
            print(f"  ℹ️  {name}: already exists, skipping (use --force to overwrite)")
            installed.append(name)
            continue

        if not dry_run:
            rules_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        installed.append(name)

    return installed


def _copy_rule_files(
    rules_dir: Path,
    sources: list[Path],
    force: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Copy a list of source .md files into rules_dir."""
    installed = []
    for src in sources:
        dest = rules_dir / src.name
        if dest.is_symlink():
            print(f"  ⚠️  {src.name}: skipped (destination is a symlink)")
            continue
        if dest.exists() and not force:
            print(f"  ℹ️  {src.stem}: already exists, skipping (use --force to overwrite)")
            installed.append(src.stem)
            continue

        if not dry_run:
            rules_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        installed.append(src.stem)

    return installed


def install_starter_rules(
    rules_dir: Path,
    dry_run: bool = False,
    force: bool = False,
) -> list[str]:
    """Install the 5 starter rules to the target directory.

    Backward-compatible wrapper around install_rules().

    Args:
        rules_dir: Target directory for rules.
        dry_run: If True, don't create files.
        force: If True, overwrite existing rules.

    Returns:
        List of installed rule names.
    """
    return _install_named_rules(rules_dir, STARTER_RULES, force=force, dry_run=dry_run)


# ── MCP Config ──────────────────────────────────────────────────────────────

def generate_mcp_config(project_root: Path, dry_run: bool = False) -> None:
    """Create or merge .mcp.json for the governed project.

    Existing servers and unrelated keys are preserved. Invalid or structurally
    incompatible JSON fails before the configuration is modified.
    """
    workspace = str(Path(project_root).resolve())
    mcp_file = Path(workspace) / ".mcp.json"

    soma_entry = {
        "command": "python3",
        "args": ["-m", "aegis_mcp"],
        "cwd": workspace,
        "env": {"AEGIS_WORKSPACE": workspace},
    }

    if dry_run:
        print(f"  Would create/update: {mcp_file}")
        return

    if mcp_file.exists():
        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{mcp_file} must contain a JSON object")
    else:
        data = {}

    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
        data["mcpServers"] = servers
    elif not isinstance(servers, dict):
        raise ValueError(f"{mcp_file} field 'mcpServers' must be a JSON object")
    servers["soma"] = soma_entry

    mode = None
    if mcp_file.exists():
        try:
            mode = os.stat(mcp_file).st_mode
        except OSError:
            pass

    # Write beside the destination with unique pid temp name and replace only after
    # serialization succeeds, preserving original file mode.
    temp_file = mcp_file.with_name(f".{mcp_file.name}.{os.getpid()}.tmp")
    try:
        temp_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        if mode is not None:
            try:
                os.chmod(temp_file, mode)
            except OSError:
                pass
        temp_file.replace(mcp_file)
    finally:
        if temp_file.exists():
            temp_file.unlink()
    print(f"  📡 MCP config written to {mcp_file}")


# ── Main flow ───────────────────────────────────────────────────────────────

def run_init(args: argparse.Namespace) -> int:
    """Main init flow. Returns exit code."""
    from aegis_core.workspace import Workspace

    # Allow test override of project root
    ws = getattr(args, "ws", None) or Workspace.for_init(
        getattr(args, "workspace", None) or getattr(args, "_project_root", None) or Path.cwd()
    )
    project_root = ws.root

    dry_run = args.dry_run
    forced_platform = args.platform

    print()
    print("  🛡️ Aegis Guardrails — Workspace Setup")
    print()

    # 1. Detect platform
    if forced_platform:
        platform = forced_platform
        print(f"  Platform: {platform} (forced)")
    else:
        platform = detect_platform(project_root)
        # Fallback: check home directory if project-level detection fails
        if platform == "unknown" and (
            not getattr(args, "_project_root", None)
            or getattr(args, "_allow_home_fallback", False)
        ):
            home_dir = Path(getattr(args, "_home", getattr(args, "_home_override", None)) or Path.home())
            platform = detect_platform(home_dir)
        if platform == "unknown":
            print("  ⚠️  Could not detect platform.")
            print("     Use --platform to specify: gemini, claude, cursor, copilot, kiro")
            return 1
        print(f"  Detected platform: {platform}")

    # 2. Detect project languages & type
    from aegis_core.ast.detect import detect_project_languages, provision_ast_driver_slots

    detected_langs = detect_project_languages(project_root)
    if detected_langs:
        lang_str = ", ".join(k.title() for k in sorted(detected_langs))
        print(f"  Detected language(s): {lang_str}")
    else:
        print("  Project type: unknown (rules are language-agnostic)")

    # 3. Check existing install
    if check_existing_install(project_root):
        print()
        print("  ℹ️  Existing Aegis installation detected.")
        print("     Starter rules will be added alongside existing rules.")

    print()

    # 4. Resolve target directory
    try:
        home = getattr(args, "_home", getattr(args, "_home_override", None))
        local = getattr(args, "local", False)
        rules_dir = get_rules_dir(platform, home=home, project_root=project_root, local=local)
    except ValueError as e:
        print(f"  ❌ {e}")
        return 1

    # 5. Confirmation prompt (unless --yes or --dry-run)
    skip_confirm = getattr(args, "yes", False) or dry_run
    global_rules_exist = rules_dir.is_dir() and any(rules_dir.glob("*.md"))
    if global_rules_exist and not getattr(args, "force", False):
        print(f"  ℹ️  Global platform rules detected in {rules_dir}. Attaching Aegis to local repository.")
        skip_confirm = True

    if not skip_confirm:
        print(f"  Will install starter rules to: {rules_dir}")
        try:
            answer = input("  Proceed? [Y/n] ").strip().lower()
            if answer and answer not in ("y", "yes"):
                print("  Aborted.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            return 0
    print()

    # 6. Install rules based on preset
    preset = getattr(args, "rules", "standard")
    force = getattr(args, 'force', False)

    if dry_run:
        print(f"  Installing rules (preset={preset}, dry run)...")
    else:
        print(f"  Installing rules (preset={preset})...")

    pre_existing = {p.stem for p in rules_dir.glob("*.md")} if rules_dir.is_dir() else set()
    ws.scaffold(minimal=(preset == "minimal"), dry_run=dry_run)
    installed = install_rules(rules_dir, preset=preset, dry_run=dry_run, force=force)

    for name in installed:
        if dry_run:
            print(f"    [DRY-RUN] {name}")
        elif name in pre_existing and not force:
            print(f"    [SKIP] {name}")
        else:
            print(f"    ✅ {name}")

    # 6.5. Zero-touch AST driver provisioning
    slots, created_drivers = provision_ast_driver_slots(
        project_root, detected_langs, copy_drivers=not dry_run, dry_run=dry_run
    )
    if slots:
        action = "Would configure" if dry_run else "Configured"
        for slot_k, slot_cmd in sorted(slots.items()):
            if slot_k.startswith("ast_driver_"):
                ext = slot_k[len("ast_driver_"):]
                print(f"    ✨ {action} AST driver (.{ext}): {slot_cmd}")

    print()

    # 7. MCP config (if requested)
    if getattr(args, "mcp", False):
        generate_mcp_config(project_root, dry_run=dry_run)

    # 7.5. Install pre-commit hook
    no_hooks = getattr(args, "no_hooks", False) or not getattr(args, "hooks", True)
    if not no_hooks:
        hook_result = install_hook(project_root, dry_run=dry_run)
        if hook_result and not dry_run:
            print("    🪝 Pre-commit hook installed (.git/hooks/pre-commit)")
        elif hook_result and dry_run:
            print("    🪝 Would install pre-commit hook")

    # 8. Claude-specific: concatenate rules into CLAUDE.md
    if platform == "claude" and installed and not dry_run:
        target_md = (project_root / "CLAUDE.md") if local else (rules_dir / "CLAUDE.md")
        _install_claude_md(rules_dir, force=force, claude_md=target_md)

    if dry_run:
        print("  Dry run complete. No files were created.")
        print(f"  Target: {rules_dir}")
    elif not installed:
        print("  ❌ No rules were installed. Check that Aegis source files exist.")
        return 1
    else:
        print("  Done! Your next agent session will be governed.")
        print(f"  Rules installed to: {rules_dir}")

    print()
    print("  After a session, run: aegis report")
    print()


    # Proactive PATH guidance (Phase 15 / BUG-041)
    if not dry_run:
        try:
            from aegis_cli.pathcheck import build_hint

            try:
                hint = build_hint(cmd_name="aegis")
            except TypeError:
                hint = build_hint()
            if hint:
                print(hint)
                print()
        except (OSError, RuntimeError):
            pass

    return 0


# ── Claude helpers ──────────────────────────────────────────────────────────

SOMA_MARKER_START = "<!-- SOMA:START -->"
SOMA_MARKER_END = "<!-- SOMA:END -->"


def _install_claude_md(
    rules_dir: Path,
    force: bool = False,
    claude_md: Path | None = None,
) -> None:
    """Concatenate installed rules into CLAUDE.md for Claude Code.

    Claude Code reads CLAUDE.md, not individual .md files. We concatenate
    all installed rules between SOMA markers so we can update them later.
    """
    if claude_md is None:
        claude_md = rules_dir / "CLAUDE.md"  # ~/.claude/CLAUDE.md

    # Build the soma governance section
    sections = []
    for rule_file in sorted(rules_dir.glob("*.md")):
        if rule_file.is_file() and rule_file.name != "CLAUDE.md":
            content = rule_file.read_text(encoding="utf-8").strip()
            sections.append(f"## {rule_file.stem}\n\n{content}")

    if not sections:
        return

    soma_block = (
        f"{SOMA_MARKER_START}\n"
        f"# Soma Governance Rules\n\n"
        + "\n\n---\n\n".join(sections)
        + f"\n{SOMA_MARKER_END}\n"
    )

    if claude_md.exists():
        existing = claude_md.read_text(encoding="utf-8")
        has_start = SOMA_MARKER_START in existing
        has_end = SOMA_MARKER_END in existing

        if has_start and has_end:
            start_idx = existing.index(SOMA_MARKER_START)
            end_idx = existing.index(SOMA_MARKER_END) + len(SOMA_MARKER_END)
            # Guard against inverted markers
            if start_idx >= end_idx:
                print("  ⚠️  CLAUDE.md has corrupted SOMA markers, skipping")
                return
            if not force:
                print("  ℹ️  CLAUDE.md already has Soma rules (use --force to update)")
                return
            # Replace existing section
            updated = existing[:start_idx] + soma_block + existing[end_idx:]
            claude_md.write_text(updated, encoding="utf-8")
        elif has_start or has_end:
            # Partial markers — refuse without --force to avoid corruption
            if not force:
                print("  ⚠️  CLAUDE.md has partial SOMA markers (use --force to replace)")
                return
            # Force: remove the orphan marker line and append fresh block
            lines = existing.splitlines(True)
            lines = [l for l in lines if SOMA_MARKER_START not in l and SOMA_MARKER_END not in l]
            claude_md.write_text("".join(lines).rstrip() + "\n\n" + soma_block, encoding="utf-8")
        else:
            # No markers — append
            claude_md.write_text(existing.rstrip() + "\n\n" + soma_block, encoding="utf-8")
    else:
        claude_md.write_text(soma_block, encoding="utf-8")

    print(f"  📝 Updated {claude_md}")


class InitCommand(AegisCommand):
    """Command to initialize governance for a project."""

    name = "init"
    category = CommandCategory.SETUP
    help = "Set up governance for this project"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be installed without doing it",
        )
        parser.add_argument(
            "--platform",
            choices=["gemini", "claude", "cursor", "copilot", "kiro"],
            help="Skip platform detection, force a platform",
        )
        parser.add_argument(
            "--local",
            action="store_true",
            help="Install rules to project-local directory instead of user home",
        )
        parser.add_argument(
            "--rules",
            choices=["minimal", "standard", "full"],
            default="standard",
            help="Rule set to install (default: standard)",
        )
        parser.add_argument(
            "--mcp",
            action="store_true",
            help="Generate .mcp.json for JIT cell matching",
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip confirmation prompts",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing rules",
        )
        parser.add_argument(
            "--no-hooks",
            action="store_true",
            help="Skip installing git pre-commit hook",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_init(args)
