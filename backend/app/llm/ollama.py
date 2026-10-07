import json
import logging
from typing import Any

import httpx

from app.llm.exceptions import (
    LLMHTTPError,
    LLMOutputTruncatedError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.provider import LLMProvider, TokenCallback

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_SECONDS = 5.0
_WRITE_TIMEOUT_SECONDS = 30.0
_POOL_TIMEOUT_SECONDS = 5.0
_READY_TIMEOUT_SECONDS = 5.0
# Loading an 8B model from a slow disk can take a minute or more.
_WARM_UP_TIMEOUT_SECONDS = 300.0
DEFAULT_TIMEOUT_SECONDS = 1200.0
DEFAULT_NUM_CTX = 16384
_NANOS = 1_000_000_000


def _read_timeout(timeout_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(
        connect=_CONNECT_TIMEOUT_SECONDS,
        read=timeout_seconds,
        write=_WRITE_TIMEOUT_SECONDS,
        pool=_POOL_TIMEOUT_SECONDS,
    )


class OllamaProvider(LLMProvider):
    """LLMProvider that streams from a local Ollama HTTP API.

    Streaming keeps the connection alive during long CPU generations: the
    read timeout applies between tokens, not to the whole response.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        think: bool = False,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        num_ctx: int = DEFAULT_NUM_CTX,
        temperature: float = 0.0,
        seed: int | None = 42,
        max_output_tokens: int | None = None,
        keep_alive: str | None = "30m",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._think = think
        self._num_ctx = num_ctx
        self._temperature = temperature
        self._seed = seed
        self._max_output_tokens = max_output_tokens
        self._keep_alive = keep_alive
        self._timeout = _read_timeout(timeout_seconds)
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    def _client(self, timeout: httpx.Timeout | float) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self._transport)

    def build_payload(
        self, prompt: str, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "num_ctx": self._num_ctx,
            "temperature": self._temperature,
        }
        if self._seed is not None:
            options["seed"] = self._seed
        if self._max_output_tokens is not None:
            options["num_predict"] = self._max_output_tokens
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": True,
            "think": self._think,
            "options": options,
        }
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        if schema is not None:
            payload["format"] = schema
        return payload

    def generate(
        self,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        on_tokens: TokenCallback | None = None,
    ) -> str:
        url = f"{self._base_url}/api/generate"
        payload = self.build_payload(prompt, schema)
        parts: list[str] = []
        final: dict[str, Any] = {}
        tokens = 0

        try:
            with self._client(self._timeout) as client:
                with client.stream("POST", url, json=payload) as response:
                    if response.status_code >= 400:
                        response.read()
                        raise LLMHTTPError(
                            _http_error_message(response),
                            status_code=response.status_code,
                        )
                    for line in response.iter_lines():
                        if not line.strip():
                            continue
                        chunk = _parse_stream_line(line)
                        if chunk.get("done"):
                            final = chunk
                            break
                        text = chunk.get("response")
                        if isinstance(text, str) and text:
                            parts.append(text)
                            tokens += 1
                            if on_tokens is not None:
                                on_tokens(tokens)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Timed out waiting for Ollama at {self._base_url}."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError(
                f"Ollama server is unavailable at {self._base_url}."
            ) from exc

        if not final:
            raise LLMResponseError("Ollama stream ended before completion.")
        _log_stats(final, self._model)
        if final.get("done_reason") == "length":
            raise LLMOutputTruncatedError(
                "The model hit the output token limit before finishing."
            )
        return "".join(parts).strip()

    def warm_up(self) -> None:
        """Ask Ollama to load the model now (a request with no prompt does only that)."""
        payload: dict[str, Any] = {"model": self._model}
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        try:
            with self._client(_WARM_UP_TIMEOUT_SECONDS) as client:
                response = client.post(f"{self._base_url}/api/generate", json=payload)
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(
                f"Ollama is not reachable at {self._base_url}."
            ) from exc
        if response.status_code >= 400:
            raise LLMHTTPError(_http_error_message(response), status_code=response.status_code)
        logger.info("llm_warm_up model=%s", self._model)

    def check_ready(self) -> None:
        try:
            with self._client(_READY_TIMEOUT_SECONDS) as client:
                response = client.get(f"{self._base_url}/api/tags")
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(
                f"Ollama is not reachable at {self._base_url}. Start Ollama and retry."
            ) from exc
        if response.status_code >= 400:
            raise LLMHTTPError(
                _http_error_message(response), status_code=response.status_code
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMResponseError("Ollama returned a non-JSON response.") from exc
        installed = {
            str(model.get("name") or model.get("model"))
            for model in (body.get("models") or [])
            if isinstance(model, dict)
        }
        if not _model_installed(self._model, installed):
            raise LLMUnavailableError(
                f"Model '{self._model}' is not installed in Ollama. "
                f"Run: ollama pull {self._model}"
            )


def _model_installed(model: str, installed: set[str]) -> bool:
    if model in installed:
        return True
    if ":" not in model:
        return f"{model}:latest" in installed
    return False


def _parse_stream_line(line: str) -> dict[str, Any]:
    try:
        chunk = json.loads(line)
    except ValueError as exc:
        raise LLMResponseError("Ollama returned a non-JSON stream chunk.") from exc
    if not isinstance(chunk, dict):
        raise LLMResponseError("Ollama returned an unexpected JSON response.")
    if chunk.get("error"):
        raise LLMResponseError(f"Ollama error: {chunk['error']}")
    return chunk


def _log_stats(final: dict[str, Any], model: str) -> None:
    def seconds(key: str) -> float:
        value = final.get(key)
        return value / _NANOS if isinstance(value, (int, float)) else 0.0

    logger.info(
        "llm_generation model=%s prompt_tokens=%s prompt_s=%.1f "
        "output_tokens=%s output_s=%.1f load_s=%.1f total_s=%.1f done_reason=%s",
        model,
        final.get("prompt_eval_count"),
        seconds("prompt_eval_duration"),
        final.get("eval_count"),
        seconds("eval_duration"),
        seconds("load_duration"),
        seconds("total_duration"),
        final.get("done_reason"),
    )


def _http_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"Ollama HTTP {response.status_code}."

    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    return f"Ollama HTTP {response.status_code}."
