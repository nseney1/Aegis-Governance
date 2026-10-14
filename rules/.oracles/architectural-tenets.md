---
id: architectural-tenets
domain: governance
name: Architectural Tenets
description: Design constraints focusing on pragmatism, explicit trade-off analysis, and scale-to-zero preferences.
trigger: model_decision
---
# Design & Trade-off Constraints

> **Role**: This rule sets the baseline for how solutions, architectures, and new features should be proposed to a senior software architect.

## 1. Pragmatism Over Purity
- **Avoid Over-Engineering**: Do not over-engineer simple scripts or local tools. 
- **Right Tool for the Job**: Avoid complex enterprise patterns (e.g., CQRS, heavy abstractions) unless the domain complexity specifically demands it.

## 2. Trade-off Analysis Required
- **Explicit Comparisons**: Whenever proposing an architectural change, a new technology, or a system design, you MUST explicitly list the trade-offs.
- **Key Metrics**: Structure the trade-off analysis around **Latency**, **Complexity**, and **Cost** (e.g., "Using DynamoDB eliminates idle costs and scaling concerns, but increases query complexity and limits ad-hoc aggregations").

## 3. Scale-to-Zero Preference
- **Infrastructure Constraints**: When proposing cloud architectures, aggressively prioritize serverless, scale-to-zero, or extremely low-idle-cost infrastructure options to protect personal project budgets.

## 4. Verify Artifact Existence Before Designing Migrations
- **No Speculative Backward Compatibility**: Before specifying migration utilities, checkpoint adapters, schema versioning, or backward-compatibility shims, verify whether the legacy data or artifacts actually exist in the workspace. If no legacy state exists to preserve, confirm with the user before investing engineering effort.

## Premature Abstraction
- **Prove Before Generalizing**: Do not extract "generic multi-app engines" or reusable frameworks until the primary implementation has demonstrated end-to-end operational stability across at least 3 successful runs. Cite YAGNI.

## Pivot Discipline
- **Two-Pivot Halt**: If a project changes its foundational paradigm twice (e.g., LLM → RL → Imitation), the agent must halt, summarize trade-offs in an ADR, and receive explicit user re-authorization before scaffolding a third framework.

## Real-Time Loop Budgets
- **No Blocking Inference in Control Loops**: AI inference calls (VLM, LLM, object detection) inside real-time execution loops must be async or decoupled. Synchronous calls with >500ms latency in a loop running at >1 Hz are prohibited.
