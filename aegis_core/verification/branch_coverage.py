"""Branch coverage verification tool.

Wraps pytest branch coverage to detect uncovered branches in target files.
Falls back to stdlib trace module when pytest-cov/coverage are unavailable.
"""
import json
import os
import subprocess
import sys
import tempfile
from typing import Optional

from . import ToolEvidence


def check(
    target_file: str,
    test_file: str,
    target_lines: Optional[set[int]] = None,
) -> ToolEvidence:
    """Run branch coverage analysis on target_file using test_file.

    Args:
        target_file: Path to the source file to check coverage for.
        test_file: Path to the test file to run.
        target_lines: Optional set of specific line numbers to check coverage for (e.g. diff).

    Returns:
        ToolEvidence with verdict=True if all branches covered, False otherwise.
        result.lines contains specific uncovered line numbers.
    """
    target_file = os.path.abspath(target_file)
    test_file = os.path.abspath(test_file)
    target_dir = os.path.dirname(target_file)
    target_basename = os.path.basename(target_file)

    with tempfile.TemporaryDirectory() as tmpdir:
        json_report = os.path.join(tmpdir, "coverage.json")

        # Try pytest-cov first
        generated = _try_pytest_cov(test_file, target_dir, json_report)

        # Fall back to coverage module
        if not generated:
            generated = _try_coverage_module(
                test_file, target_dir, json_report, tmpdir
            )

        # Fall back to stdlib trace
        if not generated:
            missing_lines = _run_trace_fallback(
                test_file, target_file, target_dir, tmpdir
            )
        else:
            missing_lines = _parse_coverage(
                json_report, target_file, target_basename
            )

    # None means the trace script crashed — fail closed
    if missing_lines is None:
        missing_lines = [-1]

    # Filter by target_lines if restricted scope was provided
    if target_lines is not None and missing_lines != [-1]:
        missing_lines = [l for l in missing_lines if l in target_lines]

    verdict = len(missing_lines) == 0
    detail = (
        "All branches covered"
        if verdict
        else f"Uncovered lines: {missing_lines}"
    )

    return ToolEvidence(
        tool="branch_coverage",
        target=target_file,
        verdict=verdict,
        detail=detail,
        lines=sorted(missing_lines),
    )


