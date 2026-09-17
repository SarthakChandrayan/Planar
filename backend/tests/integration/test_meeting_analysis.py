"""Live meeting-analysis integration tests.

Requires a running Ollama server with the configured model.
Skipped during normal pytest runs.

Enable with:

    Windows PowerShell:
        $env:RUN_OLLAMA_TESTS = "1"
        pytest tests/integration/test_meeting_analysis.py

    Linux/macOS:
        RUN_OLLAMA_TESTS=1 pytest tests/integration/test_meeting_analysis.py
"""

import json
import os
from pathlib import Path

import pytest

from app.analysis import MeetingAnalyzer
from app.config import Settings
from app.llm.ollama import OllamaProvider
from tests.fixtures.payment_meeting import PAYMENT_MEETING_TRANSCRIPT
from tests.fixtures.payment_platform_redesign import PAYMENT_PLATFORM_REDESIGN_TRANSCRIPT

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_OLLAMA_TESTS") != "1",
        reason="Live Ollama tests are skipped. Set RUN_OLLAMA_TESTS=1 to enable.",
    ),
]

_OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "output" / "large_meeting_analysis_result.json"
)


def test_payment_meeting_analysis_against_local_ollama() -> None:
    settings = Settings()
    analyzer = MeetingAnalyzer(
            OllamaProvider(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                think=settings.ollama_think,
                timeout_seconds=settings.ollama_timeout_seconds,
                num_ctx=settings.ollama_num_ctx,
            )
    )

    analysis = analyzer.analyze(PAYMENT_MEETING_TRANSCRIPT)

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(
        json.dumps(analysis.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )

    assert analysis.decisions
    assert analysis.requirements
    assert analysis.tasks
    assert analysis.risks
    assert analysis.open_questions
    assert analysis.decisions[0].id == "DEC-001"

    decision_text = " ".join(item.statement.lower() for item in analysis.decisions)
    assert "kafka" not in decision_text
    assert "redis" not in decision_text


_REDESIGN_OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "output"
    / "payment_platform_redesign_analysis_result.json"
)


def test_payment_platform_redesign_analysis_against_local_ollama() -> None:
    settings = Settings()
    analyzer = MeetingAnalyzer(
        OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            think=settings.ollama_think,
            timeout_seconds=settings.ollama_timeout_seconds,
            num_ctx=settings.ollama_num_ctx,
        )
    )

    assert "Meeting: Payment Platform Redesign" in PAYMENT_PLATFORM_REDESIGN_TRANSCRIPT
    assert "We need to lock the card-not-present path today." not in PAYMENT_PLATFORM_REDESIGN_TRANSCRIPT
    assert "Settlement cut-off stays at 22:00 UTC." not in PAYMENT_PLATFORM_REDESIGN_TRANSCRIPT

    analysis = analyzer.analyze(PAYMENT_PLATFORM_REDESIGN_TRANSCRIPT)

    _REDESIGN_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REDESIGN_OUTPUT_PATH.write_text(
        json.dumps(analysis.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )

    assert analysis.decisions
    assert analysis.requirements
    assert analysis.tasks
    assert analysis.risks
    assert analysis.open_questions
