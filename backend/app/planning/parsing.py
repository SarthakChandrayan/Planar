from typing import Any

from app.analysis.parsing import parse_json_object


def parse_plan_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from an LLM string. Does not interpret free prose."""
    return parse_json_object(text)


def normalize_extracted_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Map common field mix-ups onto the implementation-plan extraction schema."""
    out = dict(payload)
    if not _text(out.get("title")):
        statement = _text(out.get("name")) or _text(out.get("plan_title"))
        if statement:
            out["title"] = statement
    if not _text(out.get("summary")):
        summary = _text(out.get("description")) or _text(out.get("overview"))
        if summary:
            out["summary"] = summary
    steps = out.get("steps")
    if isinstance(steps, list):
        out["steps"] = [
            _normalize_step(item) if isinstance(item, dict) else item for item in steps
        ]
    criteria = out.get("acceptance_criteria")
    if criteria is None and isinstance(out.get("acceptanceCriteria"), list):
        out["acceptance_criteria"] = out["acceptanceCriteria"]
    return out


def _normalize_step(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    title = _text(out.get("title")) or _text(out.get("statement"))
    if title and not _text(out.get("title")):
        out["title"] = title
    description = _text(out.get("description")) or title
    if description and not _text(out.get("description")):
        out["description"] = description
    if not isinstance(out.get("related_requirement_ids"), list):
        related = out.get("related_requirements") or out.get("requirement_ids")
        if isinstance(related, list):
            out["related_requirement_ids"] = related
        elif isinstance(related, str) and related.strip():
            out["related_requirement_ids"] = [related]
    if not isinstance(out.get("related_task_ids"), list):
        related = out.get("related_tasks") or out.get("task_ids")
        if isinstance(related, list):
            out["related_task_ids"] = related
        elif isinstance(related, str) and related.strip():
            out["related_task_ids"] = [related]
    if not _has_evidence_list(out.get("evidence")):
        refs = out.get("source_references")
        single = out.get("source_reference")
        if isinstance(refs, list):
            out["evidence"] = refs
        elif isinstance(single, dict):
            out["evidence"] = [single]
        elif isinstance(single, str) and single.strip():
            out["evidence"] = [{"excerpt": single}]
    return out


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _has_evidence_list(value: object) -> bool:
    return isinstance(value, list) and any(isinstance(item, dict) for item in value)
