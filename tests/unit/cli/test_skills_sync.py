"""`aegis skills sync [--host ...] [--force] [--dry-run] [--json]` (v4.1 spec §3).

The packaged ``skills/<id>/SKILL.md`` are projected to ``.claude/skills/<id>/SKILL.md``
(Claude Code, Claude slot profile) and ``.agents/skills/<id>/SKILL.md`` (Codex CLI and
Antigravity share it, neutral slot wording). Each copy carries exactly ``name`` and
``description`` and, right after the closing ``---``, the provenance marker
``<!-- aegis:skill id=<id> v=1 sha=<12 hex> -->`` whose sha covers the LF-normalized
text after it. Only Aegis's own unedited copies are replaced; links, junctions and
anything outside the workspace are refused, and ``--force`` never overrides a refusal.
Every test runs with an empty HOME (tests/unit/cli/conftest.py).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

import pytest

from aegis_cli.cli import main
from aegis_cli.init import packaged_dir
from aegis_cli.skills_sync import sync_skills
from aegis_core import events
from aegis_core._version import __version__
from aegis_core.skills.slots import PLATFORM_SLOT_PROFILES, SLOT_REF_PATTERN
from conftest import symlink_or_skip

SKILLS = sorted(p.parent.name for p in packaged_dir("skills").glob("*/SKILL.md"))
CLAUDE_DIR = ".claude/skills"
SHARED_DIR = ".agents/skills"
MARKER = re.compile(r"<!-- aegis:skill id=([a-z0-9-]+) v=1 sha=([0-9a-f]{12}) -->")
ISO_UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "project"
    (root / ".aegis").mkdir(parents=True)
    return root


def _sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:12]


def _sync(ws: Path, *flags: str) -> int:
    return main(["skills", "sync", "--workspace", str(ws), *flags])


def _json(ws: Path, capsys, *flags: str):
    rc = main(["--json", "skills", "sync", "--workspace", str(ws), *flags])
    return rc, json.loads(capsys.readouterr().out)


def _source_parts(skill_id: str):
    """(raw frontmatter lines without the delimiters, body after the closing ---)."""
    text = (packaged_dir("skills") / skill_id / "SKILL.md").read_text(encoding="utf-8")
    lines = text.splitlines(True)
    close = next(i for i, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") == "---")
    return lines[1:close], "".join(lines[close + 1:])


def _render(body: str, profile: str) -> str:
    values = PLATFORM_SLOT_PROFILES[profile]
    return SLOT_REF_PATTERN.sub(lambda m: values[m.group(1)], body)


def _expected(skill_id: str, profile: str) -> bytes:
    """The projection built independently of aegis_cli.skills_sync."""
    frontmatter, body = _source_parts(skill_id)
    description = [line for line in frontmatter if line.startswith("description:")]
    assert len(description) == 1
    rendered = _render(body, profile)
    return ("---\n" + f"name: {skill_id}\n" + description[0] + "---\n"
            + f"<!-- aegis:skill id={skill_id} v=1 sha={_sha(rendered)} -->\n" + rendered).encode("utf-8")


def _files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _fixture_skill(source: Path, skill_id: str, body: str, *, eol: str = "\n",
                   description: str = "Does one thing well.") -> Path:
    path = source / skill_id / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (f"---\nid: {skill_id}\nname: Fancy Display Name\ndescription: {description}\n"
            f"kind: skill\ntrigger: user_request\naliases: [\"a\", \"b\"]\n---\n{body}")
    path.write_bytes(text.replace("\n", eol).encode("utf-8"))
    return path


# ── Projection: all 15 packaged skills ──────────────────────────────────────


def test_fifteen_packaged_skills_ship():
    assert len(SKILLS) == 15


def test_claude_code_gets_every_packaged_skill_with_the_claude_profile(ws, capsys):
    rc = _sync(ws, "--host", "claude-code")

    out = capsys.readouterr().out
    assert rc == 0
    for skill_id in SKILLS:
        assert (ws / CLAUDE_DIR / skill_id / "SKILL.md").read_bytes() == _expected(skill_id, "claude-code")
    assert not (ws / ".agents").exists()
    assert "15 created" in out


def test_codex_and_antigravity_share_one_directory_with_neutral_wording(ws):
    assert _sync(ws, "--host", "codex-cli,antigravity") == 0

    for skill_id in SKILLS:
        data = (ws / SHARED_DIR / skill_id / "SKILL.md").read_bytes()
        assert data == _expected(skill_id, "generic")
        assert b"${SLOT." not in data
    assert not (ws / ".claude").exists()
    # The shared directory never carries one vendor's names: MODEL_FAST renders "fast".
    staff = (ws / SHARED_DIR / "staff-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "haiku" not in staff and "flash" not in staff.lower()


def test_the_shared_directory_is_the_same_whichever_host_selects_it(ws, tmp_path):
    other = tmp_path / "other"
    (other / ".aegis").mkdir(parents=True)
    assert _sync(ws, "--host", "codex-cli") == 0
    assert _sync(other, "--host", "antigravity") == 0
    assert _files(ws / SHARED_DIR) == _files(other / SHARED_DIR)


def test_frontmatter_is_exactly_name_and_the_verbatim_description(ws):
    assert _sync(ws, "--host", "claude-code,codex-cli") == 0

    for skill_id in SKILLS:
        source_frontmatter, _body = _source_parts(skill_id)
        source_description = next(line for line in source_frontmatter if line.startswith("description:"))
        for directory in (CLAUDE_DIR, SHARED_DIR):
            lines = (ws / directory / skill_id / "SKILL.md").read_text(encoding="utf-8").splitlines(True)
            assert lines[:4] == ["---\n", f"name: {skill_id}\n", source_description, "---\n"]
            marker = MARKER.fullmatch(lines[4].rstrip("\n"))
            assert marker and marker.group(1) == skill_id
            assert marker.group(2) == _sha("".join(lines[5:]))


def test_a_fixture_skill_is_projected_byte_for_byte(ws, tmp_path):
    source = tmp_path / "source"
    _fixture_skill(source, "demo", "\n# Demo\nUse `${SLOT.TOOL_EDIT}` on the ${SLOT.MODEL_FAST} tier. Keep ${HOME}.\n")

    result = sync_skills(ws, ["claude-code"], source=source)

    body = "\n# Demo\nUse `Edit` on the haiku tier. Keep ${HOME}.\n"
    expected = (f"---\nname: demo\ndescription: Does one thing well.\n---\n"
                f"<!-- aegis:skill id=demo v=1 sha={_sha(body)} -->\n{body}").encode("utf-8")
    assert (ws / CLAUDE_DIR / "demo" / "SKILL.md").read_bytes() == expected
    assert result.status == "ok"
    assert [(e.id, e.result) for t in result.targets for e in t.entries] == [("demo", "created")]


def test_a_crlf_source_keeps_its_line_endings_and_the_lf_sha(ws, tmp_path):
    source = tmp_path / "source"
    _fixture_skill(source, "demo", "\n# Demo\nRun ${SLOT.TOOL_RUN}.\n", eol="\r\n")

    sync_skills(ws, ["claude-code"], source=source)

    body_lf = "\n# Demo\nRun Bash.\n"
    expected = (f"---\nname: demo\ndescription: Does one thing well.\n---\n"
                f"<!-- aegis:skill id=demo v=1 sha={_sha(body_lf)} -->\n{body_lf}").replace("\n", "\r\n")
    assert (ws / CLAUDE_DIR / "demo" / "SKILL.md").read_bytes() == expected.encode("utf-8")


def test_a_source_ending_at_its_closing_delimiter_projects_an_empty_body(ws, tmp_path):
    source = tmp_path / "source"
    path = source / "bare" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nid: bare\ndescription: Nothing else.\n---", encoding="utf-8")

    result = sync_skills(ws, ["claude-code"], source=source)

    assert result.status == "ok"
    assert (ws / CLAUDE_DIR / "bare" / "SKILL.md").read_text(encoding="utf-8") == (
        f"---\nname: bare\ndescription: Nothing else.\n---\n<!-- aegis:skill id=bare v=1 sha={_sha('')} -->\n")


@pytest.mark.parametrize("name,text,problem", [
    ("Bad_Id", "---\nid: Bad_Id\ndescription: d\n---\nbody\n", "Bad_Id"),
    ("skill-x", "---\nid: other\ndescription: d\n---\nbody\n", "other"),
    ("nodesc", "---\nid: nodesc\n---\nbody\n", "description"),
    ("skill-x", "---\nid: skill-x\ndescription: [a, b]\n---\nbody\n", "description"),
    ("skill-x", "no frontmatter\n", "frontmatter"),
    ("skill-x", "---\nid: open\ndescription: d\n", "frontmatter"),
    ("skill-x", "---\nid: skill-x\ndescription: \"unterminated\n---\nbody\n", "frontmatter"),
])
def test_a_packaged_skill_that_cannot_be_projected_is_an_error_and_written_nowhere(ws, tmp_path, name, text, problem):
    source = tmp_path / "source"
    (source / name).mkdir(parents=True)
    (source / name / "SKILL.md").write_text(text, encoding="utf-8")
    _fixture_skill(source, "good", "\nfine\n")

    result = sync_skills(ws, ["claude-code"], source=source)

    assert result.status == "failed"
    assert len(result.errors) == 1 and problem in result.errors[0] and name in result.errors[0]
    assert sorted(p.name for p in (ws / CLAUDE_DIR).iterdir()) == ["good"]


def test_a_multi_line_description_is_copied_verbatim(ws, tmp_path):
    source = tmp_path / "source"
    path = source / "folded" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nid: folded\ndescription: >\n  First line\n  second line.\nkind: skill\n---\nBody\n",
                    encoding="utf-8")

    result = sync_skills(ws, ["claude-code"], source=source)

    sha = _sha("Body\n")
    assert result.status == "ok"
    assert (ws / CLAUDE_DIR / "folded" / "SKILL.md").read_text(encoding="utf-8") == (
        "---\nname: folded\ndescription: >\n  First line\n  second line.\n---\n"
        f"<!-- aegis:skill id=folded v=1 sha={sha} -->\nBody\n")


def test_no_packaged_skills_is_an_error(ws, tmp_path):
    result = sync_skills(ws, ["claude-code"], source=tmp_path / "missing")
    assert result.status == "failed"
    assert result.errors and "no packaged skills" in result.errors[0]
    assert not (ws / ".claude").exists()


# ── Idempotency and overwrite rules ──────────────────────────────────────────


def test_a_second_run_changes_nothing(ws, capsys):
    assert _sync(ws, "--host", "claude-code,antigravity") == 0
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in ws.rglob("SKILL.md")}
    capsys.readouterr()

    rc, doc = _json(ws, capsys, "--host", "claude-code,antigravity")

    assert rc == 0 and doc["status"] == "ok"
    assert doc["counts"] == {"created": 0, "updated": 0, "unchanged": 30, "overwritten": 0,
                             "skipped": 0, "refused": 0, "failed": 0}
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in ws.rglob("SKILL.md")}
    assert len(after) == 30
    assert after == before


def test_an_unedited_aegis_copy_is_updated_when_the_packaged_skill_changes(ws, tmp_path):
    source = tmp_path / "source"
    _fixture_skill(source, "demo", "\nversion one\n")
    sync_skills(ws, ["claude-code"], source=source)
    _fixture_skill(source, "demo", "\nversion two\n", description="Now better.")

    result = sync_skills(ws, ["claude-code"], source=source)

    entry = result.targets[0].entries[0]
    assert (entry.result, entry.reason) == ("updated", None)
    text = (ws / CLAUDE_DIR / "demo" / "SKILL.md").read_text(encoding="utf-8")
    assert text.endswith("\nversion two\n") and "description: Now better.\n" in text


def test_a_crlf_checkout_of_an_aegis_copy_still_counts_as_aegis_s_copy(ws, tmp_path):
    """git may rewrite the copy with CRLF line endings; the LF-normalized sha still matches."""
    source = tmp_path / "source"
    _fixture_skill(source, "demo", "\nversion one\n")
    sync_skills(ws, ["claude-code"], source=source)
    target = ws / CLAUDE_DIR / "demo" / "SKILL.md"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))

    result = sync_skills(ws, ["claude-code"], source=source)

    assert result.targets[0].entries[0].result == "updated"
    assert b"\r\n" not in target.read_bytes()


def _edited(ws: Path, skill_id: str = "genesis") -> Path:
    target = ws / CLAUDE_DIR / skill_id / "SKILL.md"
    target.write_bytes(target.read_bytes() + b"\nMy own note.\n")
    return target


def test_a_hand_edited_copy_is_reported_and_skipped(ws, capsys):
    assert _sync(ws, "--host", "claude-code") == 0
    target = _edited(ws)
    edited = target.read_bytes()
    capsys.readouterr()

    rc, doc = _json(ws, capsys, "--host", "claude-code")

    assert rc == 0
    assert target.read_bytes() == edited
    entry = next(e for e in doc["targets"][0]["skills"] if e["id"] == "genesis")
    assert entry["result"] == "skipped" and entry["reason"] == "edited"
    assert "--force" in entry["detail"]
    assert doc["counts"]["skipped"] == 1 and doc["counts"]["unchanged"] == 14


def test_force_replaces_a_hand_edited_copy(ws, capsys):
    assert _sync(ws, "--host", "claude-code") == 0
    target = _edited(ws)
    capsys.readouterr()

    rc, doc = _json(ws, capsys, "--host", "claude-code", "--force")

    assert rc == 0
    assert target.read_bytes() == _expected("genesis", "claude-code")
    entry = next(e for e in doc["targets"][0]["skills"] if e["id"] == "genesis")
    assert entry["result"] == "overwritten"
    assert doc["force"] is True


@pytest.mark.parametrize("force", [False, True])
def test_a_file_without_the_marker_is_never_replaced(ws, capsys, force):
    target = ws / CLAUDE_DIR / "genesis" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"---\nname: genesis\ndescription: mine\n---\nMy own genesis.\n")

    rc, doc = _json(ws, capsys, "--host", "claude-code", *(["--force"] if force else []))

    assert rc == 0
    assert target.read_bytes() == b"---\nname: genesis\ndescription: mine\n---\nMy own genesis.\n"
    entry = next(e for e in doc["targets"][0]["skills"] if e["id"] == "genesis")
    assert (entry["result"], entry["reason"]) == ("skipped", "foreign")
    assert "even with --force" in entry["detail"]
    assert doc["counts"]["created"] == 14


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda t: t.replace("name: genesis\n", "name: genesis\nallowed-tools: Bash\n"), id="extra-key"),
    pytest.param(lambda t: t.replace("id=genesis ", "id=staff-review "), id="other-id"),
    pytest.param(lambda t: t.replace(" v=1 ", " v=2 "), id="other-version"),
    pytest.param(lambda t: t.replace("name: genesis\n", "name: renamed\n"), id="renamed"),
])
def test_a_copy_whose_marker_or_frontmatter_is_not_aegis_s_counts_as_edited(ws, capsys, mutate):
    assert _sync(ws, "--host", "claude-code") == 0
    target = ws / CLAUDE_DIR / "genesis" / "SKILL.md"
    changed = mutate(target.read_text(encoding="utf-8"))
    target.write_text(changed, encoding="utf-8")
    capsys.readouterr()

    rc, doc = _json(ws, capsys, "--host", "claude-code")

    assert rc == 0 and target.read_text(encoding="utf-8") == changed
    entry = next(e for e in doc["targets"][0]["skills"] if e["id"] == "genesis")
    assert (entry["result"], entry["reason"]) == ("skipped", "edited")


def test_a_marker_that_is_not_right_after_the_frontmatter_is_not_a_marker(ws, capsys):
    assert _sync(ws, "--host", "claude-code") == 0
    target = ws / CLAUDE_DIR / "genesis" / "SKILL.md"
    lines = target.read_text(encoding="utf-8").splitlines(True)
    moved = "".join(lines[:4] + ["\n"] + lines[4:])
    target.write_text(moved, encoding="utf-8")
    capsys.readouterr()

    _rc, doc = _json(ws, capsys, "--host", "claude-code", "--force")

    entry = next(e for e in doc["targets"][0]["skills"] if e["id"] == "genesis")
    assert (entry["result"], entry["reason"]) == ("skipped", "foreign")
    assert target.read_text(encoding="utf-8") == moved


def test_a_non_utf8_skill_file_is_the_user_s_own(ws, capsys):
    target = ws / CLAUDE_DIR / "genesis" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\xfe not utf-8")

    _rc, doc = _json(ws, capsys, "--host", "claude-code", "--force")

    entry = next(e for e in doc["targets"][0]["skills"] if e["id"] == "genesis")
    assert (entry["result"], entry["reason"]) == ("skipped", "foreign")
    assert target.read_bytes() == b"\xff\xfe not utf-8"


# ── Safety: links, junctions, confinement ────────────────────────────────────


@pytest.mark.parametrize("force", [False, True])
def test_a_linked_skills_directory_is_refused_even_with_force(ws, tmp_path, capsys, force):
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_or_skip(outside, ws / ".claude", target_is_directory=True)

    rc, doc = _json(ws, capsys, "--host", "claude-code", *(["--force"] if force else []))

    assert rc == 1 and doc["status"] == "refused"
    assert list(outside.iterdir()) == []
    reasons = {(e["result"], e["reason"]) for e in doc["targets"][0]["skills"]}
    assert reasons == {("refused", "link")}
    assert doc["counts"]["refused"] == 15


def test_a_link_to_a_directory_inside_the_workspace_is_refused_too(ws, capsys):
    (ws / "elsewhere" / "skills").mkdir(parents=True)
    symlink_or_skip(ws / "elsewhere", ws / ".agents", target_is_directory=True)

    rc, doc = _json(ws, capsys, "--host", "codex-cli")

    assert rc == 1
    assert list((ws / "elsewhere" / "skills").iterdir()) == []
    assert {e["reason"] for e in doc["targets"][0]["skills"]} == {"link"}


def test_a_junction_like_directory_resolving_elsewhere_is_refused(ws, tmp_path, capsys, monkeypatch):
    """A Windows junction is no symlink to os.path.islink before Python 3.12; the realpath
    check refuses it anyway. Simulated by hiding a symlink from islink (the OS boundary)."""
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_or_skip(outside, ws / ".claude", target_is_directory=True)
    real_islink = os.path.islink
    monkeypatch.setattr(os.path, "islink", lambda p: False if Path(p) == ws / ".claude" else real_islink(p))
    monkeypatch.setattr(os.path, "isjunction", lambda p: False, raising=False)

    rc, doc = _json(ws, capsys, "--host", "claude-code", "--force")

    assert rc == 1
    assert list(outside.iterdir()) == []
    entry = doc["targets"][0]["skills"][0]
    assert (entry["result"], entry["reason"]) == ("refused", "outside")
    assert "inside the workspace" in entry["detail"]


def test_a_linked_skill_file_is_refused_and_its_target_untouched(ws, tmp_path, capsys):
    victim = tmp_path / "victim.md"
    victim.write_bytes(b"precious\n")
    (ws / CLAUDE_DIR / "genesis").mkdir(parents=True)
    symlink_or_skip(victim, ws / CLAUDE_DIR / "genesis" / "SKILL.md")

    rc, doc = _json(ws, capsys, "--host", "claude-code", "--force")

    assert rc == 1
    assert victim.read_bytes() == b"precious\n"
    entry = next(e for e in doc["targets"][0]["skills"] if e["id"] == "genesis")
    assert (entry["result"], entry["reason"]) == ("refused", "link")
    assert doc["counts"]["created"] == 14


def test_a_hard_linked_aegis_copy_is_refused_even_with_force(ws, tmp_path, capsys):
    assert _sync(ws, "--host", "claude-code") == 0
    target = ws / CLAUDE_DIR / "genesis" / "SKILL.md"
    _edited(ws)
    twin = tmp_path / "twin.md"
    try:
        os.link(target, twin)
    except OSError:
        pytest.skip("hard links are unavailable")
    before = twin.read_bytes()
    capsys.readouterr()

    rc, doc = _json(ws, capsys, "--host", "claude-code", "--force")

    assert rc == 1 and twin.read_bytes() == before
    entry = next(e for e in doc["targets"][0]["skills"] if e["id"] == "genesis")
    assert (entry["result"], entry["reason"]) == ("refused", "hard_link")


@pytest.mark.parametrize("force", [False, True])
def test_a_read_only_aegis_copy_is_refused_even_with_force(ws, tmp_path, force):
    source = tmp_path / "source"
    _fixture_skill(source, "demo", "\nversion one\n")
    sync_skills(ws, ["claude-code"], source=source)
    target = ws / CLAUDE_DIR / "demo" / "SKILL.md"
    before = target.read_bytes()
    _fixture_skill(source, "demo", "\nversion two\n")
    os.chmod(target, 0o444)
    try:
        result = sync_skills(ws, ["claude-code"], source=source, force=force)
    finally:
        os.chmod(target, 0o644)

    entry = result.targets[0].entries[0]
    assert (entry.result, entry.reason) == ("refused", "read_only")
    assert "read-only" in entry.detail and result.status == "refused"
    assert target.read_bytes() == before


def test_an_unchanged_read_only_copy_is_simply_unchanged(ws, tmp_path):
    source = tmp_path / "source"
    _fixture_skill(source, "demo", "\nversion one\n")
    sync_skills(ws, ["claude-code"], source=source)
    target = ws / CLAUDE_DIR / "demo" / "SKILL.md"
    os.chmod(target, 0o444)
    try:
        result = sync_skills(ws, ["claude-code"], source=source)
    finally:
        os.chmod(target, 0o644)
    assert result.targets[0].entries[0].result == "unchanged" and result.status == "ok"


@pytest.mark.parametrize("make,where,reason", [
    (lambda ws: (ws / ".claude").write_text("x"), ".claude", "not_directory"),
    (lambda ws: ((ws / ".claude").mkdir(), (ws / CLAUDE_DIR).write_text("x")), CLAUDE_DIR, "not_directory"),
    (lambda ws: (ws / CLAUDE_DIR / "genesis" / "SKILL.md").mkdir(parents=True), "genesis/SKILL.md", "not_regular"),
])
def test_a_component_of_the_wrong_kind_is_refused(ws, capsys, make, where, reason):
    make(ws)

    rc, doc = _json(ws, capsys, "--host", "claude-code", "--force")

    assert rc == 1
    refused = [e for e in doc["targets"][0]["skills"] if e["result"] == "refused"]
    assert refused and {e["reason"] for e in refused} == {reason}
    assert all(where in e["detail"] for e in refused)


# ── Dry run, output contract, events ─────────────────────────────────────────


def test_dry_run_writes_nothing_and_records_no_event(ws, capsys):
    before = _files(ws)

    rc, doc = _json(ws, capsys, "--host", "claude-code,codex-cli", "--dry-run")

    assert rc == 0 and doc["dry_run"] is True
    assert doc["counts"]["created"] == 30
    assert _files(ws) == before and not (ws / ".claude").exists() and not (ws / ".agents").exists()
    assert events.read(ws, "skills_sync").rows == []


def test_dry_run_text_says_what_would_happen(ws, capsys):
    assert _sync(ws, "--host", "claude-code", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "would create" in out and "Dry run" in out
    assert not (ws / ".claude").exists()


def test_json_output_carries_the_envelope_and_posix_paths(ws, capsys):
    rc, doc = _json(ws, capsys, "--host", "antigravity,claude-code")

    assert rc == 0
    assert doc["source"] == "aegis skills sync"
    assert doc["aegis_version"] == __version__
    assert ISO_UTC.fullmatch(doc["checked_at"])
    assert doc["scope"] == {"workspace": str(ws.resolve()), "hosts": ["claude-code", "antigravity"],
                            "targets": [CLAUDE_DIR, SHARED_DIR]}
    assert (doc["dry_run"], doc["force"], doc["status"]) == (False, False, "ok")
    claude, shared = doc["targets"]
    assert (claude["dir"], claude["hosts"], claude["profile"]) == (CLAUDE_DIR, ["claude-code"], "claude-code")
    assert (shared["dir"], shared["hosts"], shared["profile"]) == (SHARED_DIR, ["antigravity"], "generic")
    assert claude["skills"][0] == {"id": SKILLS[0], "path": f"{CLAUDE_DIR}/{SKILLS[0]}/SKILL.md",
                                   "result": "created", "reason": None, "detail": ""}
    assert [e["id"] for e in shared["skills"]] == SKILLS
    assert doc["errors"] == [] and doc["warnings"] == []


def test_unverified_skills_directories_are_labelled(ws, capsys):
    rc, doc = _json(ws, capsys, "--host", "claude-code,codex-cli")
    assert rc == 0
    assert [t["skills_verified"] for t in doc["targets"]] == [False, False]

    assert _sync(ws, "--host", "claude-code,codex-cli") == 0
    out = capsys.readouterr().out
    assert out.count("unverified") == 2


def test_a_real_run_records_one_skills_sync_event(ws):
    assert _sync(ws, "--host", "claude-code,codex-cli") == 0

    rows = events.read(ws, "skills_sync").rows
    assert len(rows) == 1
    row = rows[0]
    assert row["result"] == "ok"
    assert row["detail"] == {
        "trigger": "sync", "hosts": ["codex-cli", "claude-code"], "targets": [SHARED_DIR, CLAUDE_DIR],
        "force": False,
        "counts": {"created": 30, "updated": 0, "unchanged": 0, "overwritten": 0,
                   "skipped": 0, "refused": 0, "failed": 0},
    }


def test_a_refused_run_records_its_result(ws, tmp_path):
    symlink_or_skip(tmp_path, ws / ".claude", target_is_directory=True)
    assert _sync(ws, "--host", "claude-code") == 1
    assert [r["result"] for r in events.read(ws, "skills_sync").rows] == ["refused"]


def test_an_event_log_that_cannot_be_written_is_a_warning_not_a_failure(ws, tmp_path, capsys):
    away = tmp_path / "away"
    away.mkdir()
    symlink_or_skip(away, ws / ".aegis" / "state", target_is_directory=True)

    rc, doc = _json(ws, capsys, "--host", "claude-code")

    assert rc == 0 and doc["status"] == "ok"
    assert len(doc["warnings"]) == 1 and "skills_sync event" in doc["warnings"][0]
    assert (ws / CLAUDE_DIR / "genesis" / "SKILL.md").is_file()
    assert list(away.iterdir()) == []


# ── Hosts and workspace ──────────────────────────────────────────────────────


def test_without_host_the_repository_s_configured_hosts_are_used(ws):
    (ws / ".aegis" / "config.json").write_text('{"v": 1, "hosts": ["antigravity"]}', encoding="utf-8")

    assert _sync(ws) == 0

    assert (ws / SHARED_DIR / "genesis" / "SKILL.md").is_file()
    assert not (ws / ".claude").exists()


def test_configured_hosts_without_a_skills_directory_are_named_in_warnings(ws, capsys):
    (ws / ".aegis" / "config.json").write_text(
        '{"v": 1, "hosts": ["claude-desktop", "gemini-cli", "nope", "claude-code"]}', encoding="utf-8")

    rc, doc = _json(ws, capsys)

    assert rc == 0
    assert [t["dir"] for t in doc["targets"]] == [CLAUDE_DIR]
    joined = "\n".join(doc["warnings"])
    assert "claude-desktop" in joined and "gemini-cli is not supported" in joined and "'nope'" in joined


def test_no_host_to_project_for_is_a_usage_error(ws, capsys):
    assert _sync(ws) == 2
    err = capsys.readouterr().err
    assert "no host" in err and "--host" in err
    assert not (ws / ".claude").exists() and not (ws / ".agents").exists()


def test_an_unreadable_config_without_host_is_a_usage_error(ws, capsys):
    (ws / ".aegis" / "config.json").write_text("{not json", encoding="utf-8")
    assert _sync(ws) == 2
    assert "config.json" in capsys.readouterr().err


def test_the_retired_gemini_cli_is_refused_with_its_message(ws, capsys):
    with pytest.raises(SystemExit) as exc:
        _sync(ws, "--host", "gemini-cli")
    assert exc.value.code == 2
    assert ("gemini-cli is not supported: Google retired Gemini CLI for individual Code Assist "
            "accounts; use --host antigravity.") in capsys.readouterr().err


def test_host_auto_uses_the_detected_hosts(ws, monkeypatch, tmp_path):
    (tmp_path / "home" / ".codex").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    assert _sync(ws, "--host", "auto") == 0

    assert (ws / SHARED_DIR / "genesis" / "SKILL.md").is_file() and not (ws / ".claude").exists()


def test_host_auto_with_nothing_detected_is_a_usage_error(ws, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert _sync(ws, "--host", "auto") == 2
    assert "no host detected" in capsys.readouterr().err


def test_a_directory_that_is_not_an_aegis_workspace_is_a_usage_error(tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _sync(plain, "--host", "claude-code") == 2
    assert "not an Aegis workspace" in capsys.readouterr().err
    assert not (plain / ".claude").exists()


def test_skills_without_an_action_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["skills"])
    assert exc.value.code == 2
