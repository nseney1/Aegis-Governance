---
id: feature-specs
domain: governance
name: Feature Spec Standards
description: Enforces rigorous, architect-level guidelines for defining new features, PRDs, and component breakdowns.
trigger: model_decision
---
# Feature Specification Guidelines

> **Role**: This rule enforces a strict, senior-level template for defining new features, ensuring all architectural, security, and edge-case considerations are handled before execution begins.

When asked to spec out a new feature or draft a Product Requirements Document (PRD), adhere strictly to the following structure:

## 1. Core Definition
- **Business Value**: What specific problem does this solve? 
- **Target Audience**: Who is this for?

## 2. Non-Functional Requirements (NFRs)
Before writing any implementation details, explicitly define the constraints:
- **Performance**: Latency expectations, throughput limits.
- **Security & Privacy**: Required auth checks, data sanitization, compliance boundaries.
- **Cost**: Expected infrastructure impact or API usage costs.

## 3. Scope Boundaries
- **In Scope**: The exact behavioral requirements.
- **Out of Scope (Anti-Goals)**: Explicitly state what is *not* being built to prevent scope creep and over-engineering.

## 4. Technical Component Breakdown
Group the technical implementation into logical layers:
- **Data Model**: Schema changes, migrations, indexing strategies.
- **API Contracts**: Request/Response payloads, error codes.
- **Business Logic**: State machines, background jobs, external integrations.
- **UI/UX**: Component hierarchy, state management.

## 5. Acceptance Criteria
- Use behavioral checklists (e.g., Given/When/Then formats) that map directly to the sad-paths and edge cases.

## 6. Documentation Deliverables
- Deliver documentation adhering to `documentation.md` standards (actionable READMEs and lightweight ADRs for architectural decisions).
