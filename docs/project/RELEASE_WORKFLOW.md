# Aegis Guardrails Release Workflow (GitFlow)

> **Superseded in v4: do not follow.** This is the v3 release procedure. It stays in the tree only until the v4 docs wave deletes it, together with the rule that lists it as a target path. Release Gate 4.5, its receipts and `check --release` are cut; a v4 release needs CI green on the exact commit (`.github/scripts/ci_green.py <sha>`) and a reviewed merge ([ADR 0005](../adr/0005-v4-plan-of-record.md) AD-2, AD-10, §5). Paths and commands below may no longer exist.

> Codified release procedure for **Aegis Guardrails** (`v3.2.0`) governed releases.
> Enforces [`invariant-gitflow-review-gate`](../../.aegis/rules/invariants/invariant-gitflow-review-gate.md) and [`invariant-ci-green-before-release`](../../.aegis/rules/invariants/invariant-ci-green-before-release.md).

## Two-Stage GitFlow Pipeline

```text
feat/* (or fix/*) ──→ PR to develop (Independent Subagent Review Gate)
                          │
                          ▼
                       develop ──→ release/vX.Y.Z ──→ Gate 4.5 (aegis check --release)
                                                           │
                                                           ▼
                                                     PR to main (Human Review Gate + CI Green)
                                                           │
                                                           ▼
                                                     tag vX.Y.Z ──→ PyPI OIDC Publish + back-merge to develop
```

### Stage 1: Feature Integration (`feat/*` → `develop`)

1. **Branch from `develop`**: `git checkout develop && git pull && git checkout -b feat/<topic>` (or `fix/<topic>`).
2. **Implement & Test**: Verify `python3 -m pytest -q` and `aegis check` pass locally.
3. **Open PR to `develop`**: `gh pr create --base develop --head feat/<topic> --title "feat: <summary>"`
4. **Independent Subagent Review Gate (`rules/gitflow-review-gate.md`)**:
   - The authoring agent MUST NOT self-approve its own PR.
   - Dispatch an independent audit subagent with an orthogonal lens to verify:
     1. All tests pass (`python3 -m pytest -q`)
     2. Zero merge conflict markers in any file
     3. Diff is strictly scoped — no unrelated changes
     4. Version strings are consistent (`pyproject.toml`, `VERSION`, `README.md`, `aegis_sdk/__init__.py`)
   - Once the independent subagent returns `APPROVED` and CI is green on `develop`, merge the PR into `develop`.

### Stage 2: Release Cutover (`develop` → `release/vX.Y.Z` → `main`)

1. **Branch from `develop`**: `git checkout develop && git pull && git checkout -b release/v3.2.0`
2. **Version bump checklist** — update every published version source atomically:
   - `pyproject.toml` → `version = "3.2.0"`
   - `VERSION` → `3.2.0`
   - `README.md` → version badge (`version-3.2.0-blue`)
   - `aegis_sdk/__init__.py` → `__version__ = "3.2.0"`
   - Run `python3 -m pytest tests/unit/core/test_static_invariants.py tests/unit/core/test_documentation_accuracy.py -q`.
3. **Execute Gate 4.5 (Mandatory Two-Layer Verification Gate)**:
   - Run `aegis check --plan "<Release plan summary>"` (or `aegis verify --plan ...` / legacy `soma verify --plan ...`) to obtain an `Arbiter` `SHIP` verdict bound to the current git tree hash.
   - Run `aegis check --release` (or `make release-gate` / `aegis verify --release-gate`) and confirm exit code `0`.
4. **Push release branch**: `git push -u origin release/v3.2.0`
5. **Create Release PR to `main`**: `gh pr create --base main --head release/v3.2.0 --title "release(v3.2.0): <summary>"`
   - The PR body must follow `rules/.oracles/git-workflow.md §5` (Executive Summary, Categorized Deliverables & Defect fixes with root cause/fix, Quantitative Test Evidence & Layer 2 Adversarial verdicts, and Human Review Gate).
