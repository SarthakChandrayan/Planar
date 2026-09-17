from typing import Any


def normalize_extracted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Map common Qwen field mix-ups onto the extraction schema.

    Still JSON-only: this does not invent items or parse prose.
    """
    return {
        "decisions": _map_items(payload.get("decisions"), _as_statement_item),
        "requirements": _map_items(payload.get("requirements"), _as_statement_item),
        "tasks": _map_items(payload.get("tasks"), _normalize_task),
        "risks": _map_items(payload.get("risks"), _normalize_risk),
        "open_questions": _map_items(payload.get("open_questions"), _normalize_open_question),
    }


def _map_items(value: object, mapper: Any) -> object:
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    return [mapper(item) if isinstance(item, dict) else item for item in value]


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _as_statement_item(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    statement = _text(out.get("statement")) or _text(out.get("description"))
    if statement and not _text(out.get("statement")):
        out["statement"] = statement
    return out


def _normalize_task(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    statement = _text(out.get("statement"))
    title = _text(out.get("title")) or statement
    description = _text(out.get("description")) or statement or title
    if title:
        out["title"] = title
    if description:
        out["description"] = description
    if not _text(out.get("priority")):
        out["priority"] = "medium"
    if not _has_source_list(out.get("source_references")):
        single = out.get("source_reference")
        if isinstance(single, dict):
            out["source_references"] = [single]
    return out


def _normalize_risk(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    description = _text(out.get("description")) or _text(out.get("statement"))
    if description:
        out["description"] = description
    if not _text(out.get("severity")):
        out["severity"] = "medium"
    return out


def _normalize_open_question(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    statement = _text(out.get("statement"))
    question = _text(out.get("question")) or statement
    context = _text(out.get("context")) or statement
    if question:
        out["question"] = question
    if context:
        out["context"] = context
    return out


def _has_source_list(value: object) -> bool:
    return isinstance(value, list) and any(isinstance(item, dict) for item in value)
