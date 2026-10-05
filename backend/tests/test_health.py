from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_llm_provider
from app.llm import LLMUnavailableError
from app.main import app
from tests.fakes import ScriptedLLM

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_model_available() -> None:
    app.dependency_overrides[get_llm_provider] = lambda: ScriptedLLM()
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_not_ready_explains_why() -> None:
    class Missing(ScriptedLLM):
        def check_ready(self) -> None:
            raise LLMUnavailableError("Model 'qwen3:8b' is not installed in Ollama.")

    app.dependency_overrides[get_llm_provider] = lambda: Missing()
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "not installed" in response.json()["detail"]
