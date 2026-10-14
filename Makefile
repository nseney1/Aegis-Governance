# Soma — Makefile
# Without soma.conf, all defaults apply (solo/trunk/all).

# Defaults (namespaced to avoid env collisions)
SOMA_PLATFORM ?= gemini
TEAM_SIZE         ?= solo
GIT_STRATEGY      ?= trunk
APPROVAL_CHAIN    ?= none
RULES_SUBSET      ?= all
ENABLE_HOOKS      ?= true

export TEAM_SIZE GIT_STRATEGY APPROVAL_CHAIN
export RULES_SUBSET ENABLE_HOOKS SOMA_PLATFORM

# A working Python 3.9+ (python3 can be the Windows Store stub, BUG-037).
# Not exported: install.sh resolves its own, so a working python3 still
# lands in MCP configs as the portable "python3".
SOMA_PYTHON_BIN ?= $(shell \
	for py in "$$SOMA_PYTHON" "$$VIRTUAL_ENV/bin/python3" "$$VIRTUAL_ENV/bin/python" python3 python py; do \
		if [ -n "$$py" ] && command -v "$$py" >/dev/null 2>&1; then \
			if "$$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then \
				command -v "$$py"; \
				break; \
			fi; \
		fi; \
	done \
)

.PHONY: help info install install-gemini install-kiro install-copilot \
        install-claude install-mcp install-windows \
        uninstall doctor validate update status test \
        verify-layer1 release-gate

help: ## Show available targets
	@echo "Soma — Adaptive Governance"
	@echo ""
	@echo "Workflow:"
	@echo "  1. cp install/soma.conf.example soma.conf"
	@echo "  2. Edit soma.conf (set SOMA_PLATFORM, TEAM_SIZE, etc.)"
	@echo "  3. make install"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Override any setting inline: make install RULES_SUBSET=core"


info: ## Show current configuration
	@echo "┌───────────────────────────────┐"
	@echo "│  Soma — Configuration         │"
	@echo "├───────────────────────────────┤"
	@echo "│  Platform:        $(SOMA_PLATFORM)"
	@echo "│  Team Size:       $(TEAM_SIZE)"
	@echo "│  Git Strategy:    $(GIT_STRATEGY)"
	@echo "│  Approval Chain:  $(APPROVAL_CHAIN)"
	@echo "│  Rules Subset:    $(RULES_SUBSET)"
	@echo "│  Hooks Enabled:   $(ENABLE_HOOKS)"
	@echo "└───────────────────────────────┘"

install: ## Install for configured platform (SOMA_PLATFORM)
	@log=$$(mktemp); trap 'rm -f "$$log"' EXIT INT TERM; \
	if [ -z "$(SOMA_PYTHON_BIN)" ]; then \
	  echo "  ⚠️  no working Python 3.9+ found; skipping pip install -e . (set SOMA_PYTHON)"; \
	elif "$(SOMA_PYTHON_BIN)" -m pip install --user -e . --quiet 2>"$$log" \
	  || "$(SOMA_PYTHON_BIN)" -m pip install --user --break-system-packages -e . --quiet 2>>"$$log" \
	  || "$(SOMA_PYTHON_BIN)" -m pip install -e . --quiet 2>>"$$log"; then :; else \
	  echo "  ⚠️  pip install -e . failed (soma CLI may not be on PATH). pip reported:"; \
	  sed 's/^/      /' "$$log"; \
	fi; \
	rm -f "$$log"
	@python3 -m soma_cli.cli install --platform "$(SOMA_PLATFORM)"

install-gemini: ## Install rules for Gemini/Antigravity (alias)
	@python3 -m soma_cli.cli install --platform gemini

install-kiro: ## Install rules for Kiro (alias)
	@python3 -m soma_cli.cli install --platform kiro

install-copilot: ## Install rules for GitHub Copilot (alias)
	@python3 -m soma_cli.cli install --platform copilot

install-claude: ## Install rules for Claude Code
	@python3 -m soma_cli.cli install --platform claude

install-mcp: ## Install only .mcp.json for any MCP-compatible agent
	@python3 -m soma_cli.cli install --platform mcp

install-windows: ## Install rules and skills for Windows using PowerShell
	@python3 -m soma_cli.cli install --platform "$(SOMA_PLATFORM)"

uninstall: ## Remove installed genome, organs, and hooks
	@echo "Uninstalling Soma for $(SOMA_PLATFORM)..."
	@python3 -m soma_cli.cli uninstall --platform "$(SOMA_PLATFORM)"

doctor: ## Verify installation health & dependencies
	@echo "Running health check..."
	@echo ""
	@echo "Dependencies:"
	@command -v bash >/dev/null 2>&1 && echo "  ✅ bash" || echo "  ❌ bash not found"
	@if [ -n "$(SOMA_PYTHON_BIN)" ]; then echo "  ✅ python ($(SOMA_PYTHON_BIN))"; else echo "  ⚠️  no working Python 3.9+ found (hooks will not install)"; fi
	@command -v git >/dev/null 2>&1 && echo "  ✅ git" || echo "  ❌ git not found"
	@command -v sed >/dev/null 2>&1 && echo "  ✅ sed" || echo "  ❌ sed not found"
	@command -v awk >/dev/null 2>&1 && echo "  ✅ awk" || echo "  ❌ awk not found"
	@echo ""
	@echo "Packages:"
	@for mod in aegis_core aegis_cli aegis_sdk aegis_mcp soma_core soma_cli soma_sdk soma_mcp; do \
	  if [ -d "$$mod" ]; then echo "  ✅ $$mod (package)"; else echo "  ❌ $$mod missing"; fi; \
	done
	@echo ""
	@echo "Hook template:"
	@if [ -f install/hooks.json.template ]; then echo "  ✅ install/hooks.json.template"; else echo "  ❌ install/hooks.json.template missing"; fi
	@echo ""
	@echo "Installed genome ($(SOMA_PLATFORM)):"
	@case "$(SOMA_PLATFORM)" in \
	  gemini) if ls $(HOME)/.gemini/config/rules/*.md >/dev/null 2>&1; then \
	      for f in $(HOME)/.gemini/config/rules/*.md; do echo "  ✅ $$(basename $$f)"; done; \
	    else echo "  (none)"; fi; \
	    if [ -f $(HOME)/.gemini/config/plugins/governance/hooks.json ]; then echo "  ✅ hooks.json installed"; else echo "  ⚠️  hooks.json not installed"; fi ;; \
	  kiro) if ls $(HOME)/.kiro/steering/*.md >/dev/null 2>&1; then \
	      for f in $(HOME)/.kiro/steering/*.md; do echo "  ✅ $$(basename $$f)"; done; \
	    else echo "  (none)"; fi; \
	    echo ""; \
	    echo "Installed skills (kiro):"; \
	    if [ -d $(HOME)/.kiro/skills ]; then \
	      if ls -d $(HOME)/.kiro/skills/*/ >/dev/null 2>&1; then \
	        for d in $(HOME)/.kiro/skills/*/; do echo "  ✅ $$(basename $$d)"; done; \
	      else echo "  (none)"; fi; \
	    else echo "  (none — $(HOME)/.kiro/skills/ not found)"; fi ;; \
	  copilot) if [ -f $(HOME)/copilot-instructions.md ]; then echo "  ✅ $(HOME)/copilot-instructions.md"; else echo "  (none)"; fi ;; \
	  claude) if [ -f $(HOME)/.claude/CLAUDE.md ]; then echo "  ✅ $(HOME)/.claude/CLAUDE.md"; else echo "  (none)"; fi ;; \
	  mcp) if [ -f .mcp.json ]; then echo "  ✅ .mcp.json"; else echo "  (none)"; fi ;; \
	esac

validate: ## Check script syntax and config values
	@echo "Validating..."
	@failed=0; \
	for s in install/hooks/*; do \
	  if [ -f "$$s" ]; then \
	    if bash -n "$$s" 2>/dev/null; then echo "  ✅ $$s"; \
	    else echo "  ❌ $$s (syntax error)"; bash -n "$$s" || true; failed=1; fi; \
	  fi; \
	done; \
	if [ -n "$(SOMA_PYTHON_BIN)" ]; then \
	  for p in aegis_cli/*.py aegis_core/*.py aegis_core/**/*.py aegis_mcp/*.py aegis_sdk/*.py soma_cli/*.py soma_core/*.py soma_core/**/*.py soma_mcp/*.py soma_sdk/*.py; do \
	    if [ -f "$$p" ]; then \
	      if "$(SOMA_PYTHON_BIN)" -c "import ast, sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" "$$p" 2>/dev/null; then :; \
	      else echo "  ❌ $$p (syntax error)"; failed=1; fi; \
	    fi; \
	  done; \
	  echo "  ✅ python syntax"; \
	  if "$(SOMA_PYTHON_BIN)" -c "import json, sys; json.load(open(sys.argv[1], encoding='utf-8'))" install/hooks.json.template > /dev/null 2>&1; then \
	    echo "  ✅ install/hooks.json.template (valid JSON)"; \
	  else echo "  ❌ install/hooks.json.template (invalid JSON)"; failed=1; fi; \
	else \
	  echo "  ⚠️  no working Python 3.9+ found — skipping Python syntax and JSON checks"; \
	fi; \
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true; \
	if [ "$$failed" -ne 0 ]; then echo "FAILED"; exit 1; fi; \
	echo "Done!"

update: ## Pull latest and re-install
	@echo "Pulling latest changes..."
	@git pull --ff-only
	@echo ""
	@$(MAKE) install

status: ## Show installed vs repo diff
	@echo "Comparing installed rules to repo..."
	@case "$(SOMA_PLATFORM)" in \
	  gemini) for rule in genome/*.md; do \
	    name=$$(basename $$rule); \
	    target=$(HOME)/.gemini/config/rules/$$name; \
	    if [ ! -f "$$target" ]; then echo "  ❌ $$name (not installed)"; \
	    elif diff -q "$$rule" "$$target" > /dev/null 2>&1; then echo "  ✅ $$name (in sync)"; \
	    else echo "  ⚠️  $$name (modified)"; fi; \
	  done ;; \
	  kiro) for rule in genome/*.md; do \
	    name=$$(basename $$rule); \
	    target=$(HOME)/.kiro/steering/$$name; \
	    if [ ! -f "$$target" ]; then echo "  ❌ $$name (not installed)"; \
	    else echo "  ✅ $$name (installed)"; fi; \
	  done ;; \
	  *) echo "  Status check only supported for gemini and kiro platforms" ;; \
	esac

test: validate ## Run validation tests (auto-parallelized when pytest-xdist is installed)
	@echo "Running test suite..."
	@if command -v pytest >/dev/null 2>&1; then \
	  if pytest -h 2>/dev/null | grep -q -- "--numprocesses"; then \
	    pytest -n auto tests/ || exit 1; \
	  else \
	    pytest tests/ || exit 1; \
	  fi; \
	else \
	  echo "  ❌  pytest not found. Install with: pip install pytest"; \
	  exit 1; \
	fi

verify-layer1: ## Run Layer 1 deterministic quality tools on changed files
	@$(SOMA_PYTHON_BIN) -m aegis_cli.verify --layer1-only

release-gate: ## Assert Release Gate 4.5 passes with a valid SHIP arbitration receipt
	@$(SOMA_PYTHON_BIN) -m aegis_cli.verify --release-gate

