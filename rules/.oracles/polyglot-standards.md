---
id: polyglot-standards
domain: governance
name: Polyglot Standards
description: Enforces unified entrypoints (Makefiles/Justfiles) and containerization across all tech stacks.
trigger: model_decision
---
# Cross-Stack Consistency Standards

> **Role**: This rule enforces a unified developer experience and standard scaffolding across all languages and tech stacks.

## 1. Universal Entrypoints
- **Consistent Verbs**: Regardless of whether a project is written in Go, Python, TypeScript, or Rust, always define a universal entrypoint file (like a `Makefile`, `Justfile`, or `package.json` scripts block).
- **Standard Commands**: Ensure the following standard verbs are always present and mapped to their language-specific equivalents: `build`, `run`, `test`, `lint`.
- **Virtual Environment Binding**: Makefiles for Python projects must bind virtual environment binaries explicitly (`$(VENV)/bin/python`, `$(VENV)/bin/pytest`) rather than relying on ambient `$PATH`.

## 2. Containerization First
- **Docker by Default**: Always include a minimal `Dockerfile` for any new service, API, or persistent background job created. Skip for standalone scripts, CLIs, single-file utilities, or serverless functions where containerless deployment is standard.
- **Optimization**: Dockerfiles MUST be multi-stage, optimized for final image size (e.g., using alpine or scratch base images), and structured to maximize layer caching.
