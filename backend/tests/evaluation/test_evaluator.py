"""Unit tests for the deterministic MeetingAnalysis evaluator. No Ollama."""

from app.domain.enums import Priority, Severity
from app.domain.models import (
    Decision,
    MeetingAnalysis,
    OpenQuestion,
    Requirement,
    Risk,
    SourceReference,
    Task,
)
from tests.evaluation.evaluator import evaluate
from tests.evaluation.payment_platform_redesign_expected import (
    PAYMENT_PLATFORM_REDESIGN_GOLDEN,
)

_REF = SourceReference(excerpt="Quoted from the meeting transcript.")


def _decision(item_id: str, statement: str) -> Decision:
    return Decision(
        id=item_id,
        statement=statement,
        confidence=0.9,
        source_reference=_REF,
    )


def _requirement(item_id: str, statement: str) -> Requirement:
    return Requirement(
        id=item_id,
        statement=statement,
        confidence=0.9,
        source_reference=_REF,
    )


def _task(item_id: str, title: str, description: str, *, with_source: bool = True) -> Task:
    return Task(
        id=item_id,
        title=title,
        description=description,
        priority=Priority.HIGH,
        source_references=[_REF] if with_source else [],
    )


def _risk(item_id: str, description: str) -> Risk:
    return Risk(
        id=item_id,
        description=description,
        severity=Severity.HIGH,
        source_reference=_REF,
    )


def _question(item_id: str, question: str, context: str) -> OpenQuestion:
    return OpenQuestion(
        id=item_id,
        question=question,
        context=context,
        source_reference=_REF,
    )


def _good_analysis() -> MeetingAnalysis:
    return MeetingAnalysis(
        decisions=[
            _decision(
                "DEC-001",
                "Use Postgres as the source of truth for idempotency keys.",
            ),
            _decision(
                "DEC-002",
                "Stripe PaymentIntents for card payments in November.",
            ),
            _decision(
                "DEC-003",
                "Do not introduce Kafka; process webhooks asynchronously with existing SQS.",
            ),
        ],
        requirements=[
            _requirement(
                "REQ-001",
                "Expose GET /payments/{id} so the backend can return payment status.",
            ),
            _requirement(
                "REQ-002",
                "Same idempotency key plus same merchant account should return the original result.",
            ),
        ],
        tasks=[
            _task(
                "TSK-001",
                "Implement the SQS consumer",
                "Arjun will implement the webhook consumer on existing SQS.",
            ),
        ],
        risks=[
            _risk(
                "RSK-001",
                "If Stripe returns success but our database write fails, payment state is wrong until webhooks reconcile.",
            ),
        ],
        open_questions=[
            _question(
                "OQ-001",
                "What is the webhook retention period?",
                "This is an open question until compliance confirms it.",
            ),
        ],
    )


def _unexpected_ids(result) -> list[str]:
    return [item.id for item in result.unexpected_artifacts]


def _forbidden_ids(result, key: str) -> list[str]:
    return [item.artifact_id for item in result.forbidden_violations if item.forbidden_key == key]


