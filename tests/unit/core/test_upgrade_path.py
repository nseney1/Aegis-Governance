"""The v3 -> v4 upgrade path never leaves a workspace stuck or silently unserved
(release review, upgrade findings 1-4).

- the .soma sentinel refuses while .soma/cells or .soma/rules still holds rule files,
  even after .aegis/ exists (an `aegis init` there must not make the old gates vanish);
- `aegis migrate` converts .soma/rules/<type>/ like .soma/cells/, and reports what
  blocks a workspace instead of "nothing to do" while the sentinel still refuses it;
- the ledger history v3.3 compaction archived, and the v2 .soma ledger, are converted;
  what is not converted is listed;
- unmigrated v3 state (ledger, config, keys, receipts, manifest) is detected.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from aegis_core import migrate
from aegis_core.errors import WorkspaceError
from aegis_core.telemetry_engine import ledger
from aegis_core.workspace.discovery import refuse_unmigrated_v3, unconverted_rule_files, unmigrated_state

WALL = "---\nid: no-eval\ntype: wall\nenforcement: gate\nforbid_ast:\n  calls: [eval]\n---\nNo eval.\n"


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _row(rule: str, event_id: str = "", ts: str = "2026-08-02T10:00:00Z", signal: str = "tp") -> dict:
    row = {"timestamp": ts, "rule_id": rule, "cell": rule, "signal": signal, "source": "session",
           "metadata": {"credit_weight": 1.0, "verdict": "PASS"}}
    if event_id:
        row["event_id"] = event_id
    return row


def _jsonl(rows) -> bytes:
    return "".join(json.dumps(r) + "\n" for r in rows).encode("utf-8")


def _gz(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(_jsonl(rows)))
    return path


# ── (a) the sentinel ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("folder", ["cells", "rules"])
def test_rule_files_left_in_soma_are_refused_even_with_an_aegis_dir(tmp_path, folder):
    root = tmp_path / "repo"
    (root / ".aegis" / "rules" / "personas").mkdir(parents=True)
    _write(root / ".soma" / folder / "walls" / "no-eval.md", WALL)

    with pytest.raises(WorkspaceError, match="aegis migrate"):
        refuse_unmigrated_v3(root)
    assert [p.relative_to(root).as_posix() for p in unconverted_rule_files(root)] == [
        f".soma/{folder}/walls/no-eval.md"
    ]


def test_a_soma_dir_without_rule_files_is_fine_next_to_aegis(tmp_path):
    root = tmp_path / "repo"
    (root / ".aegis" / "rules").mkdir(parents=True)
    _write(root / ".soma" / "cells" / "README.md", "# Cells\n")
    _write(root / ".soma" / "cells" / "walls" / ".hidden" / "x.md", WALL)
    (root / ".soma" / "rules" / "walls").mkdir(parents=True)

    refuse_unmigrated_v3(root)
    assert unconverted_rule_files(root) == []


# ── (b) migrate converts .soma/rules and never answers "nothing to do" for a refused workspace ──

def test_migrate_moves_soma_rules_like_soma_cells(tmp_path):
    root = tmp_path / "repo"
    _write(root / ".soma" / "rules" / "walls" / "no-eval.md", WALL)

    plan = migrate.plan(root)
    assert plan.to_dict()["rules"] == [
        {"from": ".soma/rules/walls/no-eval.md", "to": ".aegis/rules/invariants/no-eval.md", "type": "invariant"}
    ]
    migrate.apply(plan)

    assert (root / ".aegis" / "rules" / "invariants" / "no-eval.md").read_text(encoding="utf-8").startswith(
        "---\nid: no-eval\ntype: invariant\n")
    refuse_unmigrated_v3(root)  # served now: the sentinel lets it through
    assert migrate.plan(root).to_dict()["status"] == "up_to_date"


def test_a_soma_dir_with_nothing_to_convert_reports_how_to_clear_it(tmp_path):
    root = tmp_path / "repo"
    _write(root / ".soma" / "evidence" / "x.json", "{}")
    with pytest.raises(WorkspaceError):
        refuse_unmigrated_v3(root)

    report = migrate.plan(root).to_dict()

    assert report["status"] == "refused"
    assert ".soma" in report["refusal"]
    assert "rename or remove" in report["refusal"]


def test_rule_files_migrate_cannot_convert_block_with_their_reasons(tmp_path):
    root = tmp_path / "repo"
    (root / ".aegis" / "rules").mkdir(parents=True)
    _write(root / ".soma" / "cells" / "ribosomes" / "odd.md", "---\ntype: ribosome\n---\nBody\n")

    report = migrate.plan(root).to_dict()

    assert report["status"] == "refused"
    assert ".soma/cells/ribosomes/odd.md (unmapped type 'ribosome')" in report["refusal"]
    assert "rename or remove" in report["refusal"]


@pytest.mark.parametrize("layout", ["bare", "unmapped", "conflict", "cells", "rules"])
def test_migrate_is_never_up_to_date_while_the_sentinel_refuses(tmp_path, layout):
    root = tmp_path / "repo"
    if layout == "bare":
        (root / ".soma" / "evidence").mkdir(parents=True)
    elif layout == "unmapped":
        (root / ".aegis").mkdir(parents=True)
        _write(root / ".soma" / "cells" / "ribosomes" / "odd.md", "---\ntype: ribosome\n---\nBody\n")
    elif layout == "conflict":
        _write(root / ".aegis" / "rules" / "invariants" / "no-eval.md", "---\nid: other\ntype: invariant\n---\nX\n")
        _write(root / ".soma" / "cells" / "walls" / "no-eval.md", WALL)
    else:
        _write(root / ".soma" / layout / "walls" / "no-eval.md", WALL)

    for _round in range(2):
        with pytest.raises(WorkspaceError):
            refuse_unmigrated_v3(root)
        plan = migrate.plan(root)
        assert plan.to_dict()["status"] != "up_to_date"
        if plan.refusal or not plan.pending:
            break
        migrate.apply(plan)
        try:
            refuse_unmigrated_v3(root)
            break  # converted and served
        except WorkspaceError:
            continue  # the second round must still not say "nothing to do"


# ── (c) ledger history: archives, the v2 ledger, and what is not converted ──

def test_compacted_archives_are_converted_and_their_copies_deduplicated(tmp_path):
    root = tmp_path / "repo"
    aegis = root / ".aegis"
    (aegis / "rules").mkdir(parents=True)
    archived = [_row("no-eval", "e1"), _row("no-eval", "e2"), _row("trap-x", "e3")]
    _write(aegis / "evidence" / "signals.jsonl", "")  # v3.3 compaction left it empty
    _write(aegis / "telemetry" / "signals.jsonl", "")
    _gz(aegis / "evidence" / "archive" / "signals-2026-08.jsonl.gz", archived)
    _gz(aegis / "telemetry" / "archive" / "signals-2026-08.jsonl.gz", archived)  # the same rows, copied

    report = migrate.plan(root).to_dict()

    assert report["ledger"]["sources"] == [
        ".aegis/evidence/signals.jsonl", ".aegis/evidence/archive/signals-2026-08.jsonl.gz",
        ".aegis/telemetry/signals.jsonl", ".aegis/telemetry/archive/signals-2026-08.jsonl.gz",
    ]
    assert (report["ledger"]["rows"], report["ledger"]["duplicates"]) == (3, 3)
    migrate.apply(migrate.plan(root))
    assert ledger.aggregate(root, "no-eval")["tp"] == pytest.approx(2.0)
    assert ledger.aggregate(root, "trap-x")["tp"] == pytest.approx(1.0)


def test_archived_rows_without_an_event_id_count_once(tmp_path):
    root = tmp_path / "repo"
    aegis = root / ".aegis"
    rows = [_row("no-eval", ts="2026-08-01T00:00:00Z"), _row("no-eval", ts="2026-08-03T00:00:00Z")]
    _gz(aegis / "evidence" / "archive" / "signals-2026-08.jsonl.gz", rows)
    _gz(aegis / "telemetry" / "archive" / "signals-2026-08.jsonl.gz", rows)

    report = migrate.plan(root).to_dict()

    assert (report["ledger"]["rows"], report["ledger"]["duplicates"]) == (2, 2)


def test_an_unreadable_archive_is_reported_not_fatal(tmp_path):
    root = tmp_path / "repo"
    bad = _write(root / ".aegis" / "evidence" / "archive" / "signals-2026-07.jsonl.gz", "not gzip")
    _gz(root / ".aegis" / "evidence" / "archive" / "signals-2026-08.jsonl.gz", [_row("no-eval", "e1")])

    report = migrate.plan(root).to_dict()

    assert bad.relative_to(root).as_posix() in report["unreadable"]
    assert report["ledger"]["rows"] == 1


def test_the_v2_soma_ledger_is_converted_and_removed(tmp_path):
    root = tmp_path / "repo"
    (root / ".soma" / "evidence").mkdir(parents=True)
    (root / ".soma" / "evidence" / "signals.jsonl").write_bytes(_jsonl([_row("no-eval", "s1")]))

    plan = migrate.plan(root)
    report = plan.to_dict()
    assert report["ledger"]["sources"] == [".soma/evidence/signals.jsonl"]
    assert report["ledger"]["rows"] == 1
    assert ".soma/evidence/signals.jsonl" in report["remove"]

    migrate.apply(plan)

    assert ledger.aggregate(root, "no-eval")["tp"] == pytest.approx(1.0)
    assert not (root / ".soma" / "evidence" / "signals.jsonl").exists()
    assert migrate.plan(root).to_dict()["status"] == "up_to_date"


def test_what_is_not_converted_is_listed(tmp_path, _home):
    root = tmp_path / "repo"
    aegis = root / ".aegis"
    _write(aegis / "evidence" / "signals.jsonl", "")
    _write(aegis / "evidence" / "checkpoint_rollup.json", '{"rules": {}}\n')
    _write(aegis / "telemetry" / "checkpoint_rollup.json", '{"rules": {}}\n')
    _write(root / "steering.conf", "REVIEW_MODE=x\n")
    _write(_home / ".aegis" / "slots.yaml", "slots: {}\n")

    report = migrate.plan(root).to_dict()

    listed = {entry["path"]: entry["reason"] for entry in report["not_converted"]}
    assert set(listed) == {
        ".aegis/evidence/checkpoint_rollup.json", ".aegis/telemetry/checkpoint_rollup.json",
        "steering.conf", "~/.aegis/slots.yaml",
    }
    assert "no v4 setting" in listed["steering.conf"]
    assert "no v4 setting" in listed["~/.aegis/slots.yaml"]


def test_nothing_is_listed_as_not_converted_in_a_v4_workspace(tmp_path):
    root = tmp_path / "repo"
    (root / ".aegis" / "rules").mkdir(parents=True)
    assert migrate.plan(root).to_dict()["not_converted"] == []


# ── (d) unmigrated v3 state ──────────────────────────────────────────────────

V3_STATE = [
    ".aegis/evidence/signals.jsonl", ".aegis/telemetry/signals.jsonl", ".aegis/evidence/archive/",
    ".aegis/telemetry/archive/", ".aegis/slots.yaml", ".aegis/config.yaml", "aegis.conf",
    ".aegis/keys/", ".aegis/receipts.jsonl", ".aegis/rules/manifest.json", ".soma/evidence/signals.jsonl",
]


def _plant(root: Path, rel: str) -> None:
    path = root / rel.rstrip("/")
    if rel.endswith("/"):
        path.mkdir(parents=True)
    else:
        _write(path, "{}\n")


@pytest.mark.parametrize("rel", V3_STATE)
def test_unmigrated_state_names_what_it_found(tmp_path, rel):
    root = tmp_path / "repo"
    (root / ".aegis" / "rules").mkdir(parents=True)
    _plant(root, rel)
    assert unmigrated_state(root) == [rel.rstrip("/")]


def test_a_v4_workspace_has_no_unmigrated_state(tmp_path):
    root = tmp_path / "repo"
    (root / ".aegis" / "rules" / "traps").mkdir(parents=True)
    (root / ".aegis" / "state").mkdir()
    _write(root / ".aegis" / "config.json", '{"v": 1}\n')
    _write(root / ".aegis" / "state" / "ledger.jsonl", "")
    assert unmigrated_state(root) == []
