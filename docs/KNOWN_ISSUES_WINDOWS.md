# Known Issues — Windows (v3.3.0)

Open Windows issues as of v3.3.0 were observed on Windows 11 with Windows PowerShell 5.1, Git Bash, and Python 3.14. Each open issue is tracked in [`BUG_REGISTRY.json`](project/BUG_REGISTRY.json) with `"status": "open"`.

> **⚠ On v0.89.0, don't run the full test suite on a Windows machine you care about (BUG-010).** It can write to the real home directory. That includes `tests/test_install_lifecycle.py`, which `enzymes/verify_readme_claims.py` may invoke. Fixed after v0.89.0; see below.

CI now runs the full pytest suite on Windows (`test-windows` in `.github/workflows/validate.yml`, with an isolated `HOME`/`USERPROFILE`), so new Windows-only failures show up on every pull request.

## Impact summary

| Area | Status | Bug |
|---|---|---|
| `python -m soma_mcp` | Startup fixed in v0.89.0 | BUG-008 |
| MCP write/execute tools | Fixed in v0.89.0; request a state-bound receipt first | BUG-009 |
| MCP cell reads and receipts (`soma_scan`, `soma_list_cells`, `soma_request_receipt`) | Fixed in v0.90.0 | BUG-035 |
| `install.ps1` parsing and encoding under Windows PowerShell 5.1 | Fixed in v0.93.0 (explicit UTF-8 on all reads, BOM preserved) | BUG-011, BUG-014 |
| `install.ps1` lifecycle hooks under PowerShell 5.1 & 7 | Fixed in v0.93.0 (native Python hook runner `soma hook` / `soma_cli.hooks`) | BUG-032 |
| Hooks under Git Bash with a python.org install | Fixed after v0.89.0 (`soma_python.sh` resolver) | BUG-037 |
| `uninstall.sh` under Git Bash | Fixed in v0.90.0 | BUG-036 |
| Test suite on Windows | Fixed in v0.90.0 | BUG-010 |
| `soma status` on a cp1252 console | Fixed in v0.90.0 | BUG-012 |
| `soma_list_cells` / `Governance.list_cells` | Fixed in v0.89.0 (explicit UTF-8 inventory) | BUG-012 |
| Enzyme scripts on a cp1252 stdout | Fixed in v0.90.0 | BUG-038 |
| Windows-only tests | Fixed after v0.89.0 | BUG-013 |
| Rust AST driver / `soma doctor --fix` with a python.org install | Fixed in v1.4.0 (`python3` falls back to the running interpreter) | BUG-086 |
| Symlink tests without Developer Mode | Fixed in v1.4.0 (skip instead of WinError 1314) | BUG-087 |

## MCP server does not start: `python3` is the Windows Store stub

MCP configs written by Soma start the server with `"command": "python3"`, `"args": ["-m", "soma_mcp"]`. On many Windows machines `python3` on `PATH` is the Microsoft Store App Installer stub: it exits 49 (or prints a Microsoft Store message) instead of running Python, so the MCP host never gets a server and usually shows no useful error. The config keeps `python3` on purpose; run `soma doctor` (or `python -m soma_cli doctor`) instead, which resolves `python3` from `PATH` the way the host does and reports whether it works, is missing, is the Store stub, or runs but cannot import `soma_mcp`.

Fix for the stub: **Settings > Apps > Advanced app settings > App execution aliases**, turn off `python.exe` and `python3.exe`, then install Python from python.org (or make sure the real `python3` comes first on `PATH`). If doctor says `soma_mcp` is not importable, install it for that interpreter: `python3 -m pip install --user soma-governance`.

`soma doctor --fix-path` does not edit PowerShell profiles; on Windows it prints the `[Environment]::SetEnvironmentVariable(...)` command for the user `Path` instead. Under Git Bash (`SHELL` set to bash) it edits `~/.bashrc` like on Linux, and `install/uninstall.ps1` removes that line again from the home manifest's `path_lines`, keeping a UTF-8 BOM and the line endings. `uninstall.ps1` refuses to rewrite an rc file that is a symlink (warns instead); `uninstall.sh` follows a symlink whose target stays inside your home directory.

## Fixed in v1.4.0

### BUG-086: Rust AST driver failed without `python3.exe` ([#144](https://github.com/nseney1/Soma-Governance/issues/144))
The Rust driver slot is provisioned as `python3 .soma/drivers/rust_ast.py`, but a python.org install ships `python.exe` and no `python3.exe`. The Rust call graph therefore failed with WinError 2, and `soma doctor --fix` provisioned the slot and then reported `executable 'python3' not found on PATH`. The runner and doctor now use the interpreter running Soma when a bare `python3`/`python` isn't on `PATH`. `slots.yaml` still says `python3`.

### BUG-087: Symlink tests errored without symlink privilege ([#145](https://github.com/nseney1/Soma-Governance/issues/145))
Creating a symlink on Windows needs Developer Mode or admin rights. Two tests called `symlink_to()` directly, so on a normal account they failed with `OSError: [WinError 1314]` instead of skipping. CI's `windows-latest` runs as admin, so it never saw this. Both tests now use `conftest.symlink_or_skip`, which skips only on Windows. The same issue covered `test_async_atomic_write_text`, which CI silently skipped on every OS because `anyio` was not a test dependency.

## Fixed in v0.90.0

### BUG-035: Cell inventory rejected edited cells ([#61](https://github.com/nseney1/Soma-Governance/issues/61))
On v0.89.0, `soma_scan` and `soma_list_cells` fail with `file changed before it was opened`, and `soma_request_receipt` returns `Internal error`, so no write or execute tool can run. Cause: `os.stat` and `os.fstat` report different `st_ctime` values on Windows. The inventory now leaves `st_ctime` out of its change check on Windows and reads cells in binary mode.