6. **Wait for CI (`rules/ci-green-before-release.md`)**:
   - All GitHub Actions matrix jobs (`validate.yml`) must pass on the exact release commit before merge or tagging.
   - CI builds one wheel and one sdist, records `dist/SHA256SUMS`, verifies digests in downstream jobs, and smoke-tests both distributions outside the source checkout with `PYTHONPATH` unset and isolated Python mode (`python -I .github/scripts/wheel_smoke.py`).
   - The `test-windows` job runs the full pytest suite on `windows-latest` with `PYTHONUTF8=0` to exercise cp1252 defaults.
7. **⛔ HUMAN REVIEW GATE (`rules/gitflow-review-gate.md §2`)**:
   - Stop here. PRs targeting `main` require **Human** review and merge authority. Agents must never merge directly to `main`.
8. **Tag release** (after human merge to `main` and verified green CI per `rules/ci-green-before-release.md`):
   - `git checkout main && git pull`
   - Confirm `gh run list --branch main --limit 5` shows `completed` / `success` on `HEAD`.
   - `git tag -a v3.2.0 -m "v3.2.0: <summary>" && git push origin v3.2.0`
9. **Back-merge to `develop`**:
   - `git checkout develop && git merge main -m "chore: back-merge main (v3.2.0) into develop" && git push origin develop`
10. **Create GitHub Release**:
    - `gh release create v3.2.0 --title "v3.2.0 — <Theme>" --notes-file <release_notes>`
11. **Publish Validated Artifacts (`publish.yml`)**:
    - The release event triggers `publish.yml`, which downloads the validated build artifacts, verifies `SHA256SUMS` without rebuilding, signs build provenance (`actions/attest-build-provenance`), and uploads PEP 740 attestations and distributions to `https://pypi.org/p/aegis-guardrails` via **PyPI Trusted Publishing (OIDC)** (`pypi` environment, `id-token: write`).
12. **Cleanup**: `git push origin --delete release/v3.2.0`

## Milestone → Version Mapping

| Milestone | Version | Theme |
|:----------|:--------|:------|
| Phase 1–4.9 | v0.73.0–v0.85.0 ✅ | Foundation, Wilson scoring, credit assignment, quorum sensing, invariant DSL, hot zones |
| Phase 5.0–5.13 | v0.89.0–v0.102.0 ✅ | State-bound receipts, pure-stdlib core, zero-dependency frontmatter, command safety, facade hardening |
| Phase 6–25.5 | v0.103.0–v0.123.0 ✅ | Layer 2 CLI wiring, AST call graph, JIT budget clamping, two-phase rebuttal, ambient telemetry, `Workspace` VO, `VerificationPipeline`, horizontal skill graph, test consolidation |
| Phase 26 | v1.0.0 ✅ | Production GA, Documentation Portal & SemVer 2.0 Compatibility Guarantee |
| Phase 27–28 | v1.1.0–v1.2.1 ✅ | Language-Agnostic AST Verification (NAD), Zero-Touch Polyglot Provisioning & Rust AST Driver |
| Phase 29–31 | v1.3.0–v1.5.1 ✅ | Unified CLI Command Registry, Cross-Platform Claude Lifecycle Parity & Delegation-First Governance |
| Aegis Cutover | v2.0.0–v2.1.0 ✅ | Soma-to-Aegis Unification, `aegis-guardrails` Package Cutover & `aegis migrate` Bridge |
| Clean-Slate v3 | v3.0.0 ✅ | Pure Aegis Architecture, `.aegis/rules/` Cutover & Zero-Dependency Terminal UI (`aegis_cli/ui/`) |
| Hardening v3.1 | v3.1.0 ✅ | Standalone Wheel Parity, Burn-Before-Compare Cryptographic Receipts, 17-Tool MCP Surface & Canonical Defensive Taxonomy |
| Overhaul v3.2 | v3.2.0 ✅ | Complete Aegis Guardrails v3.2.0 Architecture, Documentation, Polyglot AST & Release Governance |

## Pre-Release Checklist

