"""Cross-file documentation accuracy checks for release-critical contracts."""
import ast
import json
import re
from pathlib import Path

from conftest import REPO_ROOT, read

ROOT = Path(REPO_ROOT)


def _literal_assignment(path, name):
    targets = [path]
    if path.parent.name.startswith("soma_"):
        canonical = ROOT / ("aegis_" + path.parent.name[5:]) / path.name
        if canonical.exists():
            targets.append(canonical)
    for p in targets:
        tree = ast.parse(read(str(p)))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                continue
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "frozenset":
                value = value.args[0]
            return set(ast.literal_eval(value))
    raise AssertionError(f"{name} not found in {path.relative_to(ROOT)}")


def _readme_mcp_row(readme, label):
    section = readme.split("### MCP Server (Recommended)", 1)[1].split("### SDK", 1)[0]
    row = next(line for line in section.splitlines() if line.startswith(f"| {label}"))
    return set(re.findall(r"`(soma_[a-z_]+)`", row))


def _script_groups():
    return {
        "Lifecycle Scripts (Hooks)": {ROOT / "install" / "hooks" / "pre-commit"},
        "Verification Scripts": {
            path for path in (ROOT / "soma_core" / "verification").iterdir()
            if path.is_file() and path.suffix == ".py" and path.name != "__init__.py"
        },
        "CLI Commands": {ROOT / "soma"} | {
            path for path in (ROOT / "soma_cli").iterdir()
            if path.is_file() and path.suffix == ".py"
            and path.name not in {"__init__.py", "__main__.py"}
        },
        "SDK Modules": {
            path for path in (ROOT / "soma_sdk").iterdir()
            if path.is_file() and path.suffix == ".py" and path.name != "__init__.py"
        },
        "MCP and Core Modules": {
            path for directory in (ROOT / "soma_mcp", ROOT / "soma_core")
            for path in directory.iterdir()
            if path.is_file() and path.suffix == ".py"
            and path.name not in {"__init__.py", "__main__.py", "compat.py"}
        },
    }


def _tool_definition_names(path):
    targets = [path]
    if path.name == "tools.py":
        targets.insert(0, path.parent / "registry.py")
    if path.parent.name.startswith("soma_"):
        canonical_dir = ROOT / ("aegis_" + path.parent.name[5:])
        if (canonical_dir / "tools.py").exists():
            targets.append(canonical_dir / "tools.py")
        if (canonical_dir / "registry.py").exists():
            targets.append(canonical_dir / "registry.py")
    for p in targets:
        if not p.exists():
            continue
        tree = ast.parse(read(str(p)))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "TOOL_DEFINITIONS"
                       for target in node.targets):
                continue
            definitions = ast.literal_eval(node.value)
            return {definition["name"] for definition in definitions}
    raise AssertionError("TOOL_DEFINITIONS not found")


def test_readme_mcp_tool_inventory_matches_code():
    readme = read(str(ROOT / "README.md"))
    section = readme.split("### MCP Server (Recommended)", 1)[1].split("### SDK", 1)[0]
    documented = set(re.findall(r"`(soma_[a-z_]+)`", section))
    expected = _tool_definition_names(ROOT / "soma_mcp" / "tools.py")
    assert documented == expected
    assert len(expected) == 20


def test_readme_mcp_tiers_match_server_definitions():
    readme = read(str(ROOT / "README.md"))
    source = ROOT / "soma_mcp" / "server.py"
    expected = {
        "Read (default)": _literal_assignment(source, "_READ_TOOLS"),
        "Write (default; receipt required)": _literal_assignment(source, "_WRITE_TOOLS"),
        "Execute (opt-in; receipt required)": _literal_assignment(source, "_EXECUTE_TOOLS"),
    }
    documented = {label: _readme_mcp_row(readme, label) for label in expected}
    assert documented == expected
    assert len(set().union(*documented.values())) == 20


def test_documentation_index_local_links_exist():
    index = ROOT / "docs" / "index.md"
    missing = []
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", read(str(index))):
        if "://" in target or target.startswith("#"):
            continue
        relative = target.split("#", 1)[0]
        if relative and not (index.parent / relative).resolve().exists():
            missing.append(target)
    assert not missing, f"docs/index.md has missing local links: {missing}"


def test_windows_issue_sections_match_bug_registry():
    version = read(str(ROOT / "VERSION")).strip()
    registry = json.loads(read(str(ROOT / "docs" / "project" / "BUG_REGISTRY.json")))
    bugs = {bug["id"]: bug for bug in registry["bugs"]}
    windows = read(str(ROOT / "docs" / "KNOWN_ISSUES_WINDOWS.md"))
    assert windows.startswith(f"# Known Issues — Windows (v{version})")
    fixed, open_issues = windows.split("## Open issues", 1)
    for bug_id in ("BUG-008", "BUG-009", "BUG-011", "BUG-014", "BUG-032"):
        assert bugs[bug_id]["fixed_in"] in (f"v{version}", "v0.93.0", "v0.89.0")
        assert f"### {bug_id}:" in fixed
        assert f"### {bug_id}:" not in open_issues
    for bug_id in ("BUG-010", "BUG-012", "BUG-013", "BUG-035", "BUG-036", "BUG-038", "BUG-037", "BUG-086", "BUG-087"):
        assert bugs[bug_id]["status"] == "fixed"
        assert f"### {bug_id}:" in fixed
        assert f"### {bug_id}:" not in open_issues
    assert "### BUG-" not in open_issues


def test_scripts_reference_counts_match_unique_source_paths():
    groups = _script_groups()
    flattened = [path for paths in groups.values() for path in paths]
    assert all(path.exists() for path in flattened)
    assert len(flattened) == len(set(flattened)), "script categories overlap"

    reference = read(str(ROOT / "docs" / "architecture" / "scripts.md"))
    for label, paths in groups.items():
        match = re.search(rf"\[{re.escape(label)}[^]]*\][^\n]*\|\s*(\d+)\s*\|", reference)
        assert match, f"summary row missing for {label}"
        assert int(match.group(1)) == len(paths), label

    total = re.search(r"\| \*\*Total\*\* \| \| \*\*(\d+)\*\* \|", reference)
    assert total
    assert int(total.group(1)) == len(flattened)


def test_readme_core_rule_count_and_inventory_match_genome():
    rules = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "genome").rglob("*.md")
        if path.name not in {"META.md", "README.md"}
    }
    readme = read(str(ROOT / "README.md"))
    assert f"Core_Rules-{len(rules)}-" in readme
    section = readme.split("## 📐 Core Rules", 1)[1].split("## 🔧 Agent Skills", 1)[0]
    linked = {target for target in re.findall(r"\]\((genome/[^)]+\.md)\)", section)}
    assert linked == rules


def test_readme_m8ven_trust_badge_exists():
    readme = read(str(ROOT / "README.md"))
    expected_markdown = r"\[\!\[M8ven Score\]\(https://m8ven\.ai/badge/mcp/nseney1-soma-governance-yv4xbk\)\]\(https://m8ven\.ai/mcp/nseney1/soma-governance\?s=readme\)"
    assert re.search(expected_markdown, readme), "m8ven badge missing or malformed in README"


def test_readme_claims_registry_verification():
    """Ensure all claims in docs/project/CLAIM_REGISTRY.json are verified during local pytest."""
    from soma_core.enforcement import verify_readme_claims
    ok, failures = verify_readme_claims(str(ROOT))
    assert ok, f"README claims verification failed: {failures}"

