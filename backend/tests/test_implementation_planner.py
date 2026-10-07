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
from app.planning import ImplementationPlanner, PlanValidationError
from app.planning.prompts import build_implementation_plan_prompt
from tests.fakes import ScriptedLLM


def _ref(excerpt: str, line: int) -> SourceReference:
    return SourceReference(excerpt=excerpt, line_start=line, line_end=line, speaker="Priya")


def _analysis() -> MeetingAnalysis:
    return MeetingAnalysis(
        decisions=[
            Decision(
                id="DEC-001",
                statement="Use the existing Postgres unique constraint for idempotency keys.",
                confidence=0.9,
                source_reference=_ref("Use the existing Postgres unique constraint.", 30),
            )
        ],
        requirements=[
            Requirement(
                id="REQ-001",
                statement="POST /v1/charges must honor an Idempotency-Key header.",
                confidence=0.9,
                source_reference=_ref("POST /v1/charges must honor an Idempotency-Key header.", 10),
                related_decision_ids=["DEC-001"],
            )
        ],
        tasks=[
            Task(
                id="TSK-001",
                title="Add idempotency middleware",
                description="Middleware on POST /v1/charges.",
                priority=Priority.HIGH,
                owner="Priya",
                acceptance_criteria=["Same key and body returns the original charge."],
                source_references=[_ref("add idempotency middleware to POST /v1/charges.", 13)],
                related_requirement_ids=["REQ-001"],
            ),
            Task(
                id="TSK-002",
                title="Document decline codes",
                description="Document capture decline codes for client teams.",
                priority=Priority.MEDIUM,
                source_references=[_ref("Also document capture decline codes", 18)],
            ),
        ],
        risks=[
            Risk(
                id="RSK-001",
                description="Two writers may double-settle a PaymentIntent.",
                severity=Severity.CRITICAL,
                source_reference=_ref("we will double-charge customers", 20),
            )
        ],
        open_questions=[
            OpenQuestion(
                id="OQ-001",
                question="Does Apple Pay ship now?",
                context="Mobile still uses Braintree.",
                source_reference=_ref("Should Apple Pay go out", 23),
            )
        ],
    )


PLAN = {
    "title": "Idempotent charges",
    "summary": "Add idempotency to charges, backed by Postgres.",
    "steps": [
        {
            "title": "Build idempotency middleware",
            "description": "Store keys under a Postgres unique constraint.",
            "requirement_ids": ["req-001"],
            "task_ids": ["TSK-001", "TSK-404"],
        },
        {
            "title": "Invented step",
            "description": "Not tied to the record.",
            "requirement_ids": [],
            "task_ids": [],
        },
    ],
    "acceptance_criteria": ["Repeated requests never create a second charge."],
}


def test_prompt_is_compact_text_with_ids() -> None:
    prompt = build_implementation_plan_prompt(_analysis())
    assert "REQ-001: POST /v1/charges" in prompt
    assert "TSK-001: Add idempotency middleware" in prompt
    assert "owner Priya" in prompt
    assert "{" not in prompt.split("TASK:")[0]  # record is text, not a JSON dump


def test_steps_cite_record_ids_and_take_evidence_from_them() -> None:
    plan = ImplementationPlanner(ScriptedLLM({"plan": PLAN})).plan(_analysis(), title="Charges")

    first = plan.steps[0]
    assert plan.id == "PLAN-001"
    assert plan.title == "Charges"
    assert first.id == "STEP-001"
    assert first.related_requirement_ids == ["REQ-001"]
    assert first.related_task_ids == ["TSK-001"]  # TSK-404 stripped
    assert {ref.line_start for ref in first.evidence} == {10, 13}


def test_steps_without_valid_references_are_dropped() -> None:
    plan = ImplementationPlanner(ScriptedLLM({"plan": PLAN})).plan(_analysis())
    assert all(step.title != "Invented step" for step in plan.steps)


def test_uncovered_tasks_are_appended_as_steps() -> None:
    plan = ImplementationPlanner(ScriptedLLM({"plan": PLAN})).plan(_analysis())
    last = plan.steps[-1]
    assert last.related_task_ids == ["TSK-002"]
    assert last.evidence[0].line_start == 18
    assert [s.id for s in plan.steps] == ["STEP-001", "STEP-002"]


def test_risks_and_questions_are_copied_from_the_record() -> None:
    plan = ImplementationPlanner(ScriptedLLM({"plan": PLAN})).plan(_analysis())
    assert [r.id for r in plan.risks] == ["RSK-001"]
    assert [q.id for q in plan.open_questions] == ["OQ-001"]


