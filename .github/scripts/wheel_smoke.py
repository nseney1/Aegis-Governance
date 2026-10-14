"""Smoke-test an installed Soma distribution with the source checkout hidden.

Run with an interpreter that has the built wheel (or sdist) installed, from a
directory OUTSIDE the repository, in isolated mode so neither PYTHONPATH nor
the current directory can shadow site-packages:

    cd "$(mktemp -d)" && python -I /path/to/wheel_smoke.py

Fails (non-zero exit) if any Soma module resolves from outside site-packages,
or if the CLI, the MCP server, or Governance SDK do not work.
"""
import importlib
import json
import os
import subprocess
import sys
import sysconfig
import tempfile

PACKAGES = ("aegis_cli", "aegis_sdk", "aegis_core", "aegis_mcp")


def fail(msg):
    print(f"wheel smoke FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def check_module_origins():
    roots = {os.path.realpath(sysconfig.get_paths()[k]) for k in ("purelib", "platlib")}
    for name in PACKAGES:
        mod = importlib.import_module(name)
        origin = os.path.realpath(getattr(mod, "__file__", "") or "")
        if not any(origin.startswith(r + os.sep) for r in roots):
            fail(f"{name} imported from {origin!r}, not from site-packages {sorted(roots)}")
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
    proc = subprocess.run([sys.executable, "-I", "-m", "aegis_cli.cli", "--help"],
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
    proc = subprocess.run([sys.executable, "-I", "-m", "aegis_mcp"], input=requests,
                          capture_output=True, text=True, timeout=60, cwd=ws, env=env)
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != 3:
        fail(f"MCP returned {len(lines)} responses: {proc.stdout[-500:]} {proc.stderr[-500:]}")
    if not lines[1]["result"]["tools"]:
        fail("MCP tools/list is empty")
    rules = json.loads(lines[2]["result"]["content"][0]["text"])
    if "trap-smoke" not in {c.get("_name") for c in rules}:
        fail(f"MCP aegis_list_rules did not see the workspace rule: {rules!r}")
    print("ok  aegis_mcp initialize / tools/list / aegis_list_rules")


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
    if len(installed) < 10 or len(files) != len(installed):
        fail(f"full rule preset is incomplete: installed={installed!r}, files={files!r}")
    print(f"ok  packaged full rule preset ({len(installed)} rules)")


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
    print("wheel smoke passed")


if __name__ == "__main__":
    main()
