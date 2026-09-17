"""Live Ollama integration tests.

These tests require a running Ollama server with the configured model.
They are skipped during normal pytest runs.

Enable them with:

    Windows PowerShell:
        $env:RUN_OLLAMA_TESTS = "1"
        pytest tests/integration/test_ollama.py

    Linux/macOS:
        RUN_OLLAMA_TESTS=1 pytest tests/integration/test_ollama.py
"""

import os

import pytest

from app.config import Settings
from app.llm.ollama import OllamaProvider
from app.main import DEV_LLM_PING_PROMPT

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_OLLAMA_TESTS") != "1",
        reason="Live Ollama tests are skipped. Set RUN_OLLAMA_TESTS=1 to enable.",
    ),
]


def test_ollama_generates_a_response() -> None:
    settings = Settings()
    provider = OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        think=settings.ollama_think,
        timeout_seconds=settings.ollama_timeout_seconds,
        num_ctx=settings.ollama_num_ctx,
    )

    result = provider.generate(DEV_LLM_PING_PROMPT)

    assert isinstance(result, str)
    assert result.strip()