### BUG-036: `uninstall.sh` under Git Bash rejected every path ([#62](https://github.com/nseney1/Soma-Governance/issues/62))
Under Git Bash the removal plan holds MSYS paths (`/c/Users/...`, `/tmp/...`), and the confinement check runs in native Windows Python, where `os.path.isabs()` rejects them, so on v0.89.0 uninstall refuses every entry and removes nothing. The check now maps MSYS paths with `cygpath` (resolved from `PATH` by the shell, never from the current directory), and the manifest reader writes UTF-8 with LF line endings, so manifests with several entries per field and non-ASCII names are removed in full. On Windows the check also refuses path segments that end in a space or a dot, and `:` stream syntax.

### BUG-038: Enzyme scripts crashed on a cp1252 stdout ([#65](https://github.com/nseney1/Soma-Governance/issues/65))
On v0.89.0, standalone scripts under `enzymes/` and `immune_system/verification/` print non-ASCII characters and exit 1 with `UnicodeEncodeError` when stdout is cp1252 (redirected or captured output, including hook runs). **Workaround on v0.89.0:** `$env:PYTHONIOENCODING = "utf-8"` (PowerShell) or `export PYTHONIOENCODING=utf-8` (Git Bash). All 29 entry points with non-ASCII output now replace characters the console can't encode.

### BUG-010: Test suite wrote to the real home directory ([#47](https://github.com/nseney1/Soma-Governance/issues/47))
Under Git Bash, `resolve_home()` prefers `USERPROFILE` over `HOME`, and six calls in `tests/test_install_lifecycle.py` overrode only `HOME`, so the installer ran against the real profile. The shared `run()` helper in `tests/conftest.py` now sets `USERPROFILE` whenever a test overrides `HOME` alone.

### BUG-012: Implicit cp1252 encoding ([#49](https://github.com/nseney1/Soma-Governance/issues/49))
On v0.89.0, `soma status` exits 1 with `UnicodeEncodeError` when stdout is cp1252 (for example, redirected output). **Workaround on v0.89.0:** `$env:PYTHONIOENCODING = "utf-8"`. `soma` and `enzymes/verify_bug_registry.py` now replace characters the console can't encode. Cell listing already reads UTF-8 explicitly since v0.89.0.

### BUG-037: Git Bash `python3` resolved to Windows Store stub ([#64](https://github.com/nseney1/Soma-Governance/issues/64))
A python.org install provides `python.exe` but no `python3.exe`, so in Git Bash `python3` resolved to the App Installer stub. `command -v python3` succeeded but execution failed, preventing hook generation and shell-script Python calls. `enzymes/soma_python.sh` now resolves a working Python 3.9+ interpreter (`soma_resolve_python` / `soma_py`) by probing `python3`, `python`, and `py -3`.

### BUG-013: Windows-only test failures ([#50](https://github.com/nseney1/Soma-Governance/issues/50))
The tests embedded unescaped Windows paths in generated files, compared paths as POSIX strings, wrote CRLF where bytes mattered, hard-coded `/bin/bash`, and required symlink privileges. They now escape paths, compare normalized paths, write LF, resolve bash (or skip), and skip symlink and execute-bit checks Windows can't satisfy. CI now runs the suite on Windows (`test-windows`, v0.90; [#56](https://github.com/nseney1/Soma-Governance/issues/56)).

## Fixed in v0.89.0

### BUG-008: MCP server crashed at startup ([#45](https://github.com/nseney1/Soma-Governance/issues/45))
`soma_mcp/tools.py` and `soma_sdk/telemetry.py` now guard the POSIX-only `fcntl` import and use platform-appropriate or best-effort locking fallbacks.

### BUG-009: Write/execute MCP tools needed a token hosts could not supply ([#46](https://github.com/nseney1/Soma-Governance/issues/46))
Write and execute tools now use single-use receipts obtained from `soma_request_receipt`. A receipt is bound to the MCP session, canonical workspace, operation, exact arguments, target-file state, and governance-cell state. It is an operation authorization mechanism, not user authentication.

### BUG-011: `install.ps1` did not parse under Windows PowerShell 5.1 ([#48](https://github.com/nseney1/Soma-Governance/issues/48))
The PowerShell scripts now carry a UTF-8 BOM, and CI dry-runs the installer under Windows PowerShell 5.1 as well as PowerShell 7. This fixes parsing, not the separate rule-content decoding problem in BUG-014.

## Fixed in v0.93.0

### BUG-014: PowerShell installer writes mojibake into generated rule files ([#59](https://github.com/nseney1/Soma-Governance/issues/59))
`install.ps1` reads rule and config files with explicit `-Encoding UTF8` and writes files preserving UTF-8 formatting and BOM. Together with the native hook runner in v0.93.0, generated rule files and configurations decode identically on PowerShell 5.1, PowerShell 7, and POSIX platforms.

### BUG-032: Native PowerShell installer does not install lifecycle hooks
`install.ps1` now deploys native hooks via `Install-Hooks` and `soma hook` / `python -m soma_cli.hooks <phase>`, eliminating the bash dependency on Windows. Installed hooks are recorded in `manifest.json` and cleanly uninstalled by `uninstall.ps1`.

## Open issues

All previously known Windows lifecycle and platform compatibility issues are resolved as of v0.93.0. Tests run automatically across Windows and Ubuntu environments in CI.
