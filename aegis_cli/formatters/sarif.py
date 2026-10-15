"""SARIF 2.1.0 and verification report formatters."""
from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "format_sarif_report",
    "format_layer2_summary",
    "format_in_band_charge_sheet",
    "format_layer1_json_payload",
]


def format_sarif_report(results: list[Any], repo_root: str | Path) -> dict[str, Any]:
    """Construct a valid SARIF 2.1.0 dictionary from Layer 1 verification results."""
    seen_rules: dict[str, dict[str, Any]] = {}
    sarif_results: list[dict[str, Any]] = []

    for r in results or []:
        tool_id = str(getattr(r, "tool", "aegis-check"))
        if tool_id not in seen_rules:
            seen_rules[tool_id] = {
                "id": tool_id,
                "shortDescription": {"text": f"Aegis verification check: {tool_id}"},
            }
        if not getattr(r, "verdict", True):
            target_str = str(getattr(r, "target", ""))
            detail_str = str(getattr(r, "detail", "Verification check failed"))
            sarif_results.append(
                {
                    "ruleId": tool_id,
                    "level": "error",
                    "message": {"text": detail_str},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": target_str,
                                }
                            }
                        }
                    ],
                }
            )

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Aegis Guardrails",
                        "informationUri": "https://github.com/nseney1/Aegis-Guardrails",
                        "rules": list(seen_rules.values()),
                    }
                },
                "results": sarif_results,
            }
        ],
    }


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


def format_in_band_charge_sheet(charge_sheet: Any) -> str:
    """Format an in-band prosecution charge sheet for CLI display."""
    lines = [
        "\n📋 AEGIS VERIFICATION REPORT — IN-BAND CHARGE SHEET (AEGIS-V01)",
        f"Target files ({len(charge_sheet.target_files)}): {', '.join(charge_sheet.target_files)}",
        f"Prosecution charges ({len(charge_sheet.predictions)}):",
    ]
    for idx, p in enumerate(charge_sheet.predictions, 1):
        sev = p.severity.value if hasattr(p.severity, "value") else str(p.severity)
        cat = p.category.value if hasattr(p.category, "value") else str(p.category)
        lines.append(f"  {idx}. [{sev.upper()}] {cat} in '{p.affected_function}': {p.risk}")
        lines.append(f"     Mechanism: {p.mechanism}")
    lines.append("\nRebuttal instructions:")
    lines.append("  Submit defense claims citing evidence_file, evidence_line, and tests covering the fix.")
    return "\n".join(lines)


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
