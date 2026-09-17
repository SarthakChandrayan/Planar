import json

import pytest
from pydantic import ValidationError

from app.domain import (
    DEC_PREFIX,
    Decision,
    ImplementationPlan,
    ImplementationPlanStep,
    MeetingAnalysis,
    OpenQuestion,
    Priority,
    Requirement,
    Risk,
    Severity,
    SourceReference,
    Task,
    format_item_id,
)


def _ref(excerpt: str = "We agreed to keep card data in the existing vault.") -> SourceReference:
    return SourceReference(excerpt=excerpt)


def _decision(**overrides: object) -> Decision:
    data: dict[str, object] = {
        "id": format_item_id(DEC_PREFIX, 1),
        "statement": "Use the existing payment vault for PAN storage.",
        "confidence": 0.91,
        "source_reference": _ref(),
    }
    data.update(overrides)
    return Decision.model_validate(data)


def payment_system_analysis() -> MeetingAnalysis:
    return MeetingAnalysis(
        decisions=[
            Decision(
                id="DEC-001",
                statement="Route all new card-not-present charges through Stripe PaymentIntents.",
                confidence=0.94,
                source_reference=SourceReference(
                    excerpt="Decision: PaymentIntents is the only supported CNP path going forward."
                ),
            ),
            Decision(
                id="DEC-002",
                statement="Keep the current settlement cut-off at 22:00 UTC.",
                confidence=0.88,
                source_reference=SourceReference(
                    excerpt="We are not moving settlement off 22:00 UTC this quarter."
                ),
            ),
        ],
        requirements=[
            Requirement(
                id="REQ-001",
                statement="The checkout API must support idempotent charge creation via Idempotency-Key.",
                confidence=0.96,
                source_reference=SourceReference(
                    excerpt="Checkout retries are already happening; we need Idempotency-Key on /charges."
                ),
            ),
            Requirement(
                id="REQ-002",
                statement="Failed captures must surface a machine-readable decline_code to the client.",
                confidence=0.83,
                source_reference=SourceReference(
                    excerpt="Support needs decline_code, not just a generic payment failed message."
                ),
            ),
        ],
        tasks=[
            Task(
                id="TSK-001",
                title="Add idempotency middleware to POST /v1/charges",
                description="Reject or replay duplicate charge requests that share an Idempotency-Key within 24 hours.",
                priority=Priority.HIGH,
                acceptance_criteria=[
                    "A repeated request with the same key and body returns the original charge.",
                    "A repeated request with the same key and a different body returns HTTP 409.",
                    "Keys expire after 24 hours and new requests are processed normally.",
                ],
                source_references=[
                    SourceReference(
                        excerpt="Checkout retries are already happening; we need Idempotency-Key on /charges."
                    ),
                    SourceReference(
                        excerpt="If the payload changes under the same key, fail it loudly."
                    ),
                ],
            ),
            Task(
                id="TSK-002",
                title="Document capture decline codes",
                description="Publish the decline_code list used by the capture worker so clients can map errors.",
                priority=Priority.MEDIUM,
                acceptance_criteria=[
                    "The public docs include every decline_code emitted in production last 90 days."
                ],
            ),
        ],
        risks=[
            Risk(
                id="RSK-001",
                description="Double-charging customers if webhooks and the capture worker both settle a PaymentIntent.",
                severity=Severity.CRITICAL,
                source_reference=SourceReference(
                    excerpt="We still have two writers on capture: webhook handler and the nightly worker."
                ),
            ),
            Risk(
                id="RSK-002",
                description="PCI scope expands if logs include full PAN on declined auth retries.",
                severity=Severity.HIGH,
                source_reference=SourceReference(
                    excerpt="Someone pasted a declined PAN into the staging logs last week."
                ),
            ),
        ],
        open_questions=[
            OpenQuestion(
                id="OQ-001",
                question="Should Apple Pay be in the same PaymentIntents rollout or a follow-up?",
                context="Mobile still uses a separate Braintree token flow; product wants one wallet story.",
                source_reference=SourceReference(
                    excerpt="Do we fold Apple Pay into this Stripe cutover or leave Braintree for wallets?"
                ),
            )
        ],
    )