Before creating a release PR, verify:
- [ ] All phase verification-gate items pass
- [ ] **Gate 4.5** passed: `aegis check --release` (and `aegis check --plan ...` / `aegis verify --plan ...`) executed with Arbiter verdict `SHIP` (exit 0)
- [ ] `python3 -m pytest -q` passes with 0 failures
- [ ] Static import integrity passes (`ruff check --select F821`)
- [ ] Version is synchronized across `pyproject.toml`, `VERSION`, `README.md` badge, and `aegis_sdk/__init__.py`
- [ ] Validation creates exactly one wheel and one sdist plus `SHA256SUMS`
- [ ] Source-hidden smoke tests (`.github/scripts/wheel_smoke.py`) pass for both wheel and sdist, verifying bundled `rules` and `skills`
- [ ] Publish downloads and digest-verifies the validated artifact; it does not rebuild
- [ ] Publish uses OIDC Trusted Publishing (`pypi` environment, `id-token: write`); no `PYPI_API_TOKEN` secret or `twine` step
- [ ] Build provenance attestations were created for the wheel and sdist
- [ ] Workflows keep top-level `permissions: contents: read`, and every action is SHA-pinned (`tests/integration/test_ci_workflows.py`)
- [ ] `dependency-audit` (`pip-audit`) passes
- [ ] `test-windows` passes (the full pytest suite on Windows)

### Gate 4.5: Two-Layer Verification Gate (Mandatory)

Before opening a release PR or tagging a release:
1. Ensure `GEMINI_API_KEY` (or another supported inference provider key) is configured in the environment.
2. Execute `aegis check --plan "<Phase plan or specification summary>"` (or `aegis verify --plan ...`; legacy alias `soma verify --plan ...`).
3. Confirm Layer 1 deterministic checks (`DeterministicVerifier`) pass.
4. Confirm Layer 2 adversarial verification (`AdversarialVerifier`) completes with `Arbiter` verdict **`SHIP`** (`exit 0`), persisting the tree-hash-bound receipt to `.aegis/evidence/arbitration_cycle_{N}.json`.
5. Run mechanical pre-release gate check: `aegis check --release` (or `make release-gate` / `aegis verify --release-gate`). Must exit with code `0`.
6. If the Arbiter outputs `REVISE` or `BLOCK`, remediate flagged divergences before proceeding to the Release PR.

### Documentation Hygiene (mandatory per release)

Audit every documentation file for accuracy and verify `python3 -m pytest tests/unit/core/test_documentation_accuracy.py -q` passes:

- [ ] `README.md` — version references, 17 MCP tools, and 18 core rules match `test_documentation_accuracy.py`
- [ ] `docs/index.md` — all local markdown links resolve cleanly
- [ ] `docs/project/CHANGELOG.md` — contains the current release entry
- [ ] `docs/project/ROADMAP.md` — shipped statuses match the release
- [ ] `docs/project/CLAIM_REGISTRY.json` — unlocked claims have passing tests
- [ ] `docs/project/RELEASE_WORKFLOW.md` — procedure and lessons remain current

### Post-Release Cleanup (after back-merge)

- [ ] Delete the merged release branch (`release/vX.Y.Z`)
- [ ] Delete stale feature branches merged into `develop`
- [ ] Verify `docs/project/CHANGELOG.md` has the release entry
- [ ] Verify GitHub Release notes match the PR body
- [ ] Verify the published PyPI files match the recorded release digests

## Lessons Learned

### v0.73–v0.75: Single-Source Version Discipline
- `VERSION` drift across `pyproject.toml`, `VERSION`, `README.md`, and `aegis_sdk/__init__.py` must be mechanically gated by `test_static_invariants.py::test_version_is_single_sourced` and `test_documentation_accuracy.py`.

### v0.80: Structural Review Separation
- Self-reviewed merges bypass governance blind spots; `rules/gitflow-review-gate.md` enforces independent subagent review for `develop` PRs and human merge authority for `main` PRs.

### v0.89 & v3.1.0: Standalone Wheel Verification
- Testing a git checkout does not prove the published wheel works in isolation. Build once, record `SHA256SUMS`, smoke-test the wheel and sdist with the source checkout hidden (`python -I .github/scripts/wheel_smoke.py`), verify `rules/` and `skills/` package data are bundled, and publish those exact bytes without rebuilding.

