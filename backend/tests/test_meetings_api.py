import json
from typing import Any, Never

from fastapi.testclient import TestClient

from app.dependencies import get_llm_provider
from app.llm import LLMTimeoutError, LLMUnavailableError
from app.llm.provider import LLMProvider
from app.main import app
from tests.fixtures.payment_meeting import (
    DECISION_MEETING_TRANSCRIPT,
    PAYMENT_MEETING_TRANSCRIPT,
)


class FakeLLMProvider(LLMProvider):
    def __init__(self, text: str) -> None:
        self.text = text

    def generate(self, prompt: str) -> str:
        return self.text


class FailingLLMProvider(LLMProvider):
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, prompt: str) -> Never:
        raise self.error


def _client_with_provider(provider: LLMProvider) -> TestClient:
    app.dependency_overrides[get_llm_provider] = lambda: provider
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _decision_payload() -> dict[str, Any]:
    return {
        "decisions": [
            {
                "statement": "Freeze the public checkout API at /v1 until October.",
                "confidence": 0.93,
                "source_reference": {
                    "excerpt": "We will freeze the public checkout API at /v1 until October."
                },
            }
        ],
        "requirements": [],
        "tasks": [],
        "risks": [],
        "open_questions": [],
    }


def test_analyze_endpoint_returns_meeting_analysis() -> None:
    client = _client_with_provider(FakeLLMProvider(json.dumps(_decision_payload())))

    response = client.post(
        "/api/meetings/analyze",
        json={"transcript": DECISION_MEETING_TRANSCRIPT},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decisions"][0]["id"] == "DEC-001"
    assert body["requirements"] == []


def test_empty_transcript_returns_422() -> None:
    client = _client_with_provider(FakeLLMProvider("{}"))

    blank = client.post("/api/meetings/analyze", json={"transcript": "   "})
    missing = client.post("/api/meetings/analyze", json={"transcript": ""})
    omitted = client.post("/api/meetings/analyze", json={})

    assert blank.status_code == 422
    assert missing.status_code == 422
    assert omitted.status_code == 422


def test_malformed_llm_output_returns_502_without_stack_trace() -> None:
    client = _client_with_provider(FakeLLMProvider("not json at all"))

    response = client.post(
        "/api/meetings/analyze",
        json={"transcript": DECISION_MEETING_TRANSCRIPT},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "The language model returned invalid analysis output."
    }
    assert "Traceback" not in response.text


def test_llm_unavailable_returns_503() -> None:
    client = _client_with_provider(
        FailingLLMProvider(LLMUnavailableError("Ollama server is unavailable."))
    )

    response = client.post(
        "/api/meetings/analyze",
        json={"transcript": PAYMENT_MEETING_TRANSCRIPT},
    )

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_llm_timeout_returns_504() -> None:
    client = _client_with_provider(
        FailingLLMProvider(LLMTimeoutError("Timed out waiting for Ollama."))
    )

    response = client.post(
        "/api/meetings/analyze",
        json={"transcript": DECISION_MEETING_TRANSCRIPT},
    )

    assert response.status_code == 504


def _plan_analysis() -> dict[str, Any]:
    return {
        "decisions": [
            {
                "id": "DEC-001",
                "statement": "Postgres is the source of truth for payment idempotency.",
                "confidence": 0.95,
                "source_reference": {
                    "excerpt": "Postgres is the source of truth for payment idempotency."
                },
            }
        ],
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "Same key and body must return the original result.",
                "confidence": 0.9,
                "source_reference": {
                    "excerpt": "A repeated request with the same key and body returns the original charge."
                },
            }
        ],
        "tasks": [
            {
                "id": "TSK-001",
                "title": "Add idempotency middleware",
                "description": "Handle duplicate charges.",
                "priority": "high",
                "acceptance_criteria": [],
                "source_references": [
                    {"excerpt": "add idempotency middleware to POST /v1/charges."}
                ],
            }
        ],
        "risks": [],
        "open_questions": [],
    }


def _plan_llm_output() -> dict[str, Any]:
    return {
        "title": "Idempotency plan",
        "summary": "Implement duplicate-request handling in Postgres.",
        "steps": [
            {
                "title": "Implement duplicate-request handling for idempotent payment creation.",
                "description": "Return the original result for the same key and body.",
                "related_requirement_ids": ["REQ-001"],
                "related_task_ids": ["TSK-001"],
                "evidence": [
                    {
                        "excerpt": "A repeated request with the same key and body returns the original charge."
                    }
                ],
            }
        ],
        "acceptance_criteria": [
            "A repeated request with the same key and body returns the original charge."
        ],
    }


def test_implementation_plan_endpoint_returns_plan() -> None:
    client = _client_with_provider(FakeLLMProvider(json.dumps(_plan_llm_output())))

    response = client.post(
        "/api/meetings/implementation-plan",
        json={"analysis": _plan_analysis(), "title": "November plan"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "PLAN-001"
    assert body["title"] == "November plan"
    assert body["steps"][0]["id"] == "STEP-001"
    assert body["steps"][0]["related_requirement_ids"] == ["REQ-001"]


def test_implementation_plan_rejects_analysis_with_dangling_relationship() -> None:
    client = _client_with_provider(FakeLLMProvider(json.dumps(_plan_llm_output())))
    analysis = _plan_analysis()
    analysis["requirements"][0]["related_decision_ids"] = ["DEC-999"]

    response = client.post(
        "/api/meetings/implementation-plan",
        json={"analysis": analysis},
    )

    assert response.status_code == 422
    assert "Traceback" not in response.text


def test_implementation_plan_malformed_llm_output_returns_502() -> None:
    client = _client_with_provider(FakeLLMProvider("not json at all"))

    response = client.post(
        "/api/meetings/implementation-plan",
        json={"analysis": _plan_analysis()},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "The language model returned invalid implementation plan output."
    }
    assert "Traceback" not in response.text
