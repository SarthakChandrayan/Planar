from typing import Never

from fastapi.testclient import TestClient

from app.dependencies import get_llm_provider
from app.llm.exceptions import (
    LLMHTTPError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.provider import LLMProvider
from app.main import DEV_LLM_PING_PROMPT, app


class FakeLLMProvider(LLMProvider):
    def __init__(self, text: str = "An API is a contract between programs.") -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
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


def test_llm_ping_uses_provider_abstraction() -> None:
    provider = FakeLLMProvider()
    client = _client_with_provider(provider)

    response = client.get("/dev/llm-ping")

    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] == DEV_LLM_PING_PROMPT
    assert body["response"] == provider.text
    assert body["model"]
    assert provider.prompts == [DEV_LLM_PING_PROMPT]


def test_llm_ping_unavailable_returns_503() -> None:
    client = _client_with_provider(
        FailingLLMProvider(LLMUnavailableError("Ollama server is unavailable."))
    )

    response = client.get("/dev/llm-ping")

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_llm_ping_timeout_returns_504() -> None:
    client = _client_with_provider(
        FailingLLMProvider(LLMTimeoutError("Timed out waiting for Ollama."))
    )

    response = client.get("/dev/llm-ping")

    assert response.status_code == 504


def test_llm_ping_http_error_returns_502() -> None:
    client = _client_with_provider(
        FailingLLMProvider(LLMHTTPError("model not found", status_code=404))
    )

    response = client.get("/dev/llm-ping")

    assert response.status_code == 502
    assert response.json()["detail"] == "model not found"


def test_llm_ping_malformed_response_returns_502() -> None:
    client = _client_with_provider(
        FailingLLMProvider(LLMResponseError("Ollama returned a non-JSON response."))
    )

    response = client.get("/dev/llm-ping")

    assert response.status_code == 502
