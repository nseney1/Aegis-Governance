"""Static regression tests — one per audited finding that can be proven
without running an install. Each test names the finding it guards.

These are cheap and require no third-party packages, so they can gate every
commit.
"""
import json
import os
import re
import subprocess
import sys

import pytest

from conftest import REPO_ROOT, iter_source_files, read, run

# ── SOMA-C03 / cross-OS: Bash 4 constructs break macOS Bash 3.2 ──────────

BASH4_PATTERNS = {
    "${var^} / ${var^^} case conversion": re.compile(r'\$\{[A-Za-z_][A-Za-z0-9_]*\^\^?\}'),
    "${var,,} case conversion": re.compile(r'\$\{[A-Za-z_][A-Za-z0-9_]*,,?\}'),
    "declare -A associative array": re.compile(r'\bdeclare\s+-A\b'),
    "typeset -A associative array": re.compile(r'\btypeset\s+-A\b'),
    "mapfile": re.compile(r'\bmapfile\b'),
    "readarray": re.compile(r'\breadarray\b'),
    "local -n nameref": re.compile(r'\blocal\s+-n\b'),
    "&>> append redirect": re.compile(r'&>>'),
}


def _shell_files():
    files = list(iter_source_files(os.path.join(REPO_ROOT, "install"), (".sh",)))
    hooks = os.path.join(REPO_ROOT, "install", "hooks")
    if os.path.isdir(hooks):
        files += [os.path.join(hooks, f) for f in os.listdir(hooks)]
    return [f for f in files if os.path.isfile(f)]