def test_good_analysis_matches_expected_artifacts() -> None:
    result = evaluate(_good_analysis(), PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC_POSTGRES_IDEMPOTENCY_SOURCE_OF_TRUTH" in result.matched_expected_keys
    assert "DEC_STRIPE_PAYMENT_INTENTS_NOVEMBER" in result.matched_expected_keys
    assert "REQ_GET_PAYMENTS_BY_ID" in result.matched_expected_keys
    assert "TSK_IMPLEMENT_SQS_WEBHOOK_CONSUMER" in result.matched_expected_keys
    assert "RSK_STRIPE_SUCCESS_DB_WRITE_FAILURE" in result.matched_expected_keys
    assert "OQ_WEBHOOK_RETENTION_PENDING_COMPLIANCE" in result.matched_expected_keys
    assert result.matched_expected >= 6
    assert result.forbidden_violations == []
    assert result.overall_score > 0


def test_missing_expected_decision_is_detected() -> None:
    analysis = _good_analysis()
    analysis.decisions = [
        item
        for item in analysis.decisions
        if "Postgres" not in item.statement
    ]
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC_POSTGRES_IDEMPOTENCY_SOURCE_OF_TRUTH" in result.missed_expected_keys


def test_unexpected_artifact_is_detected() -> None:
    analysis = _good_analysis()
    analysis.decisions.append(
        _decision("DEC-099", "Paint the office walls before the November launch.")
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC-099" in _unexpected_ids(result)


def test_kafka_promoted_as_decision_is_forbidden() -> None:
    analysis = _good_analysis()
    analysis.decisions.append(
        _decision("DEC-080", "We will use Kafka for the webhook event bus.")
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC-080" in _forbidden_ids(result, "FORBID_KAFKA")


def test_redis_promoted_as_risk_is_forbidden() -> None:
    analysis = _good_analysis()
    analysis.risks.append(
        _risk(
            "RSK-080",
            "We should use Redis as the source of truth for payment idempotency.",
        )
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "RSK-080" in _forbidden_ids(result, "FORBID_REDIS_IDEMPOTENCY_SOURCE_OF_TRUTH")


def test_apple_pay_november_requirement_is_forbidden() -> None:
    analysis = _good_analysis()
    analysis.requirements.append(
        _requirement(
            "REQ-080",
            "Apple Pay must be supported in the November checkout release.",
        )
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "REQ-080" in _forbidden_ids(result, "FORBID_APPLE_PAY_NOVEMBER_REQUIREMENT")


def test_missing_task_source_references_are_detected() -> None:
    analysis = _good_analysis()
    analysis.tasks.append(
        _task(
            "TSK-080",
            "Mystery work",
            "A task with no transcript excerpt.",
            with_source=False,
        )
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    missing_ids = [item.artifact_id for item in result.missing_source_references]
    assert "TSK-080" in missing_ids


def test_score_drops_when_coverage_falls_or_violations_are_added() -> None:
    good = evaluate(_good_analysis(), PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    missing_postgres = _good_analysis()
    missing_postgres.decisions = [
        item
        for item in missing_postgres.decisions
        if "Postgres" not in item.statement
    ]
    worse_coverage = evaluate(missing_postgres, PAYMENT_PLATFORM_REDESIGN_GOLDEN)
    assert worse_coverage.overall_score < good.overall_score

    with_kafka = _good_analysis()
    with_kafka.decisions.append(
        _decision("DEC-081", "Adopt Kafka as the payment event bus.")
    )
    worse_forbidden = evaluate(with_kafka, PAYMENT_PLATFORM_REDESIGN_GOLDEN)
    assert worse_forbidden.overall_score < good.overall_score

    with_unexpected = _good_analysis()
    with_unexpected.open_questions.append(
        _question("OQ-099", "Should we rewrite the billing UI in Rust?", "Unrelated.")
    )
    worse_unexpected = evaluate(with_unexpected, PAYMENT_PLATFORM_REDESIGN_GOLDEN)
    assert worse_unexpected.overall_score < good.overall_score


def test_state_transitions_requirement_matches_internal_state_machine() -> None:
    analysis = MeetingAnalysis(
        requirements=[
            _requirement(
                "REQ-002",
                "Payment state transitions must be modeled explicitly.",
            )
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC_INTERNAL_STATE_MACHINE_SEPARATE_FROM_STRIPE" in result.matched_expected_keys
    assert "REQ-002" not in _unexpected_ids(result)


def test_rollout_threshold_question_matches_expected_open_question() -> None:
    analysis = MeetingAnalysis(
        open_questions=[
            _question(
                "OQ-001",
                "What counts as normal for rollout thresholds?",
                "Payment creation success rate, webhook processing latency, and checkout conversion.",
            )
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "OQ_ROLLOUT_THRESHOLDS_NOT_FINAL" in result.matched_expected_keys
    assert "OQ-001" not in _unexpected_ids(result)


def test_audit_task_matches_and_is_not_also_unexpected() -> None:
    analysis = MeetingAnalysis(
        tasks=[
            _task(
                "TSK-002",
                "Implement webhook verification and processing",
                "Verify webhook signatures, persist events to Postgres, and process asynchronously using SQS.",
            ),
            _task(
                "TSK-003",
                "Audit existing checkout state transitions",
                "Review and update existing checkout state transitions to account for asynchronous processing.",
            ),
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "TSK_AUDIT_CHECKOUT_STATE_TRANSITIONS" in result.matched_expected_keys
    assert "TSK-003" not in _unexpected_ids(result)


def test_unrelated_artifact_is_still_unexpected() -> None:
    analysis = MeetingAnalysis(
        decisions=[
            _decision("DEC-099", "Paint the office walls before the November launch.")
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC-099" in _unexpected_ids(result)


def test_use_kafka_for_webhooks_is_forbidden() -> None:
    analysis = MeetingAnalysis(
        decisions=[_decision("DEC-080", "Use Kafka for webhook processing.")]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC-080" in _forbidden_ids(result, "FORBID_KAFKA")


def test_rejected_kafka_with_sqs_is_not_forbidden() -> None:
    analysis = MeetingAnalysis(
        decisions=[
            _decision("DEC-081", "Kafka was rejected; use SQS instead.")
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC-081" not in _forbidden_ids(result, "FORBID_KAFKA")
    assert result.forbidden_violations == []


def test_use_redis_as_idempotency_source_of_truth_is_forbidden() -> None:
    analysis = MeetingAnalysis(
        decisions=[
            _decision(
                "DEC-082",
                "Use Redis as the source of truth for idempotency.",
            )
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC-082" in _forbidden_ids(
        result, "FORBID_REDIS_IDEMPOTENCY_SOURCE_OF_TRUTH"
    )


def test_redis_rejected_in_favor_of_postgres_is_not_forbidden() -> None:
    analysis = MeetingAnalysis(
        decisions=[
            _decision("DEC-083", "Redis was rejected in favor of Postgres.")
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert result.forbidden_violations == []


def test_apple_pay_out_of_scope_is_not_forbidden() -> None:
    analysis = MeetingAnalysis(
        requirements=[
            _requirement(
                "REQ-081",
                "Apple Pay is still out of scope for November.",
            )
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "REQ-081" not in _forbidden_ids(
        result, "FORBID_APPLE_PAY_NOVEMBER_REQUIREMENT"
    )
    assert result.forbidden_violations == []


def test_missing_source_reference_is_still_detected() -> None:
    analysis = MeetingAnalysis(
        tasks=[
            _task(
                "TSK-080",
                "Mystery work",
                "A task with no transcript excerpt.",
                with_source=False,
            )
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    missing_ids = [item.artifact_id for item in result.missing_source_references]
    assert "TSK-080" in missing_ids


def test_score_decreases_when_expected_artifacts_are_removed() -> None:
    full = evaluate(_good_analysis(), PAYMENT_PLATFORM_REDESIGN_GOLDEN)
    missing_postgres = _good_analysis()
    missing_postgres.decisions = [
        item
        for item in missing_postgres.decisions
        if "Postgres" not in item.statement
    ]
    reduced = evaluate(missing_postgres, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert reduced.matched_expected < full.matched_expected
    assert reduced.overall_score < full.overall_score


def test_score_decreases_when_forbidden_concepts_are_promoted() -> None:
    baseline = evaluate(_good_analysis(), PAYMENT_PLATFORM_REDESIGN_GOLDEN)
    with_kafka = _good_analysis()
    with_kafka.decisions.append(
        _decision("DEC-084", "Use Kafka for webhook processing.")
    )
    worse = evaluate(with_kafka, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert worse.forbidden_violations
    assert worse.overall_score < baseline.overall_score


def _family(result, key: str):
    for item in result.family_results:
        if item.key == key:
            return item
    raise AssertionError(f"Missing family {key}")


def test_checkout_architecture_family_fully_covered_by_overlapping_decision() -> None:
    analysis = MeetingAnalysis(
        decisions=[
            _decision(
                "DEC-001",
                "Do not create a separate payment microservice for November. "
                "Implement payments as an isolated module within checkout.",
            )
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    family = _family(result, "CHECKOUT_ARCHITECTURE")
    assert family.status == "matched"
    assert "CHECKOUT_ARCHITECTURE" in result.matched_families
    assert family.satisfied_core_groups == family.total_core_groups
    assert result.family_coverage_score > 0


def test_idempotency_family_fully_covered() -> None:
    analysis = MeetingAnalysis(
        decisions=[
            _decision(
                "DEC-001",
                "Use Postgres as the source of truth for idempotency keys.",
            )
        ],
        requirements=[
            _requirement(
                "REQ-001",
                "The backend must recognize duplicate payment creation; we cannot rely on frontend behavior.",
            ),
            _requirement(
                "REQ-002",
                "Same idempotency key plus same merchant account should return the original result.",
            ),
            _requirement(
                "REQ-003",
                "Same idempotency key with a different request body must be rejected.",
            ),
        ],
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    family = _family(result, "IDEMPOTENCY")
    assert family.status == "matched"
    assert "IDEMPOTENCY" in result.matched_families


def test_idempotency_family_partially_covered_by_postgres_only() -> None:
    analysis = MeetingAnalysis(
        decisions=[
            _decision(
                "DEC-001",
                "Use Postgres as the source of truth for idempotency keys.",
            )
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    family = _family(result, "IDEMPOTENCY")
    assert family.status == "partial"
    assert family.satisfied_core_groups == 1
    assert family.total_core_groups == 4
    assert "IDEMPOTENCY" in result.partial_families
    assert "IDEMPOTENCY" not in result.matched_families
    assert "IDEMPOTENCY" not in result.missed_families


def test_idempotency_family_missed_when_unrelated() -> None:
    analysis = MeetingAnalysis(
        decisions=[
            _decision("DEC-099", "Paint the office walls before the November launch.")
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    family = _family(result, "IDEMPOTENCY")
    assert family.status == "missed"
    assert "IDEMPOTENCY" in result.missed_families


def test_semantically_equivalent_artifact_covers_state_machine_family_core() -> None:
    analysis = MeetingAnalysis(
        requirements=[
            _requirement(
                "REQ-002",
                "Payment state transitions must be modeled explicitly.",
            )
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "DEC_INTERNAL_STATE_MACHINE_SEPARATE_FROM_STRIPE" in result.matched_expected_keys
    family = _family(result, "PAYMENT_STATE_MODEL")
    assert family.satisfied_core_groups >= 1
    assert family.status in {"partial", "matched"}
    assert "DEC_INTERNAL_STATE_MACHINE_SEPARATE_FROM_STRIPE" in family.matched_artifact_keys


def test_overlapping_persist_requirement_does_not_miss_idempotency_family() -> None:
    analysis = MeetingAnalysis(
        requirements=[
            _requirement(
                "REQ-001",
                "Persist the idempotency key with the payment record.",
            )
        ]
    )
    result = evaluate(analysis, PAYMENT_PLATFORM_REDESIGN_GOLDEN)

    assert "REQ_PERSIST_IDEMPOTENCY_KEYS" in result.matched_expected_keys
    family = _family(result, "IDEMPOTENCY")
    assert family.status == "partial"
    assert family.satisfied_core_groups == 1
    assert "IDEMPOTENCY" not in result.missed_families
    assert result.family_coverage_score > 0