def test_missing_criteria_fall_back_to_task_criteria() -> None:
    answer = dict(PLAN, acceptance_criteria=[])
    plan = ImplementationPlanner(ScriptedLLM({"plan": answer})).plan(_analysis())
    assert plan.acceptance_criteria == ["Same key and body returns the original charge."]


def test_empty_record_skips_the_model() -> None:
    llm = ScriptedLLM()
    plan = ImplementationPlanner(llm).plan(MeetingAnalysis())
    assert llm.calls == []
    assert plan.steps == []
    assert "nothing to plan" in plan.summary


def test_invalid_output_raises_plan_validation_error() -> None:
    with pytest.raises(PlanValidationError):
        ImplementationPlanner(ScriptedLLM({"plan": "not json"})).plan(_analysis())


def test_steps_cite_decisions_and_misfiled_ids_are_sorted_by_prefix() -> None:
    answer = dict(
        PLAN,
        steps=[
            {
                "title": "Idempotency middleware on Postgres",
                "description": "",
                "decision_ids": ["DEC-001", "DEC-404"],
                # A decision ID in the wrong list is moved, not dropped.
                "requirement_ids": ["REQ-001", "DEC-001", "TSK-001"],
                "task_ids": [],
            },
            {
                "title": "Apply the Postgres decision",
                "description": "Only a decision is cited.",
                "decision_ids": ["DEC-001"],
                "requirement_ids": [],
                "task_ids": [],
            },
        ],
    )
    plan = ImplementationPlanner(ScriptedLLM({"plan": answer})).plan(_analysis())
    first, second = plan.steps[0], plan.steps[1]

    assert first.related_decision_ids == ["DEC-001"]
    assert first.related_requirement_ids == ["REQ-001"]
    assert first.related_task_ids == ["TSK-001"]
    # A decision-only step is kept, with the decision's transcript evidence.
    assert second.related_decision_ids == ["DEC-001"]
    assert second.evidence[0].line_start == 30


def test_plan_criteria_come_from_tasks_not_the_model() -> None:
    answer = dict(PLAN, acceptance_criteria=["Campaign generates at least 120 qualified leads"])
    plan = ImplementationPlanner(ScriptedLLM({"plan": answer})).plan(_analysis())
    # The model's invented target is ignored; the tasks' criteria are used.
    assert plan.acceptance_criteria == ["Same key and body returns the original charge."]


def test_blanket_citation_is_kept_only_where_the_step_relates() -> None:
    steps = [
        {"title": "Add idempotency middleware for charges", "description": "Idempotency-Key header on POST /v1/charges",
         "decision_ids": [], "requirement_ids": ["REQ-001"], "task_ids": ["TSK-001"]},
        {"title": "Write decline code docs", "description": "Document capture decline codes",
         "decision_ids": [], "requirement_ids": ["REQ-001"], "task_ids": ["TSK-002"]},
        {"title": "Announce to client teams", "description": "Share the release notes",
         "decision_ids": [], "requirement_ids": ["REQ-001"], "task_ids": ["TSK-002"]},
        {"title": "Only cites the requirement", "description": "Nothing else",
         "decision_ids": [], "requirement_ids": ["REQ-001"], "task_ids": []},
    ]
    plan = ImplementationPlanner(ScriptedLLM({"plan": dict(PLAN, steps=steps)})).plan(_analysis())
    cited = [s.related_requirement_ids for s in plan.steps]

    assert cited[0] == ["REQ-001"]  # shares "idempotency", "charges", ...
    assert cited[1] == [] and cited[2] == []  # unrelated: blanket link removed
    assert cited[3] == ["REQ-001"]  # its only reference, so the step is kept


def _plan_with(steps=None, outcomes=None):
    answer = dict(PLAN)
    if steps is not None:
        answer["steps"] = steps
    answer["outcomes"] = outcomes or []
    return ImplementationPlanner(ScriptedLLM({"plan": answer})).plan(_analysis())


STEP = {"title": "Build idempotency middleware", "description": "d",
        "decision_ids": ["DEC-001"], "requirement_ids": ["REQ-001"], "task_ids": ["TSK-001"]}


def test_step_when_is_kept_only_if_its_dates_are_in_the_record() -> None:
    analysis = _analysis()
    analysis.tasks[0].due = "Friday"
    plan = ImplementationPlanner(
        ScriptedLLM({"plan": dict(PLAN, outcomes=[], steps=[
            dict(STEP, when="By Friday"),
            dict(STEP, title="Second", when="Before October 28", task_ids=[]),
            dict(STEP, title="Third", when="N/A", task_ids=[]),
        ])})
    ).plan(analysis)
    assert plan.steps[0].when == "By Friday"  # "Friday" is in the record
    assert plan.steps[1].when is None  # "October 28" is invented
    assert plan.steps[2].when is None
    # A task the model left out becomes a step timed by its own due date.
    assert plan.steps[-1].related_task_ids == ["TSK-002"]


