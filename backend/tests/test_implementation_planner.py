import json
from typing import Any

import pytest

from app.domain import (
    Decision,
    MeetingAnalysis,
    OpenQuestion,
    Priority,
    Requirement,
    Risk,
    Severity,
    SourceReference,
    Task,
)
from app.llm.provider import LLMProvider
from app.planning import ImplementationPlanner, PlanValidationError
from app.planning.prompts import (
    IMPLEMENTATION_PLAN_INSTRUCTIONS,
    build_implementation_plan_prompt,
)


class FakeLLMProvider(LLMProvider):
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.text


def _ref(excerpt: str) -> SourceReference:
    return SourceReference(excerpt=excerpt)


def _analysis() -> MeetingAnalysis:
    return MeetingAnalysis(
        decisions=[
            Decision(
                id="DEC-001",
                statement="Postgres is the source of truth for payment idempotency.",
                confidence=0.95,
                source_reference=_ref(
                    "Maya: Let's make that the decision. Postgres is the source of truth for payment idempotency."
                ),
            )
        ],
        requirements=[
            Requirement(
                id="REQ-001",
                statement="Same idempotency key + same request → return the original result.",
                confidence=0.96,
                source_reference=_ref(
                    "A repeated request with the same key and body returns the original charge."
                ),
            ),
            Requirement(
                id="REQ-002",
                statement="Same idempotency key + different body → reject with HTTP 409.",
                confidence=0.94,
                source_reference=_ref(
                    "A repeated request with the same key and a different body returns HTTP 409."
                ),
            ),
        ],
        tasks=[
            Task(
                id="TSK-001",
                title="Add idempotency middleware to POST /v1/charges",
                description="Replay or reject duplicate charges using Idempotency-Key.",
                priority=Priority.HIGH,
                acceptance_criteria=[
                    "A repeated request with the same key and body returns the original charge."
                ],
                source_references=[
                    _ref("add idempotency middleware to POST /v1/charges.")
                ],
            ),
            Task(
                id="TSK-002",
                title="Persist idempotency keys in Postgres",
                description="Store keys with the existing Postgres unique constraint.",
                priority=Priority.HIGH,
                acceptance_criteria=["Keys are stored in Postgres, not Redis."],
                source_references=[
                    _ref(
                        "Maya: Let's make that the decision. Postgres is the source of truth for payment idempotency."
                    )
                ],
            ),
        ],
        risks=[
            Risk(
                id="RSK-001",
                description="Stripe succeeds but the local database write fails.",
                severity=Severity.HIGH,
                source_reference=_ref(
                    "If Stripe succeeds but the local database write fails, the customer sees success and we have no local record."
                ),
            )
        ],
        open_questions=[
            OpenQuestion(
                id="OQ-001",
                question="What numeric rollout thresholds should be used?",
                context="Not finalized before launch.",
                source_reference=_ref(
                    "Maya: We need actual thresholds. That's an open item, not a decision yet."
                ),
            )
        ],
    )


def _plan_payload(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Payment idempotency implementation",
        "summary": "Implement duplicate-request handling using Postgres as the source of truth.",
        "steps": [
            {
                "title": "Implement duplicate-request handling for idempotent payment creation.",
                "description": "Return the original result when the same idempotency key and body are replayed.",
                "related_requirement_ids": ["REQ-001"],
                "related_task_ids": ["TSK-001"],
                "evidence": [
                    {
                        "excerpt": "A repeated request with the same key and body returns the original charge."
                    }
                ],
            }
        ],
        "acceptance_criteria": [
            "A repeated request with the same key and body returns the original charge."
        ],
    }
    payload.update(overrides)
    return payload


def test_prompt_forbids_invented_architecture() -> None:
    prompt = build_implementation_plan_prompt(_analysis())

    assert "Do not invent" in IMPLEMENTATION_PLAN_INSTRUCTIONS
    assert "Redis" in IMPLEMENTATION_PLAN_INSTRUCTIONS
    assert "ENGINEERING RECORD JSON:" in prompt
    assert "REQ-001" in prompt
    assert prompt.startswith(IMPLEMENTATION_PLAN_INSTRUCTIONS)


def test_valid_step_keeps_valid_evidence() -> None:
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(_plan_payload()))).plan(
        _analysis()
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].related_requirement_ids == ["REQ-001"]
    assert plan.steps[0].related_task_ids == ["TSK-001"]
    assert [ref.excerpt for ref in plan.steps[0].evidence] == [
        "A repeated request with the same key and body returns the original charge."
    ]


def _linked_analysis() -> MeetingAnalysis:
    analysis = _analysis()
    return analysis.model_copy(
        update={
            "requirements": [
                analysis.requirements[0].model_copy(
                    update={
                        "related_decision_ids": ["DEC-001"],
                        "related_risk_ids": ["RSK-001"],
                    }
                ),
                analysis.requirements[1],
            ],
            "tasks": [
                analysis.tasks[0].model_copy(
                    update={"related_requirement_ids": ["REQ-001"]}
                ),
                analysis.tasks[1],
            ],
            "risks": [
                analysis.risks[0].model_copy(
                    update={"related_requirement_ids": ["REQ-001"]}
                )
            ],
            "open_questions": [
                analysis.open_questions[0].model_copy(
                    update={"related_requirement_ids": ["REQ-002"]}
                )
            ],
        }
    )


