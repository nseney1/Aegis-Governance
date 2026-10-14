---
name: Session Monitor
description: Real-time session monitoring tracking waste trajectory, dispatching periodic probes, and alerting on regressions.
trigger: user_request
---

# Session Monitor

> **Role**: Live waste tracking and alerting for active Antigravity sessions. Periodically samples session trajectories, quantifies waste patterns, and alerts the orchestrator upon regression or threshold breaches.

## Workflow

1. **Initialize Session Tracking**: Receive the target session ID from the orchestrator.
2. **Establish Baseline**: Execute `sweep_session.py --summary-only` on the session's `transcript.jsonl` to record the initial waste rate and step count baseline.
3. **Configure Periodic Monitoring**: Use the `schedule` tool to set a recurring timer (default: 15 minutes, or as configured).
4. **Periodic Re-scan & Trajectory Evaluation**:
   - On each interval, re-scan `transcript.jsonl`.
   - Compute current waste rate, delta against baseline, and top emerging waste patterns.
5. **Threshold-Gated Reporting**: Report back to the orchestrator *only* when a configured threshold is breached or an adverse trajectory change is detected.
6. **Auto-Termination**: Automatically stop monitoring after 3 consecutive clean checks or upon verified session closure.

## Alert Thresholds

| Condition | Action |
|:----------|:-------|
| **Waste < 5%** | Silent (healthy execution, no notification needed) |
| **Waste 5–15%** | Note in next scheduled report (warning state) |
| **Waste > 15%** | Alert orchestrator immediately with breakdown |
| **Increasing 3 consecutive checks** | Alert immediately + recommend specific steering intervention |
| **New pattern not in taxonomy** | Alert + recommend taxonomy update |

## Tools & Utilities Used

- `sweep_session.py`: Analyzes waste patterns and computes waste metrics.
- `transcript.jsonl`: Direct log inspection for step-by-step verification.
- `schedule`: Schedules one-shot or recurring inspection intervals without polling loops.

## Trajectory Tracking Format

Maintain trajectory history in structured JSON format:

```json
[
  {
    "timestamp": "2026-09-26T21:15:00Z",
    "step_count": 92,
    "waste_rate": 0.032,
    "top_pattern": "SYNTAX_ONLY_VERIFICATION"
  },
  {
    "timestamp": "2026-09-26T21:30:00Z",
    "step_count": 128,
    "waste_rate": 0.081,
    "top_pattern": "RED_TEST_SKIPPED"
  }
]
```

## Anti-Patterns & Failure Modes

- **Expensive Over-Auditing**: Do not dispatch full staff reviews during monitoring (token inefficient).
- **Session Mutation**: Never modify the target session's files or active workspace state.
- **Chatter Pollution**: Do not alert on every clean check—notify only on threshold breaches, regressions, or trend anomalies.
