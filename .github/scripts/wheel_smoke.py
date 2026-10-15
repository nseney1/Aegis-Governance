"""Smoke-test an installed Aegis distribution with the source checkout hidden.

Run with an interpreter that has the built wheel (or sdist) installed, from a
directory OUTSIDE the repository, in isolated mode so neither PYTHONPATH nor
the current directory can shadow site-packages:

    cd "$(mktemp -d)" && python -I /path/to/wheel_smoke.py

Fails (non-zero exit) if any Aegis module resolves from outside site-packages,
or if the CLI, the MCP server, or Governance SDK do not work.
"""
import importlib
import importlib.util
import json
import os
import site
import subprocess
import sys
import sysconfig
import tempfile

PACKAGES = ("aegis_cli", "aegis_sdk", "aegis_core", "aegis_mcp")
# Shipped rule floors (D16): rules/ has 4 rules plus META.md and rules/.oracles/
# has 8; the full preset installs all 12 rules (not META.md).
FULL_PRESET_RULES = 12
SOURCE_RULE_FILES = 13
# The author's dogfood rules live in the repository's .aegis/rules (D16), and
# desktop-automation is not shipped; none of them may reach the wheel.
UNSHIPPED_RULES = ("gitflow-review-gate", "ci-green-before-release", "core-change-protocol",
                   "no-pre-existing-excuse", "optional-import-guard", "desktop-automation")


def _ensure_site_packages():
    """Return (valid_site_roots, subprocess_isolation_flag).

    Under ``python -I``, user site-packages (``~/.local/lib/pythonX.Y/site-packages``)
    is omitted from ``sys.path``. When ``pip install`` defaulted to ``--user`` on a
    non-venv POSIX host, re-attach user site-packages while keeping CWD isolated.
    """
    roots = {os.path.realpath(sysconfig.get_paths()[k]) for k in ("purelib", "platlib")}
    user_site = getattr(site, "USER_SITE", None) or os.path.expanduser(
        f"~/.local/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    if user_site and os.path.isdir(user_site):
        real_user_site = os.path.realpath(user_site)
        roots.add(real_user_site)
        if importlib.util.find_spec("aegis_cli") is None:
            site.addsitedir(real_user_site)
            return roots, "-P"
    return roots, "-I"


_SITE_ROOTS, _SUBPROC_FLAG = _ensure_site_packages()


def fail(msg):
    print(f"wheel smoke FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def check_module_origins():
    for name in PACKAGES:
        mod = importlib.import_module(name)
        origin = os.path.realpath(getattr(mod, "__file__", "") or "")
        if not any(origin.startswith(r + os.sep) for r in _SITE_ROOTS):
            fail(f"{name} imported from {origin!r}, not from site-packages {sorted(_SITE_ROOTS)}")
        print(f"ok  {name:14s} {origin}")


def make_workspace():
    ws = tempfile.mkdtemp(prefix="aegis-smoke-")
    rules = os.path.join(ws, ".aegis", "rules", "traps")
    os.makedirs(rules)
    with open(os.path.join(rules, "trap-smoke.md"), "w", encoding="utf-8") as f:
        f.write("---\nid: trap-smoke\ntype: trap\nhypothesis: smoke\n"
                "prediction: smoke\ntarget_paths: ['*.py']\n---\n# Smoke\n")
    return ws


def check_cli():
    proc = subprocess.run([sys.executable, _SUBPROC_FLAG, "-m", "aegis_cli.cli", "--help"],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        fail(f"aegis --help exited {proc.returncode}: {proc.stderr[-500:]}")
    print("ok  aegis --help")


def check_mcp(ws):
    requests = "".join(json.dumps(r) + "\n" for r in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "aegis_list_rules", "arguments": {}}},
    ))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["AEGIS_WORKSPACE"] = ws
    proc = subprocess.run([sys.executable, _SUBPROC_FLAG, "-m", "aegis_mcp"], input=requests,
                          capture_output=True, text=True, timeout=60, cwd=ws, env=env)
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != 3:
        fail(f"MCP returned {len(lines)} responses: {proc.stdout[-500:]} {proc.stderr[-500:]}")
    tools = lines[1]["result"]["tools"]
    if len(tools) != 4:
        fail(f"MCP tools/list expected the 4 v4 tools, got {len(tools)}")
    payload = json.loads(lines[2]["result"]["content"][0]["text"])
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        fail(f"MCP aegis_list_rules returned no rules list: {payload!r}")
    if "trap-smoke" not in {c.get("_name") for c in rules if isinstance(c, dict)}:
        fail(f"MCP aegis_list_rules did not see the workspace rule: {rules!r}")
    print("ok  aegis_mcp initialize / tools/list (4 tools) / aegis_list_rules")


def check_governance_fitness(ws):
    from aegis_sdk.governance import Governance
    result = Governance(project_root=ws).fitness_landscape()
    if isinstance(result, dict) and "error" in result:
        fail(f"governance fitness_landscape failed: {result}")
    print("ok  governance (Governance.fitness_landscape)")


def check_full_rule_preset(ws):
    """Prove the wheel contains the full rules, not only starter rules."""
    from pathlib import Path
    from aegis_cli.init import install_rules

    target = Path(ws) / "full-rules"
    installed = install_rules(target, preset="full")
    files = sorted(target.glob("*.md"))
    if len(installed) < FULL_PRESET_RULES or len(files) != len(installed):
        fail(f"full rule preset is incomplete: installed={installed!r}, files={files!r}")
    leaked = sorted(set(installed) & set(UNSHIPPED_RULES))
    if leaked:
        fail(f"full rule preset ships rules that must stay unshipped: {leaked!r}")
    print(f"ok  packaged full rule preset ({len(installed)} rules)")


def check_packaged_skills_and_platform_adapter(ws):
    """Prove the wheel packages skills/ and PlatformAdapter resolves rules + skills from site-packages."""
    from pathlib import Path
    from aegis_cli.platforms.gemini import GeminiPlatformAdapter
    from aegis_mcp.registry import TOOL_DEFINITIONS

    if len(TOOL_DEFINITIONS) != 4:
        fail(f"TOOL_DEFINITIONS expected the 4 v4 tools, got {len(TOOL_DEFINITIONS)}")
    adapter = GeminiPlatformAdapter(workspace=Path(ws), home=Path(ws))
    rules = adapter.get_source_rules()
    skills = adapter.get_source_skills()
    if len(rules) < SOURCE_RULE_FILES:
        fail(f"GeminiPlatformAdapter.get_source_rules() found only {len(rules)} rules in wheel: {rules!r}")
    if len(skills) < 15:
        fail(f"GeminiPlatformAdapter.get_source_skills() found only {len(skills)} skills in wheel: {skills!r}")
    print(f"ok  packaged platform adapter ({len(rules)} rules, {len(skills)} skills, 4 MCP tools)")


def main():
    if os.environ.get("PYTHONPATH"):
        fail("PYTHONPATH must be unset for a source-hidden smoke test")
    if not sys.flags.isolated:
        fail("run with python -I so the current directory cannot shadow site-packages")
    check_module_origins()
    ws = make_workspace()
    check_cli()
    check_mcp(ws)
    check_governance_fitness(ws)
    check_full_rule_preset(ws)
    check_packaged_skills_and_platform_adapter(ws)
    print("wheel smoke passed")


if __name__ == "__main__":
    main()

