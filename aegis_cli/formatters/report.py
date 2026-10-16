"""Text and JSON report formatters for `aegis check`."""
from __future__ import annotations

from typing import Any

__all__ = [
    "format_layer2_json",
    "format_layer2_summary",
    "format_layer1_json_payload",
]


def format_layer2_summary(result: Any) -> str:
    """Format Layer 2 arbitration results for CLI output."""
    from aegis_core.verification import Verdict

    lines = []
    verdict_str = result.verdict.name if hasattr(result.verdict, "name") else str(result.verdict)
    icon = "✅" if result.verdict == Verdict.SHIP else "🔴"
    lines.append(f"Layer 2: {icon} {verdict_str}")

    if result.divergences:
        lines.append(f"  Divergences ({len(result.divergences)}):")
        for d in result.divergences:
            pred_desc = f" [{d.prediction.severity.value}] {d.prediction.risk}" if d.prediction else ""
            lines.append(f"    - {d.category.value} ({d.divergence_type}):{pred_desc}")
            if d.resolution:
                lines.append(f"      Resolution: {d.resolution}")

    if result.convergences:
        lines.append(
            f"  Convergences ({len(result.convergences)}): "
            f"{', '.join(c.value for c in result.convergences)}"
        )

    return "\n".join(lines)


def format_layer2_json(result: Any, verdict: Any) -> dict[str, Any]:
    """JSON summary of a Layer 2 arbitration for `aegis check --format json`."""
    return {
        "verdict": verdict.value if hasattr(verdict, "value") else str(verdict),
        "divergences": [
            {"type": d.divergence_type, "category": d.category.value, "resolution": d.resolution}
            for d in (result.divergences if result else [])
        ],
        "convergences": [c.value for c in (result.convergences if result else [])],
    }


def format_layer1_json_payload(
    layer1_pass: bool,
    target_files: list[str],
    results: list[Any],
    summary: str,
) -> dict[str, Any]:
    """Construct JSON output dictionary for Layer 1 verification results."""
    return {
        "passed": layer1_pass,
        "files": target_files,
        "layer1": [
            {
                "tool": r.tool,
                "target": r.target,
                "verdict": bool(r.verdict),
                "detail": r.detail,
            }
            for r in results
        ],
        "summary": summary,
    }
