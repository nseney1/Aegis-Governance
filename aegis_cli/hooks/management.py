"""Git hook lifecycle management: install, uninstall, status inspection, and block generation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Any

_AEGIS_HOOK_START = "# >>> aegis pre-commit >>>"
_AEGIS_HOOK_END = "# <<< aegis pre-commit <<<"
_SOMA_HOOK_START = "# >>> soma pre-commit >>>"
_SOMA_HOOK_END = "# <<< soma pre-commit <<<"
AEGIS_HOOK_FORMAT = "# aegis-hook-format:"
SOMA_HOOK_FORMAT = "# soma-hook-format:"
CURRENT_HOOK_FORMAT_VERSION = 5


# The hook runs this code with the pinned interpreter. -I keeps the working
# tree (and PYTHON* variables) off sys.path, so a repository cannot substitute
# its own aegis_cli; AEGIS_PATH is the directory aegis_cli was installed in.
_HOOK_RUNNER = "import sys; sys.path.insert(0, sys.argv[1]); from aegis_cli.cli import main; sys.exit(main(sys.argv[2:]))"


def _default_import_root() -> str:
    import aegis_cli

    return str(Path(aegis_cli.__file__).resolve().parent.parent)


def _sh_path(path: str) -> str:
    return path.replace("\\", "/") if os.name == "nt" else path


def generate_hook_block(python: str | None = None, import_root: str | None = None) -> str:
    """The marked pre-commit block: run the aegis that installed it, or fail closed.

    One absolute interpreter (default: sys.executable of the installing aegis)
    and the directory aegis_cli was imported from are baked in at install
    time. Nothing is looked up on PATH, in $VIRTUAL_ENV or in the repository.
    """
    python = python if python is not None else sys.executable
    import_root = import_root if import_root is not None else _default_import_root()
    # A relative path would resolve against the repository the hook runs in.
    if not os.path.isabs(python):
        raise ValueError(f"hook interpreter must be an absolute path, got {python!r}")
    if not os.path.isabs(import_root):
        raise ValueError(f"aegis import root must be an absolute path, got {import_root!r}")
    py = shlex.quote(_sh_path(python))
    root = shlex.quote(_sh_path(import_root))
    runner = shlex.quote(_HOOK_RUNNER)
    return (
        f"{_AEGIS_HOOK_START}\n"
        "# Installed by aegis hook install\n"
        f"{AEGIS_HOOK_FORMAT} {CURRENT_HOOK_FORMAT_VERSION}\n"
        f"AEGIS_PYTHON={py}\n"
        f"AEGIS_PATH={root}\n"
        'if [ -x "$AEGIS_PYTHON" ] && [ -f "$AEGIS_PATH/aegis_cli/__init__.py" ]; then\n'
        f'  exec "$AEGIS_PYTHON" -I -c {runner} "$AEGIS_PATH" check --hook\n'
        "fi\n"
        'echo "aegis pre-commit: aegis not found at $AEGIS_PYTHON; run aegis hook install, or commit with --no-verify" >&2\n'
        "exit 1\n"
        f"{_AEGIS_HOOK_END}\n"
    )


def _replace_hook_block(content: str, block: str) -> str | None:
    """content with its marked block swapped for block, or None if malformed."""
    for start_m, end_m in (
        (_AEGIS_HOOK_START, _AEGIS_HOOK_END),
        (_SOMA_HOOK_START, _SOMA_HOOK_END),
    ):
        start = content.find(start_m)
        if start >= 0:
            end = content.find(end_m, start)
            if end < 0:
                return None
            line_start = content.rfind("\n", 0, start) + 1
            end += len(end_m)
            if content.startswith("\r\n", end):
                end += 2
            elif content.startswith("\n", end):
                end += 1
            return content[:line_start] + block + content[end:]
    return None


def install_hook(
    project_root: str | Path | Any | None = None,
    force: bool = False,
    python: str | None = None,
    dry_run: bool = False,
    import_root: str | None = None,
) -> bool:
    """Install or refresh the aegis pre-commit hook in a git repository."""
    from aegis_core.workspace.base import Workspace
    from aegis_core.workspace.hooks import resolve_git_hooks_dir

    if isinstance(project_root, Workspace):
        ws = project_root
        root = ws.root
        git_hooks_dir = ws.git_hooks_dir
    else:
        root = Path(project_root or Path.cwd()).resolve()
        git_hooks_dir = resolve_git_hooks_dir(root)

    if not git_hooks_dir:
        return False

    block = generate_hook_block(python, import_root=import_root)
    if dry_run:
        return True

    git_hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = git_hooks_dir / "pre-commit"

    target_file = hook_file
    if hook_file.is_symlink():
        real_target = hook_file.resolve()
        if not real_target.exists():
            if not force:
                print(
                    f"Error: {hook_file} is a dangling symlink. Use --force to replace.",
                    file=sys.stderr,
                )
                return False
            hook_file.unlink()
            target_file = hook_file
        else:
            is_contained = False
            for boundary in (root, git_hooks_dir):
                if boundary:
                    try:
                        real_target.relative_to(boundary.resolve())
                        is_contained = True
                        break
                    except ValueError:
                        pass
            if not is_contained and not force:
                print(
                    f"Error: {hook_file} is a symlink pointing outside repository ({real_target}). Use --force to overwrite.",
                    file=sys.stderr,
                )
                return False
            target_file = real_target

    if target_file.exists():
        content = target_file.read_text(encoding="utf-8")
        if _AEGIS_HOOK_START in content or _SOMA_HOOK_START in content:
            updated = _replace_hook_block(content, block)
            if updated is None:
                print(f"  ⚠️  {target_file} has an unterminated hook block; left unchanged", file=sys.stderr)
                return True
            new_content = updated
        else:
            if not content.endswith("\n"):
                content += "\n"
            new_content = content + "\n" + block
    else:
        new_content = "#!/bin/sh\n\n" + block

    new_content = new_content.replace("\r\n", "\n")

    tmp_file = target_file.parent / f".pre-commit.tmp.{os.getpid()}"
    try:
        tmp_file.write_bytes(new_content.encode("utf-8"))
        if os.name != "nt":
            tmp_file.chmod(0o755)
        tmp_file.replace(target_file)
    finally:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass

    if os.name != "nt" and target_file.exists():
        try:
            target_file.chmod(target_file.stat().st_mode | 0o755)
        except OSError:
            pass

    return True


def uninstall_hook(
    project_root: str | Path | Any | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    """Remove the aegis block from the pre-commit hook, keeping user hook lines."""
    from aegis_core.workspace.base import Workspace
    from aegis_core.workspace.hooks import resolve_git_hooks_dir

    if isinstance(project_root, Workspace):
        ws = project_root
        root = ws.root
        git_hooks_dir = ws.git_hooks_dir
    else:
        root = Path(project_root or Path.cwd()).resolve()
        git_hooks_dir = resolve_git_hooks_dir(root)

    if not git_hooks_dir:
        return False

    hook_file = git_hooks_dir / "pre-commit"
    if not hook_file.exists() and not hook_file.is_symlink():
        return False

    target_file = hook_file
    if hook_file.is_symlink():
        real_target = hook_file.resolve()
        if not real_target.exists():
            if force:
                if not dry_run:
                    hook_file.unlink()
                return True
            return False
        else:
            is_contained = False
            for boundary in (root, git_hooks_dir):
                if boundary:
                    try:
                        real_target.relative_to(boundary.resolve())
                        is_contained = True
                        break
                    except ValueError:
                        pass
            if not is_contained and not force:
                print(
                    f"Error: {hook_file} is a symlink pointing outside repository ({real_target}). Use --force to uninstall.",
                    file=sys.stderr,
                )
                return False
            target_file = real_target

    content = target_file.read_text(encoding="utf-8")
    if _AEGIS_HOOK_START not in content and _SOMA_HOOK_START not in content:
        return False

    if dry_run:
        return True

    start_m, end_m = (_AEGIS_HOOK_START, _AEGIS_HOOK_END) if _AEGIS_HOOK_START in content else (_SOMA_HOOK_START, _SOMA_HOOK_END)
    start = content.find(start_m)
    end = content.find(end_m, start)
    if end >= 0:
        line_start = content.rfind("\n", 0, start) + 1
        end += len(end_m)
        if content.startswith("\r\n", end):
            end += 2
        elif content.startswith("\n", end):
            end += 1
        remaining = content[:line_start] + content[end:]
    else:
        print(f"  ⚠️  {target_file} has an unterminated hook block; left unchanged", file=sys.stderr)
        return False

    stripped_lines = [line.strip() for line in remaining.splitlines() if line.strip()]
    is_empty_or_shebang_only = (
        not stripped_lines
        or (len(stripped_lines) == 1 and stripped_lines[0].startswith("#!"))
    )

    if is_empty_or_shebang_only:
        if hook_file.is_symlink():
            try:
                target_file.unlink()
            except OSError:
                pass
            try:
                hook_file.unlink()
            except OSError:
                pass
        else:
            hook_file.unlink()
        return True

    remaining = remaining.replace("\r\n", "\n")
    tmp_file = target_file.parent / f".pre-commit.tmp.{os.getpid()}"
    try:
        tmp_file.write_bytes(remaining.encode("utf-8"))
        if os.name != "nt":
            tmp_file.chmod(target_file.stat().st_mode)
        tmp_file.replace(target_file)
    finally:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass
    return True


def _hooks_dir_in_work_tree(root: Path, git_hooks_dir: Path) -> bool:
    """True when core.hooksPath puts the hooks dir in the work tree, where it is
    normally tracked, so the machine-specific pinned paths would be committed."""
    hooks = git_hooks_dir.resolve()
    start = Path(root).resolve()
    for top in (start, *start.parents):
        dot_git = top / ".git"
        if dot_git.exists():
            if dot_git.is_dir() and hooks.is_relative_to(dot_git.resolve()):
                return False
            return hooks.is_relative_to(top)
    return False


def work_tree_warning(hook_file: str) -> str:
    return (f"Warning: {hook_file} is inside the work tree (core.hooksPath) and pins this "
            "machine's Python; do not commit it, or other clones fail closed until they run "
            "aegis hook install.")


def _pinned_value(text: str, var: str) -> str | None:
    match = re.search(rf"^{var}=(.+)$", text, re.MULTILINE)
    if not match:
        return None
    try:
        return shlex.split(match.group(1))[0]
    except (ValueError, IndexError):
        return match.group(1)


def hook_status(project_root: str | Path | Any | None = None) -> dict[str, Any]:
    """Inspect the aegis pre-commit hook in the target repository."""
    from aegis_core.workspace.base import Workspace
    from aegis_core.workspace.hooks import resolve_git_hooks_dir

    if isinstance(project_root, Workspace):
        ws = project_root
        root = ws.root
        git_hooks_dir = ws.git_hooks_dir
    else:
        root = Path(project_root or Path.cwd()).resolve()
        git_hooks_dir = resolve_git_hooks_dir(root)

    is_git_repo = git_hooks_dir is not None
    hook_file = (git_hooks_dir / "pre-commit") if is_git_repo else None

    hook_exists = hook_file.is_file() if hook_file else False
    managed = False
    format_version = None
    status = "no_git_repository"

    if is_git_repo:
        if not hook_exists:
            status = "not_installed"
        else:
            try:
                text = hook_file.read_text(encoding="utf-8", errors="replace")
                if _AEGIS_HOOK_START in text or _SOMA_HOOK_START in text:
                    managed = True
                    match = re.search(r"(?:aegis|soma)-hook-format:\s*(\d+)", text)
                    if match:
                        format_version = int(match.group(1))
                    else:
                        format_version = 1
                    if format_version == CURRENT_HOOK_FORMAT_VERSION:
                        status = "installed"
                    else:
                        status = "outdated"
                else:
                    status = "unmanaged"
            except OSError:
                status = "unreadable"

    interpreter = None
    aegis_path = None
    if managed:
        pinned = _pinned_value(text, "AEGIS_PYTHON")
        if pinned is not None:
            interpreter = {"path": pinned, "exists": os.path.isfile(pinned) and os.access(pinned, os.X_OK)}
        # The same test the hook makes before it runs; either missing path fails every commit.
        pinned = _pinned_value(text, "AEGIS_PATH")
        if pinned is not None:
            aegis_path = {"path": pinned,
                          "exists": os.path.isfile(os.path.join(pinned, "aegis_cli", "__init__.py"))}

    is_worktree = False
    if root and (root / ".git").is_file():
        is_worktree = True

    return {
        "status": status,
        "is_git_repo": is_git_repo,
        "is_worktree": is_worktree,
        "repository_root": str(root),
        "git_hooks_dir": str(git_hooks_dir) if git_hooks_dir else None,
        "hook_file": str(hook_file) if hook_file else None,
        "managed_by_aegis": managed,
        "format_version": format_version,
        "current_format_version": CURRENT_HOOK_FORMAT_VERSION,
        "interpreter": interpreter,
        "aegis_path": aegis_path,
        "hooks_dir_in_work_tree": bool(git_hooks_dir) and _hooks_dir_in_work_tree(root, git_hooks_dir),
    }


def run_hook_install(args: Any) -> int:
    ws = getattr(args, "ws", None) or getattr(args, "workspace", None)
    force = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    ok = install_hook(ws, force=force, dry_run=dry_run)
    st = hook_status(ws) if ok else {}
    if use_json:
        print(json.dumps({"status": "installed" if ok else "failed", "success": ok}))
    else:
        if ok:
            print(f"✅ aegis pre-commit hook installed ({st.get('hook_file')})")
        else:
            print("❌ Failed to install the aegis pre-commit hook (no .git directory or symlink outside repo)", file=sys.stderr)
    if st.get("hooks_dir_in_work_tree"):
        print(work_tree_warning(st["hook_file"]), file=sys.stderr)
    return 0 if ok else 1


def run_hook_uninstall(args: Any) -> int:
    ws = getattr(args, "ws", None) or getattr(args, "workspace", None)
    force = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    ok = uninstall_hook(ws, force=force, dry_run=dry_run)
    if use_json:
        print(json.dumps({"status": "uninstalled" if ok else "not_found", "success": ok}))
    else:
        if ok:
            print("✅ aegis pre-commit hook removed")
        else:
            print("ℹ️ No aegis pre-commit hook found to uninstall")
    return 0 if ok else 1


def run_hook_status(args: Any) -> int:
    ws = getattr(args, "ws", None) or getattr(args, "workspace", None)
    use_json = getattr(args, "json", False)
    st = hook_status(ws)

    if st["hooks_dir_in_work_tree"]:
        print(work_tree_warning(st["hook_file"]), file=sys.stderr)
    if use_json:
        print(json.dumps(st, indent=2))
        return 0

    print("Aegis Git Hook Status")
    print(f"  Repository Root: {st['repository_root']}")
    if not st["is_git_repo"]:
        print("  Hooks Directory: ❌ No .git directory found")
        return 0

    print(f"  Hooks Directory: {st['git_hooks_dir']}")
    print(f"  Worktree:        {'Yes (linked worktree)' if st['is_worktree'] else 'No (main repository)'}")

    if st["status"] == "installed":
        print(f"  Pre-commit Hook: ✅ Installed & Current (format: {st['format_version']})")
    elif st["status"] == "outdated":
        print(f"  Pre-commit Hook: ⚠️  Outdated format ({st['format_version']} < {st['current_format_version']}) — run 'aegis hook install' to refresh")
    elif st["status"] == "unmanaged":
        print("  Pre-commit Hook: ⚠️  Existing pre-commit hook present (not managed by aegis)")
    else:
        print("  Pre-commit Hook: ❌ Not installed — run 'aegis hook install'")

    for label, pinned in (("Runs:", st.get("interpreter")), ("Aegis path:", st.get("aegis_path"))):
        if pinned:
            mark = "✅" if pinned["exists"] else "❌ (missing: run 'aegis hook install')"
            print(f"  {label:<17}{pinned['path']} {mark}")
    return 0
