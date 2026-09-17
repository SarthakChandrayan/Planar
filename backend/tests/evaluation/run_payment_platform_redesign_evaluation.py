"""Score the saved Payment Platform Redesign analysis against the golden key.

Loads the existing Qwen JSON output. Does not call Ollama or any LLM.

Run from the backend directory:

    .venv/Scripts/python tests/evaluation/run_payment_platform_redesign_evaluation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.domain.models import MeetingAnalysis
from tests.evaluation.evaluator import EvaluationResult, evaluate
from tests.evaluation.payment_platform_redesign_expected import (
    PAYMENT_PLATFORM_REDESIGN_GOLDEN,
)

_RESULT_JSON = (
    Path(__file__).resolve().parents[1]
    / "output"
    / "payment_platform_redesign_analysis_result.json"
)


def load_analysis(path: Path) -> MeetingAnalysis:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return MeetingAnalysis.model_validate(payload)


def render_report(result: EvaluationResult) -> str:
    lines = [
        "Payment Platform Redesign evaluation",
        f"Source: {_RESULT_JSON}",
        "",
        f"Overall score: {result.overall_score:.4f}",
        f"Match rate:    {result.match_rate:.4f}  "
        f"({result.matched_expected}/{result.total_expected} expected)",
        f"Family coverage: {result.family_coverage_score:.4f}  "
        f"(matched={len(result.matched_families)}, "
        f"partial={len(result.partial_families)}, "
        f"missed={len(result.missed_families)})",
        "",
        f"Matched families ({len(result.matched_families)}):",
    ]
    lines.extend(_bullets(result.matched_families))
    lines.append("")
    lines.append(f"Partial families ({len(result.partial_families)}):")
    if result.partial_families:
        detail = {item.key: item for item in result.family_results}
        lines.extend(
            "  - "
            f"{key} ({detail[key].satisfied_core_groups}/"
            f"{detail[key].total_core_groups} core groups)"
            for key in result.partial_families
        )
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"Missed families ({len(result.missed_families)}):")
    lines.extend(_bullets(result.missed_families))
    lines.append("")
    lines.append(f"Matched expected artifacts ({len(result.matched_expected_keys)}):")
    lines.extend(_bullets(result.matched_expected_keys))
    lines.append("")
    lines.append(f"Missed expected artifacts ({len(result.missed_expected_keys)}):")
    lines.extend(_bullets(result.missed_expected_keys))
    lines.append("")
    lines.append(f"Unexpected artifacts ({len(result.unexpected_artifacts)}):")
    if result.unexpected_artifacts:
        lines.extend(
            f"  - [{item.category}] {item.id}: {item.text}"
            for item in result.unexpected_artifacts
        )
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"Forbidden violations ({len(result.forbidden_violations)}):")
    if result.forbidden_violations:
        lines.extend(
            f"  - {item.forbidden_key} in {item.artifact_id} [{item.category}]: {item.text}"
            for item in result.forbidden_violations
        )
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"Missing source references ({len(result.missing_source_references)}):")
    if result.missing_source_references:
        lines.extend(
            f"  - {item.artifact_id} [{item.category}]"
            for item in result.missing_source_references
        )
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def _bullets(values: list[str]) -> list[str]:
    if not values:
        return ["  (none)"]
    return [f"  - {value}" for value in values]


def main() -> None:
    analysis = load_analysis(_RESULT_JSON)
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)
    print(render_report(result))


if __name__ == "__main__":
    main()