def test_valid_decision() -> None:
    decision = _decision()

    assert decision.id == "DEC-001"
    assert decision.confidence == 0.91
    assert decision.source_reference.excerpt.startswith("We agreed")


def test_valid_requirement() -> None:
    requirement = Requirement(
        id="REQ-001",
        statement="Store tokens, never raw PANs, in the merchant database.",
        confidence=1.0,
        source_reference=_ref("Tokens only in our DB."),
    )

    assert requirement.id == "REQ-001"
    assert requirement.confidence == 1.0


def test_valid_task_with_defaults() -> None:
    task = Task(
        id="TSK-001",
        title="Rotate Stripe restricted keys",
        description="Replace the shared test key with per-environment restricted keys.",
        priority=Priority.LOW,
    )

    assert task.acceptance_criteria == []
    assert task.source_references == []


def test_valid_risk_and_open_question() -> None:
    risk = Risk(
        id="RSK-001",
        description="Chargebacks spike if 3DS is skipped on high-value orders.",
        severity=Severity.MEDIUM,
        source_reference=_ref("High-value orders still skip 3DS."),
    )
    question = OpenQuestion(
        id="OQ-001",
        question="Who owns the settlement reconciling job after the cutover?",
        context="Finance currently runs a spreadsheet against the Braintree export.",
        source_reference=_ref("Who owns recon after we leave Braintree?"),
    )

    assert risk.severity is Severity.MEDIUM
    assert question.id == "OQ-001"


def test_valid_meeting_analysis() -> None:
    analysis = payment_system_analysis()

    assert len(analysis.decisions) == 2
    assert analysis.tasks[0].priority is Priority.HIGH
    assert analysis.risks[0].severity is Severity.CRITICAL
    assert analysis.open_questions[0].id == "OQ-001"


def test_empty_collections_are_valid() -> None:
    analysis = MeetingAnalysis()

    assert analysis.decisions == []
    assert analysis.requirements == []
    assert analysis.tasks == []
    assert analysis.risks == []
    assert analysis.open_questions == []


