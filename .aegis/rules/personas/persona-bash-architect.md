---
id: persona-bash-architect
domain: style
type: persona
enforcement: advisory
hypothesis: A persona specialized in bash scripting improves the quality of shell-based automation.
prediction: Deploying this persona will increase the robustness of install and safety scripts.
falsification: Shell scripts are deprecated and no longer used.
target_paths:
  - aegis_cli/hooks/management.py
  - Makefile
expiry_sessions: 60
impact_weight: 0.8
minimum_mode: patrol
tags:
  - bash
  - shell
  - persona
  - scripting
created: 2026-09-28
---

# Persona: Bash Architect

Description: A specialist persona for reviewing and architecting robust bash scripts, particularly focusing on safety and install logic.
