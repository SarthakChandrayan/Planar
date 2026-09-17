import json
from typing import Any

import pytest

from app.analysis import AnalysisValidationError, EmptyTranscriptError, MeetingAnalyzer
from app.analysis.prompts import MEETING_ANALYSIS_INSTRUCTIONS, build_meeting_analysis_prompt
from app.domain import MeetingAnalysis, Priority, Severity
from app.llm import LLMUnavailableError
from app.llm.provider import LLMProvider
from tests.fixtures.payment_meeting import (
    DECISION_MEETING_TRANSCRIPT,
    OPEN_QUESTION_MEETING_TRANSCRIPT,
    PAYMENT_MEETING_TRANSCRIPT,
    REQUIREMENT_MEETING_TRANSCRIPT,
    RISK_MEETING_TRANSCRIPT,
    SUGGESTION_MEETING_TRANSCRIPT,
    TASK_MEETING_TRANSCRIPT,
)


class FakeLLMProvider(LLMProvider):
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.text


class FailingLLMProvider(LLMProvider):
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, prompt: str) -> str:
        raise self.error


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def _empty_analysis(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "decisions": [],
        "requirements": [],
        "tasks": [],
        "risks": [],
        "open_questions": [],
    }
    payload.update(overrides)
    return payload


_CLAIM_SUPPORT_TRANSCRIPT = """
Maya: Postgres is the source of truth for payment idempotency.
Arjun: We'll keep PostgreSQL as the authoritative database for idempotency.
Daniel: If Stripe succeeds but the local database write fails, the customer sees success and we have no local record.
Daniel: Eventually isn't good enough if the customer sees an order stuck in pending.
Priya: One concern is that requests with the same key but different bodies could cause inconsistent behavior.
Omar: add idempotency middleware to POST /v1/charges.
Priya: Should Apple Pay go out with this PaymentIntents rollout, or is that a follow-up?
""".strip()

_IDEMPOTENCY_BODY_EXCERPT = (
    "One concern is that requests with the same key but different bodies "
    "could cause inconsistent behavior."
)
_STRIPE_DB_EXCERPT = (
    "If Stripe succeeds but the local database write fails, the customer "
    "sees success and we have no local record."
)
_WEBHOOK_PENDING_EXCERPT = (
    "Eventually isn't good enough if the customer sees an order stuck in pending."
)
_APPLE_PAY_EXCERPT = (
    "Should Apple Pay go out with this PaymentIntents rollout, or is that a follow-up?"
)
_IDEMPOTENCY_TASK_EXCERPT = "add idempotency middleware to POST /v1/charges."


def test_prompt_states_semantic_rules() -> None:
    prompt = build_meeting_analysis_prompt("short transcript")

    assert "A suggestion is NOT a decision" in MEETING_ANALYSIS_INSTRUCTIONS
    assert "We could use Kafka." in MEETING_ANALYSIS_INSTRUCTIONS
    assert "Maybe we should add Redis." in MEETING_ANALYSIS_INSTRUCTIONS
    assert "Never use \"statement\" on a task" in MEETING_ANALYSIS_INSTRUCTIONS
    assert "source_references" in MEETING_ANALYSIS_INSTRUCTIONS
    assert "short transcript" in prompt
    assert prompt.startswith(MEETING_ANALYSIS_INSTRUCTIONS)


def test_explicit_decisions_are_extracted() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "statement": "Freeze the public checkout API at /v1 until October.",
                "confidence": 0.93,
                "source_reference": {
                    "excerpt": "We will freeze the public checkout API at /v1 until October."
                },
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        DECISION_MEETING_TRANSCRIPT
    )

    assert len(analysis.decisions) == 1
    assert analysis.decisions[0].id == "DEC-001"
    assert "freeze the public checkout api" in analysis.decisions[0].statement.lower()


