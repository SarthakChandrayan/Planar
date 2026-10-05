from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_llm_provider, get_settings
from app.llm.exceptions import (
    LLMHTTPError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.provider import LLMProvider
from app.main import DEV_LLM_PING_PROMPT, app
from tests.fakes import FailingLLM, ScriptedLLM


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _client(provider: LLMProvider, *, dev: bool = True) -> TestClient:
    app.dependency_overrides[get_llm_provider] = lambda: provider
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, enable_dev_endpoints=dev
    )
    return TestClient(app)


def test_llm_ping_uses_provider_abstraction() -> None:
    provider = ScriptedLLM({"text": "An API is a contract between programs."})
    response = _client(provider).get("/dev/llm-ping")

    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] == DEV_LLM_PING_PROMPT
    assert body["response"] == "An API is a contract between programs."
    assert provider.prompts_for("text") == [DEV_LLM_PING_PROMPT]


def test_llm_ping_is_hidden_unless_enabled() -> None:
    assert _client(ScriptedLLM(), dev=False).get("/dev/llm-ping").status_code == 404


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (LLMUnavailableError("Ollama server is unavailable."), 503),
        (LLMTimeoutError("Timed out waiting for Ollama."), 504),
        (LLMHTTPError("model not found", status_code=404), 502),
        (LLMResponseError("Ollama returned a non-JSON response."), 502),
    ],
)
def test_llm_ping_maps_provider_errors(error: Exception, status: int) -> None:
    response = _client(FailingLLM(error)).get("/dev/llm-ping")
    assert response.status_code == status
    assert response.json()["detail"].startswith(str(error))
