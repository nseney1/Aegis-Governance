---
id: documentation
domain: style
name: Documentation Standards
description: Enforces ADRs, concise READMEs, and meaningful code comments.
trigger: model_decision
---
# Architecture & Documentation Standards

> **Role**: This rule enforces high-signal, senior-level documentation standards while avoiding bloated enterprise boilerplate.

## 1. High-Signal Code Comments
- **"Why" Over "What"**: Never write obvious inline comments that simply restate the code (e.g., `// fetches user ID`). 
- **Focus on the Non-Obvious**: Only write comments to explain *why* a decision was made: edge cases, race condition handling, business logic quirks, or performance trade-offs.

## 2. Architecture Decision Records (ADRs)
- **ADR-Driven Design**: When making significant architectural choices, default to drafting a lightweight ADR instead of burying the rationale in a README.
- **Format**: An ADR must concisely cover: 
  1. **Context** (What is the problem?)
  2. **Decision** (What are we doing?)
  3. **Consequences** (What are the trade-offs: cost, latency, complexity?)

## 3. Actionable READMEs
- **Internal Tools & Scripts**: Strip READMEs down to pure utility.
- **Public/Product Repositories**: Follow the comprehensive structure defined in the `readme-writer` skill.
- **Required Sections**: 
  - **Prerequisites**: What needs to be installed?
  - **Environment Variables**: What `.env` values are required?
  - **Quick Start**: Explicit `make`, `docker`, or native commands to get the system running locally in under 2 minutes.

## 4. Visual Architectures (Mermaid.js)
- **Diagrams over Text**: Default to generating `mermaid.js` diagrams for state machines, sequence flows, or system architectures instead of writing walls of text. It is faster to comprehend and easier to maintain.

## 5. README Modularization
- **Size Threshold**: When a root README exceeds ~250 lines, extract deep-dive content (metrics & token economics, evolution narrative, experiments, historical data) into a `docs/` subdirectory. Keep the README focused on: why → quick start → what's included → installation → customization → links to deep dives.
