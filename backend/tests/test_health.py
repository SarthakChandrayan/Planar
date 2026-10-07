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


def test_warmup_endpoint_starts_once_per_interval(monkeypatch) -> None:
    import app.main as main_module

    calls: list[int] = []

    class Warm(ScriptedLLM):
        def warm_up(self) -> None:
            calls.append(1)

    monkeypatch.setattr(main_module, "_last_warm_up", 0.0)
    app.dependency_overrides[get_llm_provider] = lambda: Warm()
    first = client.post("/api/warmup").json()
    second = client.post("/api/warmup").json()
    import time

    time.sleep(0.2)
    assert first == {"started": True} and second == {"started": False}
    assert calls == [1]