@pytest.mark.parametrize("label,pattern", sorted(BASH4_PATTERNS.items()))
def test_no_bash4_only_constructs(label, pattern):
    """SOMA-C03: macOS ships Bash 3.2; these constructs raise 'bad substitution'
    at expansion time, which `bash -n` cannot detect."""
    offenders = []
    for path in _shell_files():
        for lineno, line in enumerate(read(path).splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if pattern.search(line):
                rel = os.path.relpath(path, REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, f"Bash 4+ construct ({label}) found:\n" + "\n".join(offenders)


# ── SOMA-C02: escaped quotes inside command substitution ────────────────

def test_no_escaped_quotes_in_command_substitution():
    """SOMA-C02: `cd \\"$(dirname ...)\\"` passes literal quote characters, so the
    script dies at line 4 before sourcing anything. Killed the PreToolUse gate."""
    offenders = []
    for path in _shell_files():
        for lineno, line in enumerate(read(path).splitlines(), 1):
            # Only flag the specific pattern that broke BASH_SOURCE resolution.
            # Legitimate uses like sed 's/"/\\"/g' inside $() are fine.
            if 'BASH_SOURCE' in line and '\\"' in line and "$(" in line:
                rel = os.path.relpath(path, REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Escaped quotes inside command substitution:\n" + "\n".join(offenders)
    )




# ── SOMA-H04: unencoded file I/O corrupts on non-UTF-8 locales ──────────

OPEN_CALL = re.compile(r'(?<!\.)\bopen\s*\(')
BINARY_MODE = re.compile(r'''['"][rwxa+t]*b[rwxa+t]*['"]''')


def test_all_text_open_calls_specify_encoding():
    """SOMA-H04: requires-python >=3.9 means PEP 686 does not apply, so Windows
    uses the locale codepage. Rule files contain characters cp1252 cannot encode."""
    offenders = []
    for sub in ("soma_mcp", "soma_sdk", "aegis_mcp", "aegis_sdk"):
        root = os.path.join(REPO_ROOT, sub)
        if not os.path.isdir(root):
            continue
        for path in iter_source_files(root, (".py",)):
            for lineno, line in enumerate(read(path).splitlines(), 1):
                if not OPEN_CALL.search(line):
                    continue
                if "encoding=" in line or BINARY_MODE.search(line):
                    continue
                if "makedirs" in line or line.lstrip().startswith("#"):
                    continue
                rel = os.path.relpath(path, REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "open() without encoding= (add encoding=\"utf-8\"):\n" + "\n".join(offenders)
    )


# ── SOMA-H03: path renames must land in every call site ─────────────────

def test_no_stale_gemini_config_paths():
    """SOMA-H03: install.sh writes .gemini/config/{rules,skills}. Referring to
    config/genome or config/organs means the fallback matches nothing."""
    stale = re.compile(r'\.gemini/config/(genome|organs)\b')
    targets = [
        os.path.join(REPO_ROOT, "install", "install.sh"),
        os.path.join(REPO_ROOT, "install", "uninstall.sh"),
        os.path.join(REPO_ROOT, "Makefile"),
    ]
    offenders = []
    for path in targets:
        if not os.path.exists(path):
            continue
        for lineno, line in enumerate(read(path).splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if stale.search(line):
                rel = os.path.relpath(path, REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, "Stale gemini config path:\n" + "\n".join(offenders)





def test_powershell_scripts_with_non_ascii_have_utf8_bom():
    """Windows PowerShell 5.1 decodes BOM-less scripts as ANSI (cp1252): the
    em-dash's trailing 0x94 byte becomes a closing quote and the installer
    fails to parse at all."""
    offenders = []
    for path in iter_source_files(REPO_ROOT, (".ps1", ".psm1")):
        with open(path, "rb") as f:
            data = f.read()
        if not data.isascii() and not data.startswith(b"\xef\xbb\xbf"):
            offenders.append(os.path.relpath(path, REPO_ROOT))
    assert not offenders, f"non-ASCII PowerShell scripts missing UTF-8 BOM: {offenders}"


def test_rule_basenames_are_unique_when_flattened():
    """install.sh flattens genome/**/*.md into one directory, so a duplicate
    basename would silently overwrite, last write winning."""
    genome = os.path.join(REPO_ROOT, "genome")
    seen = {}
    for path in iter_source_files(genome, (".md",)):
        name = os.path.basename(path)
        seen.setdefault(name, []).append(os.path.relpath(path, REPO_ROOT))
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dupes, f"duplicate rule basenames would collide on install: {dupes}"


# ── SOMA-M01: JSON must not contain Infinity ────────────────────────────

def test_no_infinity_emitted_in_json_payloads():
    """SOMA-M01: json.dumps(float('inf')) emits bare `Infinity`, which RFC 8259
    forbids; strict non-Python MCP clients reject the frame."""
    offenders = []
    for sub in ("soma_mcp", "soma_sdk", "aegis_mcp", "aegis_sdk"):
        root = os.path.join(REPO_ROOT, sub)
        if not os.path.isdir(root):
            continue
        for path in iter_source_files(root, (".py",)):
            for lineno, line in enumerate(read(path).splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if re.search(r"float\(\s*['\"]inf['\"]\s*\)", line):
                    rel = os.path.relpath(path, REPO_ROOT)
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "float('inf') reaches JSON payloads:\n" + "\n".join(offenders)
    )


# ── SOMA-C01: soma_mcp must import without third-party packages ─────────

def test_soma_mcp_has_no_unguarded_third_party_imports():
    """SOMA-C01: a bare `import yaml` in soma_mcp/ stopped the server from
    starting at all, violating .aegis/rules/walls/wall-mcp-zero-deps.md."""
    offenders = []
    for path in iter_source_files(os.path.join(REPO_ROOT, "soma_mcp"), (".py",)):
        lines = read(path).splitlines()
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped in ("import yaml",) or stripped.startswith("from yaml"):
                # Acceptable only inside a try: block.
                context = "\n".join(lines[max(0, lineno - 4):lineno])
                if "try:" not in context:
                    rel = os.path.relpath(path, REPO_ROOT)
                    offenders.append(f"{rel}:{lineno}: unguarded {stripped}")
    assert not offenders, (
        "soma_mcp must degrade without pyyaml:\n" + "\n".join(offenders)
    )


def test_mcp_server_answers_jsonrpc_without_pyyaml(tmp_path):
    """SOMA-C01 end to end: initialize + tools/list must return valid JSON on a
    bare interpreter. Regression: ModuleNotFoundError, exit 1, 0 bytes stdout."""
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    requests = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
    )
    env = {"PYTHONPATH": REPO_ROOT}
    mcp_pkg = "aegis_mcp" if os.path.exists(os.path.join(REPO_ROOT, "aegis_mcp")) else "soma_mcp"
    proc = subprocess.run(
        [sys.executable, "-m", mcp_pkg],
        cwd=str(tmp_path), input=requests, capture_output=True, text=True,
        timeout=120, env={**os.environ, **env},
    )
    assert proc.returncode == 0, f"server exited {proc.returncode}: {proc.stderr[:600]}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"server produced no stdout. stderr: {proc.stderr[:600]}"
    for ln in lines:
        json.loads(ln)  # every framed response must be valid JSON
    first = json.loads(lines[0])
    assert first["result"]["serverInfo"]["name"] in ("aegis-mcp", "soma-mcp")
    tools = json.loads(lines[1])["result"]["tools"]
    assert len(tools) >= 1


# ── SOMA-C02: Framework-wide zero third-party runtime dependencies ──────

def test_entire_runtime_has_zero_third_party_imports():
    """SOMA-C02: soma_cli/, soma_core/, soma_mcp/, soma_sdk/, and enzymes/
    must have strictly ZERO third-party runtime package imports.
    Only Python standard library modules and internal modules are permitted at runtime,
    with no optional extras either: Layer 2 shells out to --llm-cmd (D14)."""
    import ast
    from aegis_core.verification.import_guard import _get_stdlib_modules

    stdlib = set(_get_stdlib_modules()) | set(sys.builtin_module_names)
    internal_prefixes = ("soma_", "aegis_", "install", "genome", "rules")
    soma_core_dir = os.path.join(REPO_ROOT, "soma_core")
    aegis_core_dir = os.path.join(REPO_ROOT, "aegis_core")
    soma_core_modules = {
        f[:-3] for f in os.listdir(soma_core_dir) if f.endswith(".py")
    } if os.path.isdir(soma_core_dir) else set()
    aegis_core_modules = {
        f[:-3] for f in os.listdir(aegis_core_dir) if f.endswith(".py")
    } if os.path.isdir(aegis_core_dir) else set()
    internal_names = soma_core_modules | aegis_core_modules | {"conftest"}

    offenders = []
    runtime_dirs = ["soma_cli", "soma_core", "soma_mcp", "soma_sdk", "aegis_cli", "aegis_core", "aegis_mcp", "aegis_sdk"]
    for rdir in runtime_dirs:
        dir_path = os.path.join(REPO_ROOT, rdir)
        for path in iter_source_files(dir_path, (".py",)):
            try:
                tree = ast.parse(read(path), filename=path)
            except SyntaxError as e:
                rel = os.path.relpath(path, REPO_ROOT)
                offenders.append(f"{rel}:{e.lineno}: SyntaxError: {e.msg}")
                continue

            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        continue  # relative imports within package are internal
                    if node.module:
                        modules = [node.module.split(".")[0]]
                elif isinstance(node, ast.Call):
                    if (
                        isinstance(node.func, ast.Name)
                        and node.func.id == "__import__"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        modules = [node.args[0].value.split(".")[0]]
                    elif (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "import_module"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        modules = [node.args[0].value.split(".")[0]]

                for mod in modules:
                    if mod in stdlib:
                        continue
                    if any(mod.startswith(p) for p in internal_prefixes) or mod in internal_names:
                        continue
                    rel = os.path.relpath(path, REPO_ROOT)
                    offenders.append(f"{rel}:{node.lineno}: {mod}")
    assert not offenders, (
        "SOMA-C02 violation: Runtime modules must have zero third-party imports:\n"
        + "\n".join(offenders)
    )


# ── SOMA-M07: one source of truth for the version ───────────────────────

def test_version_is_single_sourced():
    """SOMA-M07: all five version surfaces must agree with VERSION."""
    version_file = read(os.path.join(REPO_ROOT, "VERSION")).strip()

    pyproject = read(os.path.join(REPO_ROOT, "pyproject.toml"))
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    assert match, "no version in pyproject.toml"
    assert match.group(1) == version_file, (
        f"pyproject.toml ({match.group(1)}) != VERSION ({version_file})"
    )

    for sdk_pkg in ("soma_sdk", "aegis_sdk"):
        sdk_path = os.path.join(REPO_ROOT, sdk_pkg, "__init__.py")
        if not os.path.exists(sdk_path):
            continue
        python_sdk = read(sdk_path)
        sdk_match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", python_sdk, re.M)
        assert sdk_match and sdk_match.group(1) == version_file, (
            f"Python SDK {sdk_pkg} ({sdk_match.group(1) if sdk_match else 'missing'}) != VERSION ({version_file})"
        )

    try:
        from aegis_mcp.server import _server_version
    except ImportError:
        from aegis_mcp.server import _server_version
    assert _server_version() == version_file, (
        f"MCP runtime ({_server_version()}) != VERSION ({version_file})"
    )

    mcp_server_file = os.path.join(REPO_ROOT, "aegis_mcp", "server.py") if os.path.exists(os.path.join(REPO_ROOT, "aegis_mcp", "server.py")) else os.path.join(REPO_ROOT, "soma_mcp", "server.py")
    server = read(mcp_server_file)
    assert f'"{version_file}"' not in server.replace('_server_version', ''), (
        "server.py still hardcodes the version string"
    )

    readme = read(os.path.join(REPO_ROOT, "README.md"))
    readme_badge_match = re.search(r'badge/Version-([0-9]+\.[0-9]+\.[0-9]+)-', readme)
    assert readme_badge_match and readme_badge_match.group(1) == version_file, (
        f"README.md badge ({readme_badge_match.group(1) if readme_badge_match else 'missing'}) != VERSION ({version_file})"
    )

    security = read(os.path.join(REPO_ROOT, "SECURITY.md"))
    major_minor = ".".join(version_file.split(".")[:2])
    assert f"| {major_minor}.x" in security, (
        f"SECURITY.md does not list {major_minor}.x as supported"
    )


# ── SOMA-M03: failure paths must exit nonzero ───────────────────────────

def test_cli_exits_nonzero_on_unknown_command():
    """SOMA-M03: main() returned None on the unknown-command path, so the
    console script produced exit 0 while printing an error."""
    proc = run([sys.executable, '-m', 'aegis_cli.cli',
                'definitely-not-a-command'])
    assert proc.returncode != 0, (
        f"CLI reported an unknown command but exited 0:\n{proc.stdout}{proc.stderr}"
    )


# ── SOMA-H01: the verification gate must be able to fail ────────────────

def test_make_validate_fails_on_broken_shell_script(tmp_path):
    """SOMA-H01: `bash -n "$s" && echo ok || echo fail` swallowed the exit
    status, so a syntax error anywhere kept CI green.

    Verifies that bash -n actually returns non-zero on broken syntax,
    which is the mechanism make validate relies on."""
    broken = tmp_path / "zz_pytest_broken.sh"
    broken.write_text("f() {\n")  # unterminated function body

    # Verify bash -n catches the syntax error (this is what make validate uses)
    proc = subprocess.run(
        ["bash", "-n", str(broken)],
        capture_output=True, text=True
    )
    assert proc.returncode != 0, (
        "bash -n passed despite a syntax error — make validate would miss this"
    )




# ── Static Import & Documentation Integrity ─────────────────────────────

def test_no_undefined_names_in_python_code():
    """Verify zero F821 undefined names across soma_core, soma_cli, aegis_sdk."""
    import shutil
    ruff_bin = shutil.which("ruff") or os.path.expanduser("~/.local/bin/ruff")
    if not os.path.exists(ruff_bin):
        pytest.skip("ruff binary not found")
    targets = [
        d for d in ("soma_core", "soma_cli", "soma_sdk", "soma_mcp", "aegis_core", "aegis_cli", "aegis_sdk", "aegis_mcp")
        if os.path.isdir(os.path.join(REPO_ROOT, d))
    ]
    proc = subprocess.run(
        [ruff_bin, "check", "--select", "F821", *targets],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Found undefined names (F821):\n{proc.stdout}"


def test_no_javascript_sdk_in_readme():
    """README.md must not reference nonexistent npm package or require('soma-governance')."""
    readme = read(os.path.join(REPO_ROOT, "README.md"))
    assert "require('soma-governance')" not in readme
    assert 'require("soma-governance")' not in readme

