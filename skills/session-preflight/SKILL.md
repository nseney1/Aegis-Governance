---
name: Session Pre-flight Probe
description: Probes environment health at session start, catching venv drift, git status, and broken tests.
---
# Session Pre-flight Probe

> **Role**: Eliminate environment-class waste (VIRTUALENV_DRIFT, ENV_BLINDNESS, DIRTY_VCS_STAGING) by probing project health before writing any code.

## When to Activate

Activate at **session start** when the workspace contains any of:
- `venv/`, `.venv/`, or `env/` (Python virtual environment)
- `requirements.txt`, `pyproject.toml`, `setup.py` (Python project)
- `package.json` (Node project)
- `Makefile` with test/lint targets
- `.git/` directory
- Imports of `pyautogui`, `xdotool`, `pygame` (GUI automation)

## Execution Protocol

### Step 1: Detect Project Type

Run a quick scan of workspace root:
```bash
ls -1 venv/ .venv/ env/ 2>/dev/null | head -1          # Python venv
ls package.json 2>/dev/null                              # Node
grep -l 'pyautogui\|xdotool\|pygame' *.py **/*.py 2>/dev/null  # GUI automation
```

### Step 2: Dispatch Flash Preflight Subagent

Dispatch a **Flash** read-only research subagent with the appropriate checklist below. The subagent must NOT modify any files.

#### Python Project Checklist

```
Execute these checks and report findings as a structured checklist:

1. VENV HEALTH
   - Run: head -1 ./venv/bin/pip (or .venv/bin/pip)
   - Run: cat ./venv/pyvenv.cfg | grep -E "home|command"
   - PASS if shebang and pyvenv.cfg paths match $PWD
   - FAIL if they point to a different directory (stale venv)

2. TEST SUITE
   - Check if any of these exist: Makefile (with test target), pytest.ini, 
     setup.cfg [tool:pytest], pyproject.toml [tool.pytest]
   - If found, run: make test (or pytest --co -q) to verify tests collect
   - Report: test runner command, number of tests, pass/fail
   - If no test suite found, report: "No test suite detected"

3. GIT STATE
   - Run: git status --porcelain | wc -l
   - Run: git log --oneline -3
   - PASS if clean or <5 uncommitted files
   - WARN if >5 uncommitted files or untracked data directories

4. GITIGNORE COVERAGE
   - Run: git ls-files --others --ignored --exclude-standard | wc -l
   - Check .gitignore covers: venv/, __pycache__/, *.pt, *.pth, data/, 
     models/, *.egg-info/, .env
   - WARN if data/ or models/ directories exist but aren't gitignored

5. DEPENDENCY HEALTH
   - Run: ./venv/bin/pip check 2>&1 | head -10
   - PASS if "No broken requirements found"
   - WARN if any dependency conflicts reported
```

#### GUI/Automation Addendum (append to Python checklist)

```
6. DISPLAY ENVIRONMENT
   - Run: echo $DISPLAY
   - Run: xdpyinfo 2>&1 | head -5 (or xrandr --query)
   - PASS if DISPLAY is set and X11 responds
   - FAIL if DISPLAY unset or Xlib errors

7. AUTOMATION LIBRARIES
   - Run: ./venv/bin/python -c "import pyautogui; print(pyautogui.size())"
   - Check for coordinate calibration files (config.py, hud_reader.py constants)
   - WARN if no calibration data found for screen automation
```

#### Node Project Checklist

```
1. Run: node --version && npm --version
2. Run: npm ls --depth=0 2>&1 | tail -5
3. Check: package.json has "test" script
4. Run: npm test --dry-run (or npm test if fast)
5. Git state: same as Python checklist items 3-4
```

### Step 3: Process Results

When the preflight subagent reports back:

- **All PASS**: Proceed with deliverable work. Log: "✅ Preflight clean"
- **Any WARN**: Note warnings but proceed. Inject a brief reminder in your working context.
- **Any FAIL**: **Fix before writing code**. Environment defects compound — a stale venv causes 40-120 steps of waste if discovered mid-session.

## Cost Budget

| Component | Tokens | Time |
|:----------|:------:|:----:|
| Flash subagent | ~500 | ~5s |
| Shell commands (5-7) | ~200 | ~3s |
| Result processing | ~100 | ~1s |
| **Total** | **~800** | **<10s** |

## Anti-Patterns

- **Don't skip preflight for "quick fixes"** — the 5dd84eed session started as a "quick git setup" and burned 58 steps on venv drift
- **Don't use inherit/pro for preflight** — Flash is sufficient for read-only diagnostics
- **Don't let preflight modify files** — it's a read-only probe; fixes are the orchestrator's job
- **Don't run preflight on non-coding tasks** — governance, documentation, and research sessions don't need it
