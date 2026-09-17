from typing import Any

import httpx

from app.llm.exceptions import (
    LLMHTTPError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.provider import LLMProvider

_CONNECT_TIMEOUT_SECONDS = 5.0
_WRITE_TIMEOUT_SECONDS = 30.0
_POOL_TIMEOUT_SECONDS = 5.0
DEFAULT_TIMEOUT_SECONDS = 1200.0
DEFAULT_NUM_CTX = 16384


def _read_timeout(timeout_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(
        connect=_CONNECT_TIMEOUT_SECONDS,
        read=timeout_seconds,
        write=_WRITE_TIMEOUT_SECONDS,
        pool=_POOL_TIMEOUT_SECONDS,
    )


class OllamaProvider(LLMProvider):
    """LLMProvider that calls a local Ollama HTTP API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        think: bool = False,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        num_ctx: int = DEFAULT_NUM_CTX,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._think = think
        self._num_ctx = num_ctx
        self._timeout = timeout or _read_timeout(timeout_seconds)

    def generate(self, prompt: str) -> str:
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "think": self._think,
            "options": {"num_ctx": self._num_ctx},
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Timed out waiting for Ollama at {self._base_url}."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError(
                f"Ollama server is unavailable at {self._base_url}."
            ) from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = _http_error_message(exc.response)
            raise LLMHTTPError(message, status_code=exc.response.status_code) from exc

        try:
            body: Any = response.json()
        except ValueError as exc:
            raise LLMResponseError("Ollama returned a non-JSON response.") from exc

        return _parse_generate_response(body)


def _http_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"Ollama HTTP {response.status_code}."

    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    return f"Ollama HTTP {response.status_code}."


def _parse_generate_response(body: Any) -> str:
    if not isinstance(body, dict):
        raise LLMResponseError("Ollama returned an unexpected JSON response.")

    text = body.get("response")
    if not isinstance(text, str):
        raise LLMResponseError("Ollama response did not include generated text.")

    return text.strip()
