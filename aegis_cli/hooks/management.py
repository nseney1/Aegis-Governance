"""Git hook lifecycle management: install, uninstall, status inspection, and block generation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any

_AEGIS_HOOK_START = "# >>> aegis pre-commit >>>"
_AEGIS_HOOK_END = "# <<< aegis pre-commit <<<"
_SOMA_HOOK_START = "# >>> soma pre-commit >>>"
_SOMA_HOOK_END = "# <<< soma pre-commit <<<"
AEGIS_HOOK_FORMAT = "# aegis-hook-format:"
SOMA_HOOK_FORMAT = "# soma-hook-format:"
CURRENT_HOOK_FORMAT_VERSION = 4


def generate_hook_block(python: str | None = None) -> str:
    """The marked pre-commit block (portable POSIX sh with dynamic multi-repo resolution)."""
    py = python if python is not None else sys.executable
    if os.name == "nt":
        py = py.replace("\\", "/")
    q = shlex.quote(py)
    return (
        f"{_AEGIS_HOOK_START}\n"
        "# Installed by aegis hook install\n"
        f"{AEGIS_HOOK_FORMAT} {CURRENT_HOOK_FORMAT_VERSION}\n"
        "if command -v aegis >/dev/null 2>&1; then\n"
        "  exec aegis check --hook\n"
        "elif command -v soma >/dev/null 2>&1; then\n"
        "  exec soma check --hook\n"
        'elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ] && "$VIRTUAL_ENV/bin/python" -c \'import aegis_cli\' >/dev/null 2>&1; then\n'
        '  exec "$VIRTUAL_ENV/bin/python" -m aegis_cli check --hook\n'
        'elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/Scripts/python.exe" ] && "$VIRTUAL_ENV/Scripts/python.exe" -c \'import aegis_cli\' >/dev/null 2>&1; then\n'
        '  exec "$VIRTUAL_ENV/Scripts/python.exe" -m aegis_cli check --hook\n'
        'elif [ -x "$PWD/.venv/bin/python" ] && "$PWD/.venv/bin/python" -c \'import aegis_cli\' >/dev/null 2>&1; then\n'
        '  exec "$PWD/.venv/bin/python" -m aegis_cli check --hook\n'
        'elif [ -x "$PWD/.venv/Scripts/python.exe" ] && "$PWD/.venv/Scripts/python.exe" -c \'import aegis_cli\' >/dev/null 2>&1; then\n'
        '  exec "$PWD/.venv/Scripts/python.exe" -m aegis_cli check --hook\n'
        f"elif {q} -c 'import aegis_cli' >/dev/null 2>&1; then\n"
        f"  exec {q} -m aegis_cli check --hook\n"
        "elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0)' 2>/dev/null && python3 -c 'import aegis_cli' >/dev/null 2>&1; then\n"
        "  exec python3 -m aegis_cli check --hook\n"
        'elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ] && "$VIRTUAL_ENV/bin/python" -c \'import soma_cli\' >/dev/null 2>&1; then\n'
        '  exec "$VIRTUAL_ENV/bin/python" -m soma_cli check --hook\n'
        "elif python3 -c 'import soma_cli' >/dev/null 2>&1; then\n"
        "  exec python3 -m soma_cli check --hook\n"
        "else\n"
        '  echo "aegis pre-commit: cannot execute quality checks." >&2\n'
        '  echo "  Neither \'aegis\' nor a Python interpreter with \'aegis_cli\' installed was found on PATH." >&2\n'
        '  echo "  Run \'aegis hook status\' or \'aegis doctor\' to diagnose environment resolution." >&2\n'
        "  exit 1\n"
        "fi\n"
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
) -> bool:
    """Install or refresh Soma pre-commit hook into a git repository."""
    from aegis_core.workspace import Workspace, resolve_git_hooks_dir

    if isinstance(project_root, Workspace):
        ws = project_root
        root = ws.root
        git_hooks_dir = ws.git_hooks_dir
    else:
        root = Path(project_root or Path.cwd()).resolve()
        git_hooks_dir = resolve_git_hooks_dir(root)

    if not git_hooks_dir:
        return False

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

    block = generate_hook_block(python)

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
    """Safely remove Soma pre-commit hook while preserving user hooks."""
    from aegis_core.workspace import Workspace, resolve_git_hooks_dir

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


def hook_status(project_root: str | Path | Any | None = None) -> dict[str, Any]:
    """Inspect and report the status of Soma git hooks in the target repository."""
    from aegis_core.workspace import Workspace, resolve_git_hooks_dir

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
    managed_by_soma = False
    format_version = None
    status = "no_git_repository"

    if is_git_repo:
        if not hook_exists:
            status = "not_installed"
        else:
            try:
                text = hook_file.read_text(encoding="utf-8", errors="replace")
                if _AEGIS_HOOK_START in text or _SOMA_HOOK_START in text:
                    managed_by_soma = True
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

    soma_path = shutil.which("soma")
    venv_env = os.environ.get("VIRTUAL_ENV")
    local_venv = None
    if root:
        for candidate in (root / ".venv" / "bin" / "python", root / ".venv" / "Scripts" / "python.exe"):
            if candidate.is_file():
                local_venv = str(candidate)
                break

    py3_path = shutil.which("python3")
    py3_valid = False
    if py3_path:
        try:
            res = subprocess.run([py3_path, "-c", "import sys; sys.exit(0)"], capture_output=True, timeout=2)
            py3_valid = (res.returncode == 0)
        except Exception:
            py3_valid = False

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
        "managed_by_soma": managed_by_soma,
        "format_version": format_version,
        "current_format_version": CURRENT_HOOK_FORMAT_VERSION,
        "interpreters": {
            "soma_on_path": soma_path is not None,
            "soma_path": soma_path,
            "virtual_env": venv_env,
            "local_venv": local_venv,
            "python3": py3_path,
            "python3_valid": py3_valid,
        },
    }


def run_hook_install(args: Any) -> int:
    ws = getattr(args, "ws", None) or getattr(args, "workspace", None)
    force = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    ok = install_hook(ws, force=force, dry_run=dry_run)
    if use_json:
        print(json.dumps({"status": "installed" if ok else "failed", "success": ok}))
    else:
        if ok:
            st = hook_status(ws)
            print(f"✅ Soma pre-commit hook installed ({st.get('hook_file')})")
        else:
            print("❌ Failed to install Soma pre-commit hook (no .git directory or symlink outside repo)", file=sys.stderr)
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
            print("✅ Soma pre-commit hook removed")
        else:
            print("ℹ️ No Soma pre-commit hook found to uninstall")
    return 0 if ok else 1


def run_hook_status(args: Any) -> int:
    ws = getattr(args, "ws", None) or getattr(args, "workspace", None)
    use_json = getattr(args, "json", False)
    st = hook_status(ws)

    if use_json:
        print(json.dumps(st, indent=2))
        return 0

    print("🪝 Soma Git Hook Status")
    print(f"  Repository Root: {st['repository_root']}")
    if not st["is_git_repo"]:
        print("  Hooks Directory: ❌ No .git directory found")
        return 0

    print(f"  Hooks Directory: {st['git_hooks_dir']}")
    print(f"  Worktree:        {'Yes (linked worktree)' if st['is_worktree'] else 'No (main repository)'}")

    if st["status"] == "installed":
        print(f"  Pre-commit Hook: ✅ Installed & Current (format: {st['format_version']})")
    elif st["status"] == "outdated":
        print(f"  Pre-commit Hook: ⚠️  Outdated format ({st['format_version']} < {st['current_format_version']}) — run 'soma hook install' to refresh")
    elif st["status"] == "unmanaged":
        print("  Pre-commit Hook: ⚠️  Existing pre-commit hook present (not managed by Soma)")
    else:
        print("  Pre-commit Hook: ❌ Not installed — run 'soma hook install'")

    interp = st.get("interpreters", {})
    print("  Environment Resolution:")
    soma_disp = f"✅ ({interp['soma_path']})" if interp.get("soma_on_path") else "❌ (not found)"
    print(f"    • soma on PATH: {soma_disp}")
    venv_disp = f"✅ ({interp['virtual_env']})" if interp.get("virtual_env") else "❌ (none active)"
    print(f"    • VIRTUAL_ENV:  {venv_disp}")
    local_disp = f"✅ ({interp['local_venv']})" if interp.get("local_venv") else "❌ (none)"
    print(f"    • .venv:        {local_disp}")
    py3_disp = f"✅ ({interp['python3']})" if interp.get("python3_valid") else "❌ (invalid or missing)"
    print(f"    • python3:      {py3_disp}")
    return 0