def _try_pytest_cov(test_file, target_dir, json_report):
    """Attempt pytest-cov. Returns True if JSON report was generated."""
    from aegis_core.verification.test_runner import resolve_pytest_cmd

    pytest_cmd = resolve_pytest_cmd()
    if not pytest_cmd:
        return False
    try:
        subprocess.run(
            pytest_cmd + [
                test_file,
                f"--cov={target_dir}",
                "--cov-branch",
                f"--cov-report=json:{json_report}",
                "--no-header", "-q",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False
    return os.path.exists(json_report)


def _try_coverage_module(test_file, target_dir, json_report, tmpdir):
    """Attempt coverage module. Returns True if JSON report was generated."""
    from aegis_core.verification.test_runner import resolve_pytest_python
    py_exec = resolve_pytest_python(target_dir)
    data_file = os.path.join(tmpdir, "coverage.data")
    try:
        subprocess.run(
            [
                py_exec, "-m", "coverage", "run",
                "--branch",
                f"--source={target_dir}",
                f"--data-file={data_file}",
                "-m", "pytest", test_file, "-q",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False
    try:
        subprocess.run(
            [
                py_exec, "-m", "coverage", "json",
                f"--data-file={data_file}",
                "-o", json_report,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False
    return os.path.exists(json_report)


def _run_trace_fallback(test_file, target_file, target_dir, tmpdir):  # pragma: no cover
    """Use stdlib trace module via subprocess to find uncovered lines."""
    from aegis_core.verification.test_runner import resolve_pytest_python
    py_exec = resolve_pytest_python(target_dir)
    # Build a helper script that uses trace to run pytest and report coverage
    trace_script = os.path.join(tmpdir, "_trace_runner.py")
    results_file = os.path.join(tmpdir, "trace_results.json")

    with open(trace_script, "w") as f:
        f.write(
            _TRACE_SCRIPT_TEMPLATE.format(
                test_file_repr=repr(test_file),
                target_file_repr=repr(target_file),
                target_dir_repr=repr(target_dir),
                results_file_repr=repr(results_file),
            )
        )

    try:
        subprocess.run(
            [py_exec, trace_script],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return None

    if not os.path.exists(results_file):
        return None

    with open(results_file, encoding='utf-8', errors='replace') as f:
        return json.load(f)


_TRACE_SCRIPT_TEMPLATE = '''\
"""Trace runner: executes pytest under trace and reports uncovered lines."""
import dis
import json
import os
import sys
import trace

# Run pytest with tracing
tracer = trace.Trace(count=True, trace=False, countfuncs=False, countcallers=False)
sys.argv = ["pytest", {test_file_repr}, "-q", "--no-header", "--tb=no"]
tracer.runfunc(
    __import__("pytest").main,
    [{test_file_repr}, "-q", "--no-header", "--tb=no"],
)

target_file = {target_file_repr}
results_file = {results_file_repr}

# Get counts: dict of (filename, lineno) -> count
counts = tracer.results().counts

# Determine which lines of the target were executed
executed_lines = set()
for (fname, lineno), count in counts.items():
    if count > 0 and os.path.abspath(fname) == target_file:
        executed_lines.add(lineno)

# Determine all executable lines in the target file.
# Disassembly via dis.findlinestarts precisely identifies executable bytecode
# statements while ignoring comments, multiline docstrings, and bare structural keywords.
all_lines = set()
try:
    with open(target_file, encoding='utf-8', errors='replace') as f:
        src = f.read()
    co = compile(src, target_file, "exec")
    def _extract_linestarts(code_obj):
        for offset, lineno in dis.findlinestarts(code_obj):
            if lineno > 0:
                all_lines.add(lineno)
        for const in code_obj.co_consts:
            if hasattr(const, "co_code"):
                _extract_linestarts(const)
    _extract_linestarts(co)
except Exception:
    all_lines = set()

# Fallback to source-line heuristic with multiline docstring state tracking
if not all_lines:
    in_triple_double = False
    in_triple_single = False
    with open(target_file, encoding='utf-8', errors='replace') as f:
        for i, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            if stripped.startswith("@"):
                continue

            # Handle triple-quote boundaries
            if not in_triple_single:
                if in_triple_double:
                    if '"""' in stripped:
                        in_triple_double = False
                    continue
                elif stripped.startswith('"""') or stripped.startswith('r"""') or stripped.startswith('f"""'):
                    content_after = stripped[stripped.find('"""') + 3:]
                    if '"""' not in content_after:
                        in_triple_double = True
                    continue

            if not in_triple_double:
                if in_triple_single:
                    if "\\'\\'\\'" in stripped:
                        in_triple_single = False
                    continue
                elif stripped.startswith("\\'\\'\\'") or stripped.startswith("r\\'\\'\\'") or stripped.startswith("f\\'\\'\\'"):
                    content_after = stripped[stripped.find("\\'\\'\\'") + 3:]
                    if "\\'\\'\\'" not in content_after:
                        in_triple_single = True
                    continue

            # Exclude bare structural keywords and closing brackets
            if stripped in ("else:", "try:", "finally:", ")", "]", "}}", "):", "],", "}},", "),"):
                continue
            all_lines.add(i)

# Exclude lines marked with pragma: no cover or nocov, and if __name__ == '__main__' blocks
no_cover = set()
try:
    import ast
    with open(target_file, encoding='utf-8', errors='replace') as f:
        src_content = f.read()
    for idx, line in enumerate(src_content.splitlines(), 1):
        if "pragma: no cover" in line or "nocov" in line:
            no_cover.add(idx)
    tree = ast.parse(src_content)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            is_main_guard = False
            t = node.test
            if isinstance(t, ast.Compare):
                left_id = getattr(t.left, "id", None)
                if left_id == "__name__":
                    is_main_guard = True
            if is_main_guard:
                start = node.lineno
                end = getattr(node, "end_lineno", start)
                no_cover.update(range(start, end + 1))
except Exception:
    pass
all_lines = all_lines - no_cover

missing = sorted(all_lines - executed_lines)
with open(results_file, "w") as f:
    json.dump(missing, f)
'''



def _parse_coverage(json_report, target_file, target_basename):
    """Extract missing line numbers from JSON coverage report."""
    with open(json_report) as f:
        data = json.load(f)

    files = data.get("files", {})

    # Try exact path match first, then basename match
    file_data = files.get(target_file)
    actual_path = target_file
    if file_data is None:
        for filepath, fdata in files.items():
            if os.path.basename(filepath) == target_basename:
                file_data = fdata
                actual_path = filepath
                break

    if file_data is None:
        return [-1]

    src_lines = {}
    read_path = actual_path if os.path.isabs(actual_path) else os.path.abspath(actual_path)
    if not os.path.isfile(read_path):
        for root, _, fnames in os.walk("."):
            if target_basename in fnames:
                read_path = os.path.join(root, target_basename)
                break
    if os.path.isfile(read_path):
        try:
            with open(read_path, "r", encoding="utf-8", errors="replace") as sf:
                for lno, line in enumerate(sf, 1):
                    src_lines[lno] = line.strip()
        except Exception:
            pass

    jump_tokens = {"break", "continue", "pass"}
    missing = [l for l in file_data.get("missing_lines", []) if src_lines.get(l) not in jump_tokens]
    executed = set(file_data.get("executed_lines", []))
    # Also include branch-specific uncovered lines (filter out negative exits, loop continuations, executed statements, and bare jumps)
    for from_line, to_line in file_data.get("missing_branches", []):
        if to_line <= 0 or to_line <= from_line:
            continue
        if to_line in executed:
            continue
        if src_lines.get(to_line) in jump_tokens:
            continue
        if to_line not in missing:
            missing.append(to_line)
    return missing
