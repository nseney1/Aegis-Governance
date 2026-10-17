"""Python 3.9 compatibility for ``aegis_cli.hooks.commitmsg.install``.

``pathlib.Path.write_text`` gained the ``newline`` keyword in Python 3.10, while the
project supports Python 3.9+ and needs LF line endings in ``.git/hooks/prepare-commit-msg``
on every OS.
"""
from __future__ import annotations

from pathlib import Path

from aegis_cli.hooks import commitmsg


def test_install_writes_lf_bytes_without_py310_write_text_newline_kwarg(tmp_path, monkeypatch):
    real_write_text = Path.write_text

    def py39_write_text(self, data, encoding=None, errors=None):
        return real_write_text(self, data, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "write_text", py39_write_text)
    hooks_dir = tmp_path / "hooks"
    assert commitmsg.install(hooks_dir) == "installed"
    raw = (hooks_dir / commitmsg.HOOK_NAME).read_bytes()
    assert raw.startswith(b"#!/bin/sh\n") and b"\r\n" not in raw
    assert commitmsg.install(hooks_dir) == "unchanged"