def test_list_defaults_are_not_shared() -> None:
    first = MeetingAnalysis()
    second = MeetingAnalysis()
    first.decisions.append(_decision())

    assert second.decisions == []

    first_task = Task(
        id="TSK-001",
        title="A",
        description="B",
        priority=Priority.LOW,
    )
    second_task = Task(
        id="TSK-002",
        title="C",
        description="D",
        priority=Priority.LOW,
    )
    first_task.acceptance_criteria.append("Done when tests pass.")

    assert second_task.acceptance_criteria == []


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (Decision, {"statement": "x", "confidence": 0.5, "source_reference": {"excerpt": "y"}}),
        (Requirement, {"id": "REQ-001", "confidence": 0.5, "source_reference": {"excerpt": "y"}}),
        (Task, {"id": "TSK-001", "title": "x", "priority": "high"}),
        (Risk, {"id": "RSK-001", "severity": "low", "source_reference": {"excerpt": "y"}}),
        (OpenQuestion, {"id": "OQ-001", "question": "Why?", "source_reference": {"excerpt": "y"}}),
        (SourceReference, {}),
    ],
)
def test_missing_required_fields(model: type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(payload)

    assert exc_info.value.errors()


def test_empty_strings_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _decision(statement="   ")

    with pytest.raises(ValidationError):
        SourceReference(excerpt="")


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2, -1])
def test_invalid_confidence_values(confidence: float) -> None:
    with pytest.raises(ValidationError):
        _decision(confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_valid_confidence_boundaries(confidence: float) -> None:
    decision = _decision(confidence=confidence)
    assert decision.confidence == confidence


@pytest.mark.parametrize("priority", ["urgent", "p0", "", "HIGH"])
def test_invalid_priority_values(priority: str) -> None:
    with pytest.raises(ValidationError):
        Task(
            id="TSK-001",
            title="Work",
            description="Do the work",
            priority=priority,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("severity", ["catastrophic", "info", "", "HIGH"])
def test_invalid_severity_values(severity: str) -> None:
    with pytest.raises(ValidationError):
        Risk(
            id="RSK-001",
            description="Something bad",
            severity=severity,  # type: ignore[arg-type]
            source_reference=_ref(),
        )


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            Decision,
            {
                "id": "DEC-1",
                "statement": "x",
                "confidence": 0.5,
                "source_reference": {"excerpt": "y"},
            },
        ),
        (
            Decision,
            {
                "id": "decision-001",
                "statement": "x",
                "confidence": 0.5,
                "source_reference": {"excerpt": "y"},
            },
        ),
        (
            Requirement,
            {
                "id": "REQ-01",
                "statement": "x",
                "confidence": 0.5,
                "source_reference": {"excerpt": "y"},
            },
        ),
        (
            Task,
            {
                "id": "TASK-001",
                "title": "x",
                "description": "y",
                "priority": "low",
            },
        ),
        (
            Risk,
            {
                "id": "RSK-",
                "description": "x",
                "severity": "low",
                "source_reference": {"excerpt": "y"},
            },
        ),
        (
            OpenQuestion,
            {
                "id": "Q-001",
                "question": "Why?",
                "context": "Because",
                "source_reference": {"excerpt": "y"},
            },
        ),
    ],
)
def test_invalid_ids_are_rejected(model: type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_format_item_id_is_zero_padded() -> None:
    assert format_item_id("DEC", 1) == "DEC-001"
    assert format_item_id("TSK", 12) == "TSK-012"
    assert format_item_id("OQ", 100) == "OQ-100"
    assert format_item_id("PLAN", 1) == "PLAN-001"
    assert format_item_id("STEP", 2) == "STEP-002"


def test_valid_implementation_plan() -> None:
    analysis = payment_system_analysis()
    plan = ImplementationPlan(
        id="PLAN-001",
        title="Idempotency implementation",
        summary="Handle duplicate charges in Postgres.",
        steps=[
            ImplementationPlanStep(
                id="STEP-001",
                title="Implement duplicate-request handling.",
                description="Return the original charge for the same key and body.",
                related_requirement_ids=["REQ-001"],
                related_task_ids=["TSK-001"],
                evidence=[
                    SourceReference(
                        excerpt="Checkout retries are already happening; we need Idempotency-Key on /charges."
                    )
                ],
            )
        ],
        acceptance_criteria=["Same key and body returns the original charge."],
        risks=analysis.risks,
        open_questions=analysis.open_questions,
    )

    assert plan.id == "PLAN-001"
    assert plan.steps[0].id == "STEP-001"
    assert plan.risks[0].id == "RSK-001"


def test_implementation_plan_step_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ImplementationPlanStep(
            id="STEP-001",
            title="Work",
            description="Do the work",
            related_requirement_ids=["REQ-001"],
        )


def test_duplicate_step_ids_are_rejected() -> None:
    step = ImplementationPlanStep(
        id="STEP-001",
        title="Work",
        description="Do the work",
        evidence=[SourceReference(excerpt="Checkout retries are already happening.")],
    )
    with pytest.raises(ValidationError, match="Duplicate step IDs"):
        ImplementationPlan(
            id="PLAN-001",
            title="Plan",
            summary="Summary",
            steps=[step, step],
        )



def test_format_item_id_rejects_non_positive_numbers() -> None:
    with pytest.raises(ValueError, match="start at 1"):
        format_item_id("DEC", 0)


def test_duplicate_ids_are_rejected() -> None:
    decision = _decision()
    with pytest.raises(ValidationError, match="Duplicate item IDs"):
        MeetingAnalysis(decisions=[decision, decision])


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Decision.model_validate(
            {
                "id": "DEC-001",
                "statement": "Use Stripe",
                "confidence": 0.9,
                "source_reference": {"excerpt": "Use Stripe"},
                "notes": "extra",
            }
        )


def test_serialization_and_deserialization() -> None:
    original = payment_system_analysis()

    as_dict = original.model_dump(mode="json")
    as_json = original.model_dump_json()
    parsed = json.loads(as_json)
    restored = MeetingAnalysis.model_validate(as_dict)

    assert parsed["tasks"][0]["priority"] == "high"
    assert parsed["risks"][0]["severity"] == "critical"
    assert restored == original
    assert MeetingAnalysis.model_validate_json(as_json) == original


def test_empty_meeting_analysis_roundtrip() -> None:
    original = MeetingAnalysis()

    restored = MeetingAnalysis.model_validate(original.model_dump())

    assert restored == original
    assert restored.model_dump() == {
        "decisions": [],
        "requirements": [],
        "tasks": [],
        "risks": [],
        "open_questions": [],
    }


def _requirement(**overrides: object) -> Requirement:
    data: dict[str, object] = {
        "id": "REQ-001",
        "statement": "Store tokens, never raw PANs, in the merchant database.",
        "confidence": 1.0,
        "source_reference": _ref("Tokens only in our DB."),
    }
    data.update(overrides)
    return Requirement.model_validate(data)


def _task(**overrides: object) -> Task:
    data: dict[str, object] = {
        "id": "TSK-001",
        "title": "Rotate Stripe restricted keys",
        "description": "Replace the shared test key with per-environment restricted keys.",
        "priority": Priority.LOW,
    }
    data.update(overrides)
    return Task.model_validate(data)


def _risk(**overrides: object) -> Risk:
    data: dict[str, object] = {
        "id": "RSK-001",
        "description": "Chargebacks spike if 3DS is skipped on high-value orders.",
        "severity": Severity.MEDIUM,
        "source_reference": _ref("High-value orders still skip 3DS."),
    }
    data.update(overrides)
    return Risk.model_validate(data)


def _open_question(**overrides: object) -> OpenQuestion:
    data: dict[str, object] = {
        "id": "OQ-001",
        "question": "Who owns the settlement reconciling job after the cutover?",
        "context": "Finance currently runs a spreadsheet against the Braintree export.",
        "source_reference": _ref("Who owns recon after we leave Braintree?"),
    }
    data.update(overrides)
    return OpenQuestion.model_validate(data)


def test_valid_decision_requirement_relationship() -> None:
    analysis = MeetingAnalysis(
        decisions=[_decision()],
        requirements=[_requirement(related_decision_ids=["DEC-001"])],
    )

    assert analysis.requirements[0].related_decision_ids == ["DEC-001"]


def test_valid_requirement_task_relationship() -> None:
    analysis = MeetingAnalysis(
        requirements=[_requirement()],
        tasks=[_task(related_requirement_ids=["REQ-001"])],
    )

    assert analysis.tasks[0].related_requirement_ids == ["REQ-001"]


def test_valid_requirement_risk_relationship() -> None:
    analysis = MeetingAnalysis(
        requirements=[_requirement(related_risk_ids=["RSK-001"])],
        risks=[_risk(related_requirement_ids=["REQ-001"])],
    )

    assert analysis.requirements[0].related_risk_ids == ["RSK-001"]
    assert analysis.risks[0].related_requirement_ids == ["REQ-001"]


def test_valid_requirement_open_question_relationship() -> None:
    analysis = MeetingAnalysis(
        requirements=[_requirement()],
        open_questions=[_open_question(related_requirement_ids=["REQ-001"])],
    )

    assert analysis.open_questions[0].related_requirement_ids == ["REQ-001"]


def test_dangling_decision_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown related_decision_ids"):
        MeetingAnalysis(requirements=[_requirement(related_decision_ids=["DEC-001"])])


def test_dangling_requirement_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown related_requirement_ids"):
        MeetingAnalysis(tasks=[_task(related_requirement_ids=["REQ-001"])])


def test_empty_relationship_lists_remain_valid() -> None:
    analysis = payment_system_analysis()

    assert analysis.requirements[0].related_decision_ids == []
    assert analysis.requirements[0].related_risk_ids == []
    assert analysis.tasks[0].related_requirement_ids == []
    assert analysis.risks[0].related_requirement_ids == []
    assert analysis.open_questions[0].related_requirement_ids == []


def test_duplicate_relationship_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Duplicate related_decision_ids"):
        _requirement(related_decision_ids=["DEC-001", "DEC-001"])

    with pytest.raises(ValidationError, match="Duplicate related_requirement_ids"):
        _task(related_requirement_ids=["REQ-001", "REQ-001"])

    with pytest.raises(ValidationError, match="Duplicate related_task_ids"):
        ImplementationPlanStep(
            id="STEP-001",
            title="Work",
            description="Do the work",
            related_task_ids=["TSK-001", "TSK-001"],
            evidence=[_ref("Checkout retries are already happening.")],
        )
