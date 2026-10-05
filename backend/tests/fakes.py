"""Test doubles for the LLM provider."""

import json
from typing import Any

from app.llm.provider import LLMProvider, TokenCallback

Answer = dict[str, Any] | str | Exception


def schema_key(schema: dict[str, Any] | None) -> str:
    """Which pass a request belongs to, from its JSON schema."""
    if schema is None:
        return "text"
    first = next(iter(schema.get("properties", {})), "text")
    return "plan" if first == "title" else first


class ScriptedLLM(LLMProvider):
    """Answers each request by pass ("decisions", "tasks", "plan", ...).

    An answer may be a payload dict (sent as JSON), a raw string, or an
    exception to raise. A list of answers is consumed one call at a time.
    Passes with no scripted answer get an empty result.
    """

    def __init__(self, answers: dict[str, Answer | list[Answer]] | None = None) -> None:
        self._answers = {key: list(v) if isinstance(v, list) else [v] for key, v in (answers or {}).items()}
        self.calls: list[tuple[str, str]] = []

    def generate(
        self,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        on_tokens: TokenCallback | None = None,
    ) -> str:
        key = schema_key(schema)
        self.calls.append((key, prompt))
        if on_tokens is not None:
            on_tokens(1)
        queue = self._answers.get(key)
        if not queue:
            return json.dumps(_empty(key))
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, str):
            return answer
        return json.dumps(answer)

    def prompts_for(self, key: str) -> list[str]:
        return [prompt for call_key, prompt in self.calls if call_key == key]


class FailingLLM(LLMProvider):
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(
        self,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        on_tokens: TokenCallback | None = None,
    ) -> str:
        raise self.error


def _empty(key: str) -> dict[str, Any]:
    if key == "risks":
        return {"risks": [], "open_questions": []}
    if key == "plan":
        return {"title": "", "summary": "", "steps": [], "acceptance_criteria": []}
    return {key: []}