def test_requirements_are_extracted() -> None:
    payload = _empty_analysis(
        requirements=[
            {
                "statement": "The refund endpoint must reject amounts greater than the original capture.",
                "confidence": 0.9,
                "source_reference": {
                    "excerpt": "The refund endpoint must reject amounts greater than the original capture."
                },
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        REQUIREMENT_MEETING_TRANSCRIPT
    )

    assert analysis.requirements[0].id == "REQ-001"
    assert "reject amounts" in analysis.requirements[0].statement


def test_analyzer_does_not_invent_traceability_links() -> None:
    payload = _empty_analysis(
        requirements=[
            {
                "statement": "The refund endpoint must reject amounts greater than the original capture.",
                "confidence": 0.9,
                "source_reference": {
                    "excerpt": "The refund endpoint must reject amounts greater than the original capture."
                },
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        REQUIREMENT_MEETING_TRANSCRIPT
    )

    assert analysis.requirements[0].related_decision_ids == []
    assert analysis.requirements[0].related_risk_ids == []


def test_engineering_tasks_are_extracted() -> None:
    payload = _empty_analysis(
        tasks=[
            {
                "title": "Implement DLQ consumer for failed captures",
                "description": "Park capture jobs after three failed retries.",
                "priority": "high",
                "acceptance_criteria": [
                    "A failed capture is retried three times then parked."
                ],
                "source_references": [
                    {
                        "excerpt": "Please add a dead-letter queue for failed capture jobs this sprint."
                    }
                ],
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        TASK_MEETING_TRANSCRIPT
    )

    assert analysis.tasks[0].id == "TSK-001"
    assert analysis.tasks[0].priority is Priority.HIGH
    assert analysis.tasks[0].acceptance_criteria


def test_qwen_statement_shaped_tasks_and_questions_are_accepted() -> None:
    payload = _empty_analysis(
        tasks=[
            {
                "statement": "Implement the DLQ consumer for failed captures.",
                "source_reference": {
                    "excerpt": "Please add a dead-letter queue for failed capture jobs this sprint."
                },
            }
        ],
        open_questions=[
            {
                "statement": "Do we still need Braintree after the Stripe cutover?",
                "source_reference": {
                    "excerpt": "Do we still need Braintree after the Stripe cutover, or can we drop it next quarter?"
                },
            }
        ],
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        TASK_MEETING_TRANSCRIPT + "\n" + OPEN_QUESTION_MEETING_TRANSCRIPT
    )

    assert analysis.tasks[0].id == "TSK-001"
    assert analysis.tasks[0].title.startswith("Implement the DLQ")
    assert analysis.tasks[0].priority is Priority.MEDIUM
    assert analysis.open_questions[0].id == "OQ-001"
    assert "Braintree" in analysis.open_questions[0].question


def test_risks_are_extracted() -> None:
    payload = _empty_analysis(
        risks=[
            {
                "description": "Logging raw PANs on declined auths expands PCI scope.",
                "severity": "high",
                "source_reference": {
                    "excerpt": "logging raw PANs on declined auths will expand our PCI scope."
                },
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        RISK_MEETING_TRANSCRIPT
    )

    assert analysis.risks[0].id == "RSK-001"
    assert analysis.risks[0].severity is Severity.HIGH


def test_unresolved_questions_are_extracted() -> None:
    payload = _empty_analysis(
        open_questions=[
            {
                "question": "Do we still need Braintree after the Stripe cutover?",
                "context": "Legal has not answered the contract question.",
                "source_reference": {
                    "excerpt": "Do we still need Braintree after the Stripe cutover, or can we drop it next quarter?"
                },
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        OPEN_QUESTION_MEETING_TRANSCRIPT
    )

    assert analysis.open_questions[0].id == "OQ-001"
    assert "Braintree" in analysis.open_questions[0].question


def test_suggestions_must_not_become_decisions() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "statement": "Settlement cut-off stays at 22:00 UTC.",
                "confidence": 0.95,
                "source_reference": {
                    "excerpt": "Settlement cut-off stays at 22:00 UTC."
                },
            }
        ],
        open_questions=[
            {
                "question": "Should settlement events go on Kafka?",
                "context": "Suggested but not decided.",
                "source_reference": {
                    "excerpt": "We could use Kafka for the settlement event bus."
                },
            },
            {
                "question": "Should idempotency keys be stored in Redis?",
                "context": "Suggested but not accepted.",
                "source_reference": {
                    "excerpt": "Maybe we should add Redis for storing idempotency keys."
                },
            },
        ],
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        SUGGESTION_MEETING_TRANSCRIPT
    )

    decision_text = " ".join(item.statement.lower() for item in analysis.decisions)
    assert "kafka" not in decision_text
    assert "redis" not in decision_text
    assert any("22:00 UTC" in item.statement for item in analysis.decisions)
    assert len(analysis.open_questions) == 2


def test_payment_fixture_analysis_assigns_deterministic_ids() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "id": "ignored-id",
                "statement": "Route all new CNP charges through Stripe PaymentIntents.",
                "confidence": 0.94,
                "source_reference": {
                    "excerpt": "We will route all new card-not-present charges through Stripe PaymentIntents."
                },
            },
            {
                "statement": "Keep settlement cut-off at 22:00 UTC.",
                "confidence": 0.9,
                "source_reference": {
                    "excerpt": "Settlement cut-off stays at 22:00 UTC."
                },
            },
        ],
        requirements=[
            {
                "statement": "POST /v1/charges must honor Idempotency-Key.",
                "confidence": 0.96,
                "source_reference": {
                    "excerpt": "POST /v1/charges must honor an Idempotency-Key header."
                },
            },
            {
                "statement": "Failed captures must return a machine-readable decline_code.",
                "confidence": 0.84,
                "source_reference": {
                    "excerpt": "Failed captures must return a machine-readable decline_code so support is not guessing."
                },
            },
        ],
        tasks=[
            {
                "title": "Add idempotency middleware to POST /v1/charges",
                "description": "Replay or reject duplicate charges using Idempotency-Key.",
                "priority": "high",
                "acceptance_criteria": [
                    "A repeated request with the same key and body returns the original charge.",
                    "A repeated request with the same key and a different body returns HTTP 409.",
                ],
                "source_references": [
                    {
                        "excerpt": "add idempotency middleware to POST /v1/charges."
                    }
                ],
            }
        ],
        risks=[
            {
                "description": "Double-charging if webhook and nightly worker both capture.",
                "severity": "critical",
                "source_reference": {
                    "excerpt": "if the webhook handler and the nightly capture worker both settle the same PaymentIntent, we will double-charge customers."
                },
            }
        ],
        open_questions=[
            {
                "question": "Should Apple Pay ship with this PaymentIntents rollout?",
                "context": "Mobile still uses Braintree for wallets.",
                "source_reference": {
                    "excerpt": "Should Apple Pay go out with this PaymentIntents rollout, or is that a follow-up?"
                },
            }
        ],
    )
    provider = FakeLLMProvider(_json(payload))
    analysis = MeetingAnalyzer(provider).analyze(PAYMENT_MEETING_TRANSCRIPT)

    assert isinstance(analysis, MeetingAnalysis)
    assert [item.id for item in analysis.decisions] == ["DEC-001", "DEC-002"]
    assert [item.id for item in analysis.requirements] == ["REQ-001", "REQ-002"]
    assert analysis.tasks[0].id == "TSK-001"
    assert analysis.risks[0].id == "RSK-001"
    assert analysis.open_questions[0].id == "OQ-001"
    assert PAYMENT_MEETING_TRANSCRIPT in provider.prompts[0]
    assert "Kafka" in PAYMENT_MEETING_TRANSCRIPT


def test_malformed_llm_output_is_rejected() -> None:
    analyzer = MeetingAnalyzer(FakeLLMProvider("this is not json"))

    with pytest.raises(AnalysisValidationError):
        analyzer.analyze(DECISION_MEETING_TRANSCRIPT)


def test_invalid_confidence_is_rejected() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "statement": "Freeze /v1.",
                "confidence": 1.5,
                "source_reference": {
                    "excerpt": "We will freeze the public checkout API at /v1 until October."
                },
            }
        ]
    )
    analyzer = MeetingAnalyzer(FakeLLMProvider(_json(payload)))

    with pytest.raises(AnalysisValidationError):
        analyzer.analyze(DECISION_MEETING_TRANSCRIPT)


def test_missing_required_fields_are_rejected() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "confidence": 0.9,
                "source_reference": {
                    "excerpt": "We will freeze the public checkout API at /v1 until October."
                },
            }
        ]
    )
    analyzer = MeetingAnalyzer(FakeLLMProvider(_json(payload)))

    with pytest.raises(AnalysisValidationError):
        analyzer.analyze(DECISION_MEETING_TRANSCRIPT)