def test_outcomes_are_checked_against_the_items_they_cite() -> None:
    plan = _plan_with(
        steps=[STEP],
        outcomes=[
            {"text": "Repeated charge requests honor the Idempotency-Key header", "ids": ["REQ-001"]},
            {"text": "Postgres unique constraint handles 10,000 keys per second", "ids": ["DEC-001"]},
            {"text": "Something unrelated", "ids": ["DEC-404"]},
        ],
    )
    assert plan.acceptance_criteria == [
        "Repeated charge requests honor the Idempotency-Key header",
        # Invented number: replaced by the decision's own words.
        "Use the existing Postgres unique constraint for idempotency keys.",
    ]


def test_without_outcomes_the_plan_is_done_when_its_decisions_hold() -> None:
    plan = _plan_with(steps=[STEP], outcomes=[])
    assert plan.acceptance_criteria == [
        "Use the existing Postgres unique constraint for idempotency keys."
    ]


def test_unrelated_links_are_dropped_and_related_ones_kept() -> None:
    steps = [
        # Related: shares "idempotency" / "charges" with REQ-001 and DEC-001's "Postgres... keys".
        {"title": "Idempotency middleware", "description": "", "decision_ids": [],
         "requirement_ids": ["REQ-001"], "task_ids": ["TSK-001"]},
        # Unrelated: docs task citing the idempotency requirement and the Postgres decision,
        # with a description written to sound related.
        {"title": "Write decline code docs", "description": "Document idempotency keys in Postgres",
         "decision_ids": ["DEC-001"], "requirement_ids": ["REQ-001"], "task_ids": ["TSK-002"]},
    ]
    plan = ImplementationPlanner(ScriptedLLM({"plan": dict(PLAN, steps=steps, outcomes=[])})).plan(_analysis())
    assert plan.steps[0].related_requirement_ids == ["REQ-001"]
    assert plan.steps[1].related_requirement_ids == []
    assert plan.steps[1].related_decision_ids == []



def test_forgotten_task_attaches_to_its_step_instead_of_duplicating_it() -> None:
    steps = [
        {"title": "Idempotency middleware", "description": "", "decision_ids": [],
         "requirement_ids": ["REQ-001"], "task_ids": ["TSK-001"]},
        # The model wrote the docs step but forgot to cite TSK-002.
        {"title": "Document decline codes", "description": "For client teams",
         "decision_ids": [], "requirement_ids": [], "task_ids": []},
    ]
    plan = ImplementationPlanner(ScriptedLLM({"plan": dict(PLAN, steps=steps, outcomes=[])})).plan(_analysis())
    titles = [s.title for s in plan.steps]
    assert titles.count("Document decline codes") == 1
    assert len(plan.steps) == 2
    assert plan.steps[1].related_task_ids == ["TSK-002"]


def test_item_cited_by_several_steps_stays_where_it_belongs() -> None:
    analysis = _analysis()
    steps = [
        # Strong match: idempotency middleware on charges.
        {"title": "Idempotency middleware for POST /v1/charges", "description": "",
         "decision_ids": [], "requirement_ids": ["REQ-001"], "task_ids": ["TSK-001"]},
        # Weak match: shares only "charges" with REQ-001.
        {"title": "Document charges decline codes", "description": "",
         "decision_ids": [], "requirement_ids": ["REQ-001"], "task_ids": ["TSK-002"]},
    ]
    plan = ImplementationPlanner(ScriptedLLM({"plan": dict(PLAN, steps=steps, outcomes=[])})).plan(analysis)
    assert plan.steps[0].related_requirement_ids == ["REQ-001"]
    assert plan.steps[1].related_requirement_ids == []



def test_outcome_joining_several_items_is_split_one_per_line() -> None:
    analysis = _analysis()
    ids = [analysis.decisions[0].id, analysis.requirements[0].id]
    outcomes = [{"text": "Both things will happen.", "ids": ids}]
    plan = ImplementationPlanner(ScriptedLLM({"plan": dict(PLAN, outcomes=outcomes)})).plan(analysis)
    statements = {d.id: d.statement for d in analysis.decisions} | {r.id: r.statement for r in analysis.requirements}
    assert plan.acceptance_criteria[:2] == [statements[ids[0]], statements[ids[1]]]
