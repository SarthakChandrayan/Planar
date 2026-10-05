from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_llm_provider
from app.llm import LLMProvider, LLMTimeoutError, LLMUnavailableError
from app.main import app
from tests.fakes import FailingLLM, ScriptedLLM
from tests.fixtures.payment_meeting import DECISION_MEETING_TRANSCRIPT

DECISIONS = {
    "decisions": [
        {"statement": "Freeze the public checkout API at /v1 until October.", "lines": [1]}
    ]
}


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _client(provider: LLMProvider) -> TestClient:
    app.dependency_overrides[get_llm_provider] = lambda: provider
    return TestClient(app)


def test_analyze_endpoint_returns_meeting_analysis() -> None:
    client = _client(ScriptedLLM({"decisions": DECISIONS}))

    response = client.post("/api/meetings/analyze", json={"transcript": DECISION_MEETING_TRANSCRIPT})

    assert response.status_code == 200
    body = response.json()
    assert body["decisions"][0]["id"] == "DEC-001"
    assert body["decisions"][0]["source_reference"]["line_start"] == 1
    assert body["decisions"][0]["source_reference"]["speaker"] == "Lin"
    assert body["requirements"] == []
    assert response.headers["X-Request-ID"]


def test_request_id_is_echoed() -> None:
    client = _client(ScriptedLLM())
    response = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"


def test_empty_transcript_returns_422() -> None:
    client = _client(ScriptedLLM())

    assert client.post("/api/meetings/analyze", json={"transcript": "   "}).status_code == 422
    assert client.post("/api/meetings/analyze", json={"transcript": ""}).status_code == 422
    assert client.post("/api/meetings/analyze", json={}).status_code == 422


def test_unusable_llm_output_returns_502_without_stack_trace() -> None:
    client = _client(
        ScriptedLLM({"decisions": "x", "requirements": "x", "tasks": "x", "risks": "x"})
    )

    response = client.post("/api/meetings/analyze", json={"transcript": DECISION_MEETING_TRANSCRIPT})

    assert response.status_code == 502
    assert response.json() == {"detail": "The language model returned invalid analysis output."}
    assert "Traceback" not in response.text


def test_llm_unavailable_returns_503() -> None:
    client = _client(FailingLLM(LLMUnavailableError("Ollama server is unavailable.")))
    response = client.post("/api/meetings/analyze", json={"transcript": DECISION_MEETING_TRANSCRIPT})
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_llm_timeout_returns_504() -> None:
    client = _client(FailingLLM(LLMTimeoutError("Timed out waiting for Ollama.")))
    response = client.post("/api/meetings/analyze", json={"transcript": DECISION_MEETING_TRANSCRIPT})
    assert response.status_code == 504


def _analysis_body() -> dict:
    ref = {"excerpt": "POST /v1/charges must honor an Idempotency-Key header."}
    return {
        "decisions": [],
        "requirements": [
            {"id": "REQ-001", "statement": "Honor Idempotency-Key.", "confidence": 0.9,
             "source_reference": ref}
        ],
        "tasks": [],
        "risks": [],
        "open_questions": [],
    }


def test_implementation_plan_endpoint_returns_plan() -> None:
    plan = {
        "title": "x",
        "summary": "Idempotent charges.",
        "steps": [{"title": "Middleware", "description": "d", "requirement_ids": ["REQ-001"], "task_ids": []}],
        "acceptance_criteria": [],
    }
    client = _client(ScriptedLLM({"plan": plan}))

    response = client.post(
        "/api/meetings/implementation-plan",
        json={"analysis": _analysis_body(), "title": "November plan"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "PLAN-001"
    assert body["title"] == "November plan"
    assert body["steps"][0]["related_requirement_ids"] == ["REQ-001"]


def test_implementation_plan_rejects_dangling_relationship() -> None:
    analysis = _analysis_body()
    analysis["requirements"][0]["related_decision_ids"] = ["DEC-999"]
    response = _client(ScriptedLLM()).post(
        "/api/meetings/implementation-plan", json={"analysis": analysis}
    )
    assert response.status_code == 422


def test_implementation_plan_malformed_output_returns_502() -> None:
    response = _client(ScriptedLLM({"plan": "not json"})).post(
        "/api/meetings/implementation-plan", json={"analysis": _analysis_body()}
    )
    assert response.status_code == 502
    assert response.json() == {
        "detail": "The language model returned invalid implementation plan output."
    }
