"""BUG-073: an untrusted repository must not choose what Layer 2 runs.

v3 let workspace config name provider endpoints, which could send host API keys
to an attacker. v4 runs one command from ``--llm-cmd`` or ``AEGIS_LLM_CMD``
(D14), and a repo file must never supply it: ``aegis check --full`` in a repo
that tries to must still refuse to run Layer 2.
"""
from __future__ import annotations

import pytest

from aegis_cli.cli import main


def _exit_code(argv: list[str]) -> int:
    try:
        return main(argv)
    except SystemExit as exc:
        return exc.code


@pytest.mark.parametrize(
    "rel_path, content",
    [
        ("aegis.conf", "AEGIS_LLM_CMD=touch {marker}\n"),
        (".aegis/aegis.conf", "AEGIS_LLM_CMD=touch {marker}\n"),
        (".aegis/config.json", '{{"llm_cmd": "touch {marker}", "AEGIS_LLM_CMD": "touch {marker}"}}'),
    ],
)
def test_repo_config_cannot_supply_the_layer2_command(tmp_path, monkeypatch, capsys, rel_path, content):
    monkeypatch.delenv("AEGIS_LLM_CMD", raising=False)
    marker = tmp_path / "pwned"
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    config = tmp_path / rel_path
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(content.format(marker=marker), encoding="utf-8")

    rc = _exit_code(["check", "--workspace", str(tmp_path), "--full", "--plan", "ship it", "app.py"])

    assert rc == 2
    assert "Layer 2 needs --llm-cmd or AEGIS_LLM_CMD" in capsys.readouterr().err
    assert not marker.exists()