def test_planner_step_referencing_valid_requirement_and_task_ids_succeeds() -> None:
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(_plan_payload()))).plan(
        _linked_analysis()
    )

    assert plan.steps[0].related_requirement_ids == ["REQ-001"]
    assert plan.steps[0].related_task_ids == ["TSK-001"]
    assert plan.steps[0].evidence


def test_planner_step_unknown_ids_are_stripped() -> None:
    payload = _plan_payload()
    payload["steps"][0]["related_requirement_ids"] = ["REQ-001", "REQ-999"]
    payload["steps"][0]["related_task_ids"] = ["TSK-999"]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(
        _linked_analysis()
    )

    assert plan.steps[0].related_requirement_ids == ["REQ-001"]
    assert plan.steps[0].related_task_ids == []
    assert plan.steps[0].evidence


def test_dangling_task_id_is_rejected() -> None:
    payload = _plan_payload()
    payload["steps"][0]["related_task_ids"] = ["TSK-999"]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert plan.steps[0].related_task_ids == []
    assert plan.steps[0].related_requirement_ids == ["REQ-001"]
    assert plan.steps[0].evidence


def test_unknown_requirement_and_task_ids_are_stripped_when_evidence_is_valid() -> None:
    payload = _plan_payload()
    payload["steps"][0]["related_requirement_ids"] = ["REQ-999"]
    payload["steps"][0]["related_task_ids"] = ["TSK-999"]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert len(plan.steps) == 1
    assert plan.steps[0].related_requirement_ids == []
    assert plan.steps[0].related_task_ids == []
    assert [ref.excerpt for ref in plan.steps[0].evidence] == [
        "A repeated request with the same key and body returns the original charge."
    ]


def test_step_with_completely_fabricated_evidence_is_dropped() -> None:
    payload = _plan_payload()
    payload["steps"][0]["evidence"] = [
        {"excerpt": "We unanimously voted to adopt Redis for idempotency today."}
    ]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert plan.steps == []


def test_step_is_dropped_when_all_evidence_becomes_invalid() -> None:
    payload = _plan_payload()
    payload["steps"].append(
        {
            "title": "Reject requests with same key and different body.",
            "description": "Return HTTP 409 when the body does not match.",
            "related_requirement_ids": ["REQ-002"],
            "related_task_ids": ["TSK-001"],
            "evidence": [
                {
                    "excerpt": "Reject requests with the same key and a different body."
                },
                {"excerpt": "We unanimously voted to adopt Redis for idempotency today."},
            ],
        }
    )
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert [step.id for step in plan.steps] == ["STEP-001"]
    assert plan.steps[0].title.startswith("Implement duplicate-request")
    assert plan.steps[0].evidence


def test_step_keeps_multiple_valid_evidence_references() -> None:
    payload = _plan_payload()
    payload["steps"][0]["evidence"] = [
        {
            "excerpt": "A repeated request with the same key and body returns the original charge."
        },
        {
            "excerpt": "A repeated request with the same key and a different body returns HTTP 409."
        },
        {"excerpt": "We unanimously voted to adopt Redis for idempotency today."},
    ]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert [ref.excerpt for ref in plan.steps[0].evidence] == [
        "A repeated request with the same key and body returns the original charge.",
        "A repeated request with the same key and a different body returns HTTP 409.",
    ]


def test_valid_engineering_record_becomes_implementation_plan() -> None:
    provider = FakeLLMProvider(json.dumps(_plan_payload()))
    plan = ImplementationPlanner(provider).plan(_analysis())

    assert plan.id == "PLAN-001"
    assert plan.steps[0].id == "STEP-001"
    assert plan.steps[0].related_requirement_ids == ["REQ-001"]
    assert plan.steps[0].related_task_ids == ["TSK-001"]
    assert plan.risks[0].id == "RSK-001"
    assert plan.open_questions[0].id == "OQ-001"
    assert "Postgres" in plan.summary
    assert plan.steps[0].evidence[0].excerpt.startswith("A repeated request")


def test_invalid_requirement_id_is_removed() -> None:
    payload = _plan_payload()
    payload["steps"][0]["related_requirement_ids"] = ["REQ-001", "REQ-999"]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert plan.steps[0].related_requirement_ids == ["REQ-001"]


def test_invalid_task_id_is_removed() -> None:
    payload = _plan_payload()
    payload["steps"][0]["related_task_ids"] = ["TSK-999"]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert plan.steps[0].related_task_ids == []
    assert plan.steps[0].related_requirement_ids == ["REQ-001"]


