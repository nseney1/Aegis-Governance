"""Shipped rule and skill text names capabilities, not one host's tools (build-sheet D16).

Every host reads the same rules/ and skills/ text, rendered for it at scan time and at
skills sync (aegis_core.skills.slots.render_for_host). A hard-coded Antigravity tool or
model tier reads as nonsense on Codex or Claude Code, so the lint below rejects them and
checks that every placeholder renders for every host profile.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

from aegis_core.skills.slots import PLATFORM_SLOT_PROFILES, SLOT_REF_PATTERN, render_for_host

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
SHIPPED = sorted([*(ROOT / "rules").glob("*.md"), *(ROOT / "rules").glob(".oracles/*.md"),
                  *(ROOT / "skills").glob("*/SKILL.md")])
CAPABILITY_KEYS = set(PLATFORM_SLOT_PROFILES["generic"])

# One host's vocabulary. Tool and API names match as whole identifiers; model tiers
# match where the text uses them as a tier (`flash`, Flash subagents, inherit/pro).
HOST_SPECIFIC = {
    "Antigravity tool name": re.compile(
        r"\b(view_file|replace_file_content|multi_replace_file_content|write_to_file|grep_search|"
        r"invoke_subagent|define_subagent|kill_all|ConversationId|send_message|list_dir|run_command|"
        r"search_web|read_url_content|codebase_search|find_by_name|ask_question|review_orchestrator)\b"),
    "Gemini model tier": re.compile(r"\b[Ff]lash\b|`inherit`|`pro`|\binherit/pro\b"),
    "host product named as the only host": re.compile(r"\bAntigravity\b|\bantigravity\b|Gemini Providence"),
}
# Text that names a product as subject matter, not as the host running the rule.
ALLOWED = {("skills/domain-researcher/SKILL.md", "| **Gemini API** |")}


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_the_lint_sees_the_shipped_rules_and_skills():
    names = {_rel(p) for p in SHIPPED}
    assert "rules/subagent-delegation.md" in names and "skills/staff-review/SKILL.md" in names
    assert len([n for n in names if n.startswith("skills/")]) >= 15


@pytest.mark.parametrize("path", SHIPPED, ids=_rel)
def test_shipped_text_names_no_single_hosts_tools(path: Path):
    hits = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if any(_rel(path) == f and marker in line for f, marker in ALLOWED):
            continue
        for what, pattern in HOST_SPECIFIC.items():
            for match in pattern.finditer(line):
                hits.append(f"{_rel(path)}:{lineno}: {what}: {match.group(0)!r}")
    assert hits == [], "use ${SLOT.TOOL_*}/${SLOT.MODEL_*} or neutral wording:\n" + "\n".join(hits)


@pytest.mark.parametrize("path", SHIPPED, ids=_rel)
def test_every_placeholder_is_a_capability_every_host_binds(path: Path):
    text = path.read_text(encoding="utf-8")
    keys = {m.group(1) or m.group(2) for m in SLOT_REF_PATTERN.finditer(text)}
    assert keys <= CAPABILITY_KEYS, f"{_rel(path)}: unknown slots {sorted(keys - CAPABILITY_KEYS)}"


@pytest.mark.parametrize("host", sorted(PLATFORM_SLOT_PROFILES) + ["claude-desktop", "unknown-agent"])
def test_shipped_text_renders_completely_for_every_host(host: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for path in SHIPPED:
        rendered, warnings = render_for_host(path.read_text(encoding="utf-8"), host)
        assert "${SLOT." not in rendered, f"{_rel(path)} left a placeholder for {host}"
        assert warnings == []


def test_the_rewrite_uses_slots_where_hosts_differ():
    # The delegation and cost rules are the ones whose advice depends on the host's tools.
    for rel in ("rules/subagent-delegation.md", "rules/cost-optimization.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "${SLOT.MODEL_FAST}" in text, rel
    assert "${SLOT.TOOL_SUBAGENT}" in (ROOT / "rules" / "subagent-delegation.md").read_text(encoding="utf-8")
