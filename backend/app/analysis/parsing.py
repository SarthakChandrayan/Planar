import json
import re
from typing import Any

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCED_JSON = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from an LLM string. Does not interpret free prose."""
    if not text or not text.strip():
        raise ValueError("LLM returned an empty response.")

    cleaned = _THINK_BLOCK.sub("", text).strip()
    candidates: list[str] = [cleaned]
    candidates.extend(block.strip() for block in _FENCED_JSON.findall(cleaned) if block.strip())

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])

    last_error: Exception | None = None
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(payload, dict):
            return payload
        last_error = ValueError("LLM JSON root must be an object.")

    raise ValueError("LLM did not return a JSON object.") from last_error