def test_fabricated_evidence_is_dropped() -> None:
    payload = _plan_payload()
    payload["steps"][0]["evidence"] = [
        {"excerpt": "We unanimously voted to adopt Redis for idempotency today."},
        {
            "excerpt": "A repeated request with the same key and body returns the original charge."
        },
    ]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert [ref.excerpt for ref in plan.steps[0].evidence] == [
        "A repeated request with the same key and body returns the original charge."
    ]


def test_step_with_only_invalid_grounding_is_dropped() -> None:
    payload = _plan_payload(
        steps=[
            {
                "title": "Add Redis caching.",
                "description": "Invented work.",
                "related_requirement_ids": ["REQ-999"],
                "related_task_ids": ["TSK-999"],
                "evidence": [
                    {"excerpt": "We unanimously voted to adopt Redis for idempotency today."}
                ],
            }
        ]
    )
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert plan.steps == []


def test_malformed_json_is_rejected() -> None:
    planner = ImplementationPlanner(FakeLLMProvider("this is not json"))

    with pytest.raises(PlanValidationError):
        planner.plan(_analysis())


def test_missing_required_fields_are_rejected() -> None:
    planner = ImplementationPlanner(FakeLLMProvider(json.dumps({"title": "Plan"})))

    with pytest.raises(PlanValidationError):
        planner.plan(_analysis())


def test_plan_and_step_ids_are_deterministic_and_ignore_llm_ids() -> None:
    payload = _plan_payload()
    payload["id"] = "PLAN-99"
    payload["steps"][0]["id"] = "STEP-7"
    payload["steps"].append(
        {
            "id": "STEP-1",
            "title": "Persist idempotency records in Postgres.",
            "description": "Use the existing Postgres unique constraint.",
            "related_requirement_ids": ["REQ-002"],
            "related_task_ids": ["TSK-002"],
            "evidence": [
                {
                    "excerpt": (
                        "Maya: Let's make that the decision. Postgres is the "
                        "source of truth for payment idempotency."
                    )
                }
            ],
        }
    )
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert plan.id == "PLAN-001"
    assert [step.id for step in plan.steps] == ["STEP-001", "STEP-002"]


def test_empty_requirements_and_tasks_yield_empty_steps() -> None:
    analysis = MeetingAnalysis(
        decisions=[
            Decision(
                id="DEC-001",
                statement="Keep settlement cut-off at 22:00 UTC.",
                confidence=0.9,
                source_reference=_ref("Settlement cut-off stays at 22:00 UTC."),
            )
        ]
    )
    payload = _plan_payload(
        summary="No implementation work was assigned.",
        steps=[
            {
                "title": "Invent a service.",
                "description": "Not in the record.",
                "related_requirement_ids": ["REQ-001"],
                "related_task_ids": ["TSK-001"],
                "evidence": [
                    {"excerpt": "We unanimously voted to adopt Redis for idempotency today."}
                ],
            }
        ],
        acceptance_criteria=[],
    )
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(analysis)

    assert plan.steps == []
    assert plan.acceptance_criteria == []
    assert plan.risks == []
    assert plan.open_questions == []


def test_step_can_link_multiple_requirements_and_tasks() -> None:
    payload = _plan_payload()
    payload["steps"][0]["related_requirement_ids"] = ["REQ-002", "REQ-001"]
    payload["steps"][0]["related_task_ids"] = ["TSK-002", "TSK-001"]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert plan.steps[0].related_requirement_ids == ["REQ-002", "REQ-001"]
    assert plan.steps[0].related_task_ids == ["TSK-002", "TSK-001"]


def test_llm_risks_are_ignored_and_record_risks_are_copied() -> None:
    payload = _plan_payload()
    payload["risks"] = [
        {
            "id": "RSK-009",
            "description": "Redis could lose idempotency keys.",
            "severity": "critical",
        }
    ]
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert [risk.id for risk in plan.risks] == ["RSK-001"]
    assert "Redis" not in plan.risks[0].description


def test_request_title_overrides_llm_title() -> None:
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(_plan_payload()))).plan(
        _analysis(),
        title="November checkout plan",
    )

    assert plan.title == "November checkout plan"


def test_planner_depends_on_llm_provider_not_ollama() -> None:
    import inspect

    source = inspect.getsource(ImplementationPlanner)
    assert "OllamaProvider" not in source
    assert "LLMProvider" in source


def test_statement_shaped_step_is_normalized() -> None:
    payload = {
        "title": "Plan",
        "summary": "Handle duplicate payment requests.",
        "steps": [
            {
                "statement": "Implement duplicate-request handling for idempotent payment creation.",
                "related_requirements": ["REQ-001"],
                "source_reference": {
                    "excerpt": "A repeated request with the same key and body returns the original charge."
                },
            }
        ],
    }
    plan = ImplementationPlanner(FakeLLMProvider(json.dumps(payload))).plan(_analysis())

    assert plan.steps[0].title.startswith("Implement duplicate-request")
    assert plan.steps[0].related_requirement_ids == ["REQ-001"]
    assert plan.steps[0].evidence