def test_invented_source_excerpt_is_dropped() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "statement": "Freeze the public checkout API at /v1 until October.",
                "confidence": 0.93,
                "source_reference": {
                    "excerpt": "We will freeze the public checkout API at /v1 until October."
                },
            },
            {
                "statement": "Use Kafka.",
                "confidence": 0.9,
                "source_reference": {"excerpt": "We unanimously voted to adopt Kafka today."},
            },
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        DECISION_MEETING_TRANSCRIPT
    )

    assert [item.statement for item in analysis.decisions] == [
        "Freeze the public checkout API at /v1 until October."
    ]
    assert analysis.decisions[0].id == "DEC-001"


def test_all_invented_excerpts_yield_empty_analysis() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "statement": "Use Kafka.",
                "confidence": 0.9,
                "source_reference": {"excerpt": "We unanimously voted to adopt Kafka today."},
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        DECISION_MEETING_TRANSCRIPT
    )

    assert analysis.decisions == []


def test_matching_source_excerpt_is_kept() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "statement": "Postgres is the source of truth for payment idempotency.",
                "confidence": 0.94,
                "source_reference": {
                    "excerpt": "Postgres is the source of truth for payment idempotency."
                },
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        _CLAIM_SUPPORT_TRANSCRIPT
    )

    assert len(analysis.decisions) == 1
    assert analysis.decisions[0].id == "DEC-001"
    assert "postgres" in analysis.decisions[0].statement.lower()


