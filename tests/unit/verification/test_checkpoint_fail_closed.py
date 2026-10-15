"""Fail-closed and read-only regression tests for CLI/MCP checkpoint."""
import argparse
import os
from pathlib import Path

import pytest

from aegis_core.verification import checkpoint_checks


def _write_wall(root, content=None):
    path = root / '.aegis' / 'rules' / 'walls' / 'wall-test.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or (
        '---\n'
        'id: wall-test\n'
        'domain: testing\n'
        'type: wall\n'
        'enforcement: gate\n'
        '---\n'
        '# Test wall\n'
    ), encoding='utf-8')
    return path


def _snapshot(root):
    """Capture path set, file bytes, and symlink targets without following links."""
    result = {}

    def visit(directory):
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = Path(entry.path)
                rel = path.relative_to(root).as_posix()
                if entry.is_symlink():
                    result[rel] = ('symlink', os.readlink(entry.path))
                elif entry.is_dir(follow_symlinks=False):
                    result[rel] = ('directory', None)
                    visit(path)
                else:
                    result[rel] = ('file', path.read_bytes())

    visit(root)
    return result


def test_hardcoded_path_read_failure_is_an_issue(tmp_path, monkeypatch):
    source = tmp_path / 'src' / 'app.py'
    source.parent.mkdir()
    source.write_text('VALUE = 1\n', encoding='utf-8')
    real_read_text = Path.read_text

    def denied(path, *args, **kwargs):
        if path == source:
            raise PermissionError('simulated read denial')
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', denied)
    issues = checkpoint_checks.check_hardcoded_paths(tmp_path)
    assert any(
        issue['check'] == 'hardcoded_paths'
        and issue.get('file') == 'src/app.py'
        and 'read' in issue['message'].lower()
        for issue in issues
    )


def test_cell_stat_failure_is_an_issue(tmp_path, monkeypatch):
    import aegis_core.rule_inventory as inventory

    cell = _write_wall(tmp_path)
    real_stat = inventory.os.stat

    def denied(path, *args, **kwargs):
        if os.fspath(path) == str(cell):
            raise PermissionError('simulated stat denial')
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(inventory.os, 'stat', denied)
    issues = checkpoint_checks.check_cell_conventions(tmp_path)
    assert any(
        issue['check'] == 'cell_conventions'
        and issue.get('file') == '.aegis/rules/walls/wall-test.md'
        and 'stat' in issue['message'].lower()
        for issue in issues
    )


@pytest.mark.parametrize('content, expected', [
    ('---\nid: [unterminated\n---\nbody\n', 'malformed'),
    ('---\n- one\n- two\n---\nbody\n', 'mapping'),
    ('---\nid: wall-test\n', 'unterminated'),
])
def test_malformed_cell_frontmatter_is_an_issue(tmp_path, content, expected):
    _write_wall(tmp_path, content)
    issues = checkpoint_checks.check_cell_conventions(tmp_path)
    assert any(
        issue['check'] == 'cell_conventions'
        and expected in issue['message'].lower()
        for issue in issues
    ), issues


def _run_cli(root):
    from aegis_cli.checkpoint import run_checkpoint

    return run_checkpoint(argparse.Namespace(
        workspace=str(root), pre_commit=False, strict=True, json=False,
    ))


@pytest.mark.parametrize('malformed', [False, True], ids=['pass', 'fail'])
def test_checkpoint_is_recursively_read_only_on_pass_and_fail(tmp_path, malformed, capsys):
    content = '---\nid: [unterminated\n---\nbody\n' if malformed else None
    _write_wall(tmp_path, content)
    marker = tmp_path / '.marker'
    marker.write_bytes(b'unchanged bytes\x00\xff')
    external = tmp_path.parent / f'{tmp_path.name}-external'
    external.mkdir()
    link = tmp_path / '.snapshot-link'
    try:
        link.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks are unavailable')

    before = _snapshot(tmp_path)
    result = _run_cli(tmp_path)
    after = _snapshot(tmp_path)

    assert after == before
    assert result == (1 if malformed else 0)


def test_resolve_canonical_test_candidates(tmp_path: Path):
    """Verify deterministic test candidate resolution supports mirrored, subpackage, and fallback paths."""
    from aegis_core.verification.checkpoint_checks import _resolve_canonical_test_candidates

    # Subpackage file
    sub_src = tmp_path / "aegis_core" / "schemas" / "cells.py"
    candidates = [p.as_posix() for p in _resolve_canonical_test_candidates(tmp_path, sub_src)]

    # Must include canonical mirrored path and subpackage grouped test
    assert any("tests/core/schemas/test_cells.py" in c for c in candidates)
    assert any("tests/test_schemas.py" in c for c in candidates)

    # Standard module
    cli_src = tmp_path / "aegis_cli" / "promote.py"
    candidates_cli = [p.as_posix() for p in _resolve_canonical_test_candidates(tmp_path, cli_src)]
    assert any("tests/cli/test_promote.py" in c for c in candidates_cli)
    assert any("tests/test_cli_promote.py" in c for c in candidates_cli)
