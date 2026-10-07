"""The extracted record must not be more certain than the meeting was."""

from app.analysis import MeetingAnalyzer
from app.analysis.grounding import (
    affirms,
    asserts_unstated_negative,
    is_question,
    restore_modality,
)
from tests.fakes import ScriptedLLM


def test_should_stays_should() -> None:
    evidence = "Services should authenticate using short-lived workload credentials."
    assert (
        restore_modality("Services must authenticate using short-lived credentials.", evidence)
        == "Services should authenticate using short-lived credentials."
    )
    # A real obligation in the evidence keeps "must".
    assert restore_modality(
        "Payment data must never be logged.", "Payment data must never be logged, and we should audit it."
    ) == "Payment data must never be logged."
    # No "should" in the evidence: unchanged.
    assert restore_modality("Topics must use TLS.", "Topics must use TLS.") == "Topics must use TLS."


def test_present_negatives_need_evidence_but_conditions_and_possibilities_dont() -> None:
    recommendation = "Arjun said it should be enabled."
    assert asserts_unstated_negative("Encryption at rest was not yet enabled.", recommendation)
    assert not asserts_unstated_negative(
        "Duplicates could occur if retries are not handled carefully.",
        "Blindly retrying could create duplicate authorization attempts.",
    )
    assert not asserts_unstated_negative("The team may not have capacity.", "Capacity is about 50.")
    assert not asserts_unstated_negative("The team lacks monitoring.", "We have no monitoring yet.")


def test_question_detection() -> None:
    assert is_question("Tanya asked whether the retry policy would increase completion time.")
    assert is_question("Do we need encryption at rest?")
    assert not is_question("Mehul acknowledged that it could.")
    assert affirms("Mehul acknowledged that it could.")
    assert not affirms("Arjun said it should be enabled.")


TRANSCRIPT = """Meeting: Retry review
Tanya: Will the retry policy increase transaction completion time?
Mehul: I acknowledge that it could.
Tanya: Do we need encryption at rest?
Arjun: It should be enabled, but the review focuses on access control.
Arjun: Services should authenticate using short-lived workload credentials."""


def _analysis(risks=(), requirements=()):
    llm = ScriptedLLM(
        {
            "risks": {"risks": list(risks), "open_questions": []},
            "requirements": {"requirements": list(requirements)},
        }
    )
    return MeetingAnalyzer(llm).analyze(TRANSCRIPT)


def test_question_confirmed_by_next_line_is_a_risk_with_the_answer_as_evidence() -> None:
    analysis = _analysis(
        risks=[
            {"description": "The retry policy could increase transaction completion time.",
             "severity": "medium", "lines": [2]},
        ]
    )
    risk = analysis.risks[0]
    assert "acknowledge that it could" in risk.source_reference.excerpt
    assert risk.source_reference.line_end == 3


def test_unanswered_question_or_invented_state_is_not_a_risk() -> None:
    analysis = _analysis(
        risks=[
            {"description": "Encryption at rest needs review for completion.", "severity": "medium", "lines": [4]},
            {"description": "Encryption at rest is not enabled, a security risk.", "severity": "high", "lines": [5]},
        ]
    )
    assert analysis.risks == []


def test_requirement_keeps_should() -> None:
    analysis = _analysis(
        requirements=[
            {"statement": "Services must authenticate using short-lived workload credentials.", "lines": [6]},
        ]
    )
    assert analysis.requirements[0].statement == (
        "Services should authenticate using short-lived workload credentials."
    )


# ---------------------------------------------------------------- round 2


def test_never_stays_never() -> None:
    evidence = "Sensitive payment information must never be included in logs."
    assert (
        restore_modality("Payment information must not be included in logs.", evidence)
        == "Payment information must never be included in logs."
    )


def test_list_numbering_is_not_a_fact() -> None:
    from app.analysis.grounding import adds_facts

    meeting = "## 5. Exactly-Once Debate\n5. Temporary failures will use retries.\nPeaks reach 45,000 per minute."
    assert adds_facts(">= 5 event types defined", meeting) == {"5"}
    assert adds_facts("Handles 45,000 per minute", meeting) == set()
    assert adds_facts("Retry 5xx responses", "selected 5xx responses") == set()


NOTES = """Meeting: Event review
Vikram: Define the Kafka event schemas and transaction state machine.
Arjun asked whether the architecture required exactly-once processing guarantees.
Vikram said exactly-once would add too much complexity and recommended at-least-once delivery.
The team also needs to determine the retention period for Kafka transaction events."""


def _notes_analysis(**answers):
    return MeetingAnalyzer(ScriptedLLM(answers)).run(NOTES)


def test_invented_task_target_is_removed_and_recorded() -> None:
    outcome = _notes_analysis(tasks={"tasks": [{
        "title": "Define Kafka event schemas", "description": "Define the Kafka event schemas and transaction state machine",
        "owner": "Vikram", "due": "", "priority": "medium",
        "acceptance_criteria": [">= 5 event types defined", "State machine documented"], "lines": [2],
    }]})
    assert outcome.analysis.tasks[0].acceptance_criteria == ["State machine documented"]
    assert outcome.dropped[0]["kind"] == "task criterion"
    assert "5" in outcome.dropped[0]["reason"]


def test_requirement_from_a_question_quotes_the_answer() -> None:
    outcome = _notes_analysis(requirements={"requirements": [{
        "statement": "Exactly-once processing is not required; at-least-once delivery is acceptable.",
        "lines": [3],
    }]})
    excerpt = outcome.analysis.requirements[0].source_reference.excerpt
    assert "asked whether" in excerpt and "recommended at-least-once" in excerpt


def test_unresolved_item_becomes_an_open_question_not_a_risk() -> None:
    outcome = _notes_analysis(risks={"risks": [{
        "description": "Undefined Kafka retention period could lead to data loss.",
        "severity": "medium", "lines": [5],
    }], "open_questions": []})
    assert outcome.analysis.risks == []
    question = outcome.analysis.open_questions[0]
    assert question.question.startswith("The team also needs to determine the retention period")
    assert "data loss" not in question.question + question.context
    assert any(d["kind"] == "risk" for d in outcome.dropped)



def test_answer_evidence_includes_the_conclusion_not_just_the_next_line() -> None:
    notes = (
        "Meeting: Delivery review\n"
        "Arjun asked whether the architecture required exactly-once processing guarantees.\n"
        "Vikram said exactly-once semantics would significantly increase complexity.\n"
        "Rhea asked about something unrelated.\n"
        "He recommended at-least-once delivery with idempotent consumers."
    )
    outcome = MeetingAnalyzer(ScriptedLLM({"requirements": {"requirements": [{
        "statement": "Exactly-once is not required; at-least-once delivery with idempotent consumers is acceptable.",
        "lines": [2],
    }]}})).run(notes)
    excerpt = outcome.analysis.requirements[0].source_reference.excerpt
    assert "recommended at-least-once delivery with idempotent consumers" in excerpt
    assert "unrelated" not in excerpt
