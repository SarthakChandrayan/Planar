from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.llm.exceptions import (
    LLMHTTPError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.ollama import OllamaProvider
from app.llm.provider import LLMProvider

MODEL = "configured-model"
BASE_URL = "http://localhost:11434"


def _provider() -> OllamaProvider:
    return OllamaProvider(base_url=BASE_URL, model=MODEL)


def _mock_client(response: MagicMock) -> MagicMock:
    client = MagicMock()
    client.post.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False
    return context


def test_ollama_provider_is_llm_provider() -> None:
    assert isinstance(_provider(), LLMProvider)


def test_generate_posts_to_ollama_and_returns_text() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"response": "  An API lets programs talk.  "}
    response.raise_for_status = MagicMock()

    with patch("app.llm.ollama.httpx.Client", return_value=_mock_client(response)):
        result = _provider().generate("Explain what an API is in one sentence.")

    assert result == "An API lets programs talk."
    response.raise_for_status.assert_called_once()


def test_generate_uses_configured_model_not_a_hardcoded_name() -> None:
    response = MagicMock()
    response.json.return_value = {"response": "ok"}
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.post.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False

    provider = OllamaProvider(base_url="http://example.local:11434/", model="my-local-model")

    with patch("app.llm.ollama.httpx.Client", return_value=context):
        provider.generate("hello")

    url, kwargs = client.post.call_args
    assert url[0] == "http://example.local:11434/api/generate"
    assert kwargs["json"] == {
        "model": "my-local-model",
        "prompt": "hello",
        "stream": False,
        "think": False,
        "options": {"num_ctx": 16384},
    }


def test_generate_sends_configured_think_value() -> None:
    response = MagicMock()
    response.json.return_value = {"response": "ok"}
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.post.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False

    provider = OllamaProvider(base_url=BASE_URL, model=MODEL, think=True)

    with patch("app.llm.ollama.httpx.Client", return_value=context):
        provider.generate("hello")

    assert client.post.call_args.kwargs["json"]["think"] is True


def test_default_think_is_false() -> None:
    response = MagicMock()
    response.json.return_value = {"response": "ok"}
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.post.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False

    with patch("app.llm.ollama.httpx.Client", return_value=context) as client_cls:
        _provider().generate("hello")

    assert client.post.call_args.kwargs["json"]["think"] is False
    assert client_cls.call_args.kwargs["timeout"].read == 1200.0
    assert client.post.call_args.kwargs["json"]["options"]["num_ctx"] == 16384


def test_timeout_seconds_are_applied_to_httpx_client() -> None:
    response = MagicMock()
    response.json.return_value = {"response": "ok"}
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.post.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False

    provider = OllamaProvider(base_url=BASE_URL, model=MODEL, timeout_seconds=120.0)

    with patch("app.llm.ollama.httpx.Client", return_value=context) as client_cls:
        provider.generate("hello")

    timeout = client_cls.call_args.kwargs["timeout"]
    assert timeout.read == 120.0
    assert timeout.connect == 5.0


def test_unavailable_server_raises_llm_unavailable_error() -> None:
    client = MagicMock()
    client.post.side_effect = httpx.ConnectError("connection refused")
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False

    with patch("app.llm.ollama.httpx.Client", return_value=context):
        with pytest.raises(LLMUnavailableError, match="unavailable"):
            _provider().generate("hello")


def test_timeout_raises_llm_timeout_error() -> None:
    client = MagicMock()
    client.post.side_effect = httpx.ReadTimeout("timed out")
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False

    with patch("app.llm.ollama.httpx.Client", return_value=context):
        with pytest.raises(LLMTimeoutError, match="Timed out"):
            _provider().generate("hello")


def test_http_error_raises_llm_http_error() -> None:
    request = httpx.Request("POST", f"{BASE_URL}/api/generate")
    raw = httpx.Response(
        404,
        json={"error": "model 'configured-model' not found"},
        request=request,
    )

    with patch("app.llm.ollama.httpx.Client", return_value=_mock_client(raw)):
        with pytest.raises(LLMHTTPError, match="not found") as exc_info:
            _provider().generate("hello")

    assert exc_info.value.status_code == 404


def test_non_json_response_raises_llm_response_error() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.side_effect = ValueError("not json")

    with patch("app.llm.ollama.httpx.Client", return_value=_mock_client(response)):
        with pytest.raises(LLMResponseError, match="non-JSON"):
            _provider().generate("hello")


def test_missing_response_field_raises_llm_response_error() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"done": True}

    with patch("app.llm.ollama.httpx.Client", return_value=_mock_client(response)):
        with pytest.raises(LLMResponseError, match="generated text"):
            _provider().generate("hello")


def test_list_payload_raises_llm_response_error() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = ["not", "an", "object"]

    with patch("app.llm.ollama.httpx.Client", return_value=_mock_client(response)):
        with pytest.raises(LLMResponseError, match="unexpected JSON"):
            _provider().generate("hello")
