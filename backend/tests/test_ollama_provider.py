import json
from collections.abc import Callable

import httpx
import pytest

from app.llm.exceptions import (
    LLMHTTPError,
    LLMOutputTruncatedError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.ollama import OllamaProvider
from app.llm.provider import LLMProvider

BASE_URL = "http://localhost:11434"


def _stream(*chunks: dict) -> bytes:
    return "\n".join(json.dumps(chunk) for chunk in chunks).encode()


def _provider(
    handler: Callable[[httpx.Request], httpx.Response], **kwargs
) -> OllamaProvider:
    options = {"base_url": BASE_URL, "model": "configured-model"} | kwargs
    return OllamaProvider(**options, transport=httpx.MockTransport(handler))


def _ok_stream(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        content=_stream(
            {"response": " An API ", "done": False},
            {"response": "lets programs talk. ", "done": False},
            {"response": "", "done": True, "done_reason": "stop", "eval_count": 2},
        ),
    )


def test_ollama_provider_is_llm_provider() -> None:
    assert isinstance(_provider(_ok_stream), LLMProvider)


def test_generate_streams_and_joins_text() -> None:
    counts: list[int] = []
    result = _provider(_ok_stream).generate("hi", on_tokens=counts.append)
    assert result == "An API lets programs talk."
    assert counts == [1, 2]


def test_payload_has_model_schema_and_deterministic_options() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return _ok_stream(request)

    provider = _provider(
        handler,
        base_url="http://example.local:11434/",
        model="my-local-model",
        num_ctx=8192,
        temperature=0.0,
        seed=7,
        max_output_tokens=512,
        keep_alive="10m",
    )
    provider.generate("hello", schema={"type": "object"})

    assert seen["url"] == "http://example.local:11434/api/generate"
    assert seen["body"] == {
        "model": "my-local-model",
        "prompt": "hello",
        "stream": True,
        "think": False,
        "keep_alive": "10m",
        "format": {"type": "object"},
        "options": {"num_ctx": 8192, "temperature": 0.0, "seed": 7, "num_predict": 512},
    }


def test_think_flag_is_sent() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _ok_stream(request)

    _provider(handler, think=True).generate("x")
    assert seen["think"] is True


def test_token_callback_can_abort() -> None:
    class Stop(Exception):
        pass

    def stop(_count: int) -> None:
        raise Stop()

    with pytest.raises(Stop):
        _provider(_ok_stream).generate("x", on_tokens=stop)


def test_length_stop_raises_truncated_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_stream({"response": "{", "done": False}, {"done": True, "done_reason": "length"}),
        )

    with pytest.raises(LLMOutputTruncatedError):
        _provider(handler).generate("x")


def test_stream_error_chunk_raises_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_stream({"error": "model crashed"}))

    with pytest.raises(LLMResponseError, match="model crashed"):
        _provider(handler).generate("x")


def test_stream_without_done_raises_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_stream({"response": "half", "done": False}))

    with pytest.raises(LLMResponseError):
        _provider(handler).generate("x")


def test_non_json_stream_raises_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>proxy</html>")

    with pytest.raises(LLMResponseError):
        _provider(handler).generate("x")


def test_http_error_raises_llm_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'x' not found"})

    with pytest.raises(LLMHTTPError) as caught:
        _provider(handler).generate("x")
    assert caught.value.status_code == 404
    assert str(caught.value) == "model 'x' not found"


def test_unreachable_server_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMUnavailableError):
        _provider(handler).generate("x")


def test_timeout_raises_llm_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMTimeoutError):
        _provider(handler).generate("x")


def _tags(*names: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": n} for n in names]})

    return handler


def test_check_ready_passes_when_model_installed() -> None:
    _provider(_tags("configured-model", "other:1b")).check_ready()
    _provider(_tags("llama3:latest"), model="llama3").check_ready()


def test_check_ready_names_the_missing_model() -> None:
    with pytest.raises(LLMUnavailableError, match="ollama pull qwen3:8b"):
        _provider(_tags("qwen3:4b"), model="qwen3:8b").check_ready()


def test_check_ready_reports_unreachable_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMUnavailableError, match="not reachable"):
        _provider(handler).check_ready()


def test_warm_up_loads_the_model_without_a_prompt() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"done": True})

    _provider(handler, keep_alive="30m").warm_up()
    assert seen == {"path": "/api/generate", "body": {"model": "configured-model", "keep_alive": "30m"}}


def test_warm_up_reports_unreachable_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMUnavailableError):
        _provider(handler).warm_up()