def test_verbatim_but_unrelated_excerpt_is_dropped() -> None:
    payload = _empty_analysis(
        risks=[
            {
                "description": "Stripe succeeds but the local database write fails.",
                "severity": "high",
                "source_reference": {"excerpt": _IDEMPOTENCY_BODY_EXCERPT},
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        _CLAIM_SUPPORT_TRANSCRIPT
    )

    assert analysis.risks == []


def test_mismatched_risk_excerpts_are_dropped() -> None:
    payload = _empty_analysis(
        risks=[
            {
                "description": "Stripe succeeds but the local database write fails.",
                "severity": "high",
                "source_reference": {"excerpt": _IDEMPOTENCY_BODY_EXCERPT},
            },
            {
                "description": (
                    "Asynchronous webhook processing may leave a customer "
                    "order pending."
                ),
                "severity": "medium",
                "source_reference": {"excerpt": _IDEMPOTENCY_BODY_EXCERPT},
            },
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        _CLAIM_SUPPORT_TRANSCRIPT
    )

    assert analysis.risks == []


def test_matching_stripe_db_risk_excerpt_is_kept() -> None:
    payload = _empty_analysis(
        risks=[
            {
                "description": "Stripe succeeds but the local database write fails.",
                "severity": "high",
                "source_reference": {"excerpt": _STRIPE_DB_EXCERPT},
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        _CLAIM_SUPPORT_TRANSCRIPT
    )

    assert len(analysis.risks) == 1
    assert analysis.risks[0].id == "RSK-001"
    assert "stripe" in analysis.risks[0].description.lower()
    assert analysis.risks[0].source_reference.excerpt == _STRIPE_DB_EXCERPT


def test_matching_webhook_risk_excerpt_is_kept() -> None:
    payload = _empty_analysis(
        risks=[
            {
                "description": (
                    "Asynchronous webhook processing may leave a customer "
                    "order pending."
                ),
                "severity": "medium",
                "source_reference": {"excerpt": _WEBHOOK_PENDING_EXCERPT},
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        _CLAIM_SUPPORT_TRANSCRIPT
    )

    assert len(analysis.risks) == 1
    assert analysis.risks[0].id == "RSK-001"
    assert "webhook" in analysis.risks[0].description.lower()
    assert analysis.risks[0].source_reference.excerpt == _WEBHOOK_PENDING_EXCERPT


def test_paraphrase_alias_excerpt_is_kept() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "statement": "Postgres is the source of truth for idempotency.",
                "confidence": 0.91,
                "source_reference": {
                    "excerpt": (
                        "We'll keep PostgreSQL as the authoritative database "
                        "for idempotency."
                    )
                },
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        _CLAIM_SUPPORT_TRANSCRIPT
    )

    assert len(analysis.decisions) == 1
    assert "postgres" in analysis.decisions[0].statement.lower()


def test_task_keeps_only_supporting_source_references() -> None:
    payload = _empty_analysis(
        tasks=[
            {
                "title": "Add idempotency middleware to POST /v1/charges",
                "description": "Replay or reject duplicate charges using Idempotency-Key.",
                "priority": "high",
                "acceptance_criteria": [
                    "A repeated request with the same key and body returns the original charge."
                ],
                "source_references": [
                    {"excerpt": _IDEMPOTENCY_TASK_EXCERPT},
                    {"excerpt": _APPLE_PAY_EXCERPT},
                ],
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        _CLAIM_SUPPORT_TRANSCRIPT
    )

    assert len(analysis.tasks) == 1
    assert analysis.tasks[0].id == "TSK-001"
    assert [ref.excerpt for ref in analysis.tasks[0].source_references] == [
        _IDEMPOTENCY_TASK_EXCERPT
    ]


def test_task_is_dropped_when_all_source_references_are_unsupported() -> None:
    payload = _empty_analysis(
        tasks=[
            {
                "title": "Add idempotency middleware to POST /v1/charges",
                "description": "Replay or reject duplicate charges using Idempotency-Key.",
                "priority": "high",
                "acceptance_criteria": [
                    "A repeated request with the same key and body returns the original charge."
                ],
                "source_references": [{"excerpt": _APPLE_PAY_EXCERPT}],
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        _CLAIM_SUPPORT_TRANSCRIPT
    )

    assert analysis.tasks == []


def test_generic_claim_is_not_dropped_when_support_cannot_be_judged() -> None:
    payload = _empty_analysis(
        decisions=[
            {
                "statement": "Proceed.",
                "confidence": 0.5,
                "source_reference": {"excerpt": _IDEMPOTENCY_BODY_EXCERPT},
            }
        ]
    )
    analysis = MeetingAnalyzer(FakeLLMProvider(_json(payload))).analyze(
        _CLAIM_SUPPORT_TRANSCRIPT
    )

    assert len(analysis.decisions) == 1
    assert analysis.decisions[0].statement == "Proceed."


def test_empty_transcript_is_rejected() -> None:
    analyzer = MeetingAnalyzer(FakeLLMProvider("{}"))

    with pytest.raises(EmptyTranscriptError):
        analyzer.analyze("   ")


def test_llm_provider_failure_is_propagated() -> None:
    analyzer = MeetingAnalyzer(
        FailingLLMProvider(LLMUnavailableError("Ollama server is unavailable."))
    )

    with pytest.raises(LLMUnavailableError):
        analyzer.analyze(DECISION_MEETING_TRANSCRIPT)


def test_analyzer_depends_on_llm_provider_not_ollama() -> None:
    from app.analysis.analyzer import MeetingAnalyzer as Analyzer
    import inspect

    source = inspect.getsource(Analyzer)
    assert "OllamaProvider" not in source
    assert "LLMProvider" in source
