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



def test_confirming_reply_is_kept_even_when_other_lines_share_more_words() -> None:
    notes = (
        "Meeting: Retry review\n"
        "Tanya asked whether the retry policy would increase transaction completion time.\n"
        "Mehul acknowledged that it could.\n"
        "The maximum retry window must be defined before implementation.\n"
        "The exact retry policy intervals remain unresolved."
    )
    outcome = MeetingAnalyzer(ScriptedLLM({"risks": {"risks": [{
        "description": "The retry policy could increase transaction completion time.",
        "severity": "medium", "lines": [2],
    }], "open_questions": []}})).run(notes)
    excerpt = outcome.analysis.risks[0].source_reference.excerpt
    assert "Mehul acknowledged that it could." in excerpt



def test_risk_that_restates_a_rule_is_dropped() -> None:
    notes = (
        "Meeting: Security review\n"
        "Arjun said the review should focus on access control and event integrity.\n"
        "The group agreed that the security review must be completed before production traffic is moved to Kafka."
    )
    outcome = MeetingAnalyzer(ScriptedLLM({"risks": {"risks": [{
        "description": "Security review not completed could expose access control and event integrity issues.",
        "severity": "high", "lines": [3],
    }], "open_questions": []}})).run(notes)
    assert outcome.analysis.risks == []
    assert any("rule" in d["reason"] for d in outcome.dropped)


def test_risk_with_a_voiced_concern_next_to_a_rule_is_kept() -> None:
    notes = (
        "Meeting: Load review\n"
        "Mehul warned that an extra lookup per event must be avoided because it could overload PostgreSQL."
    )
    outcome = MeetingAnalyzer(ScriptedLLM({"risks": {"risks": [{
        "description": "Extra lookups per event could overload PostgreSQL.",
        "severity": "medium", "lines": [2],
    }], "open_questions": []}})).run(notes)
    assert len(outcome.analysis.risks) == 1



def test_problem_already_happening_is_not_softened_to_could() -> None:
    from app.analysis.grounding import restore_present

    claim = "Inconsistent timeout and retry policies could cause cascading failures."
    evidence = "The group agreed that inconsistent timeout and retry policies are contributing to cascading failures."
    assert restore_present(claim, evidence) == (
        "Inconsistent timeout and retry policies are contributing to cascading failures."
    )
    assert restore_present(claim, "Mehul warned it could cause cascading failures.") == claim


def test_open_question_worded_as_a_question_ends_with_a_question_mark() -> None:
    from app.analysis.grounding import as_question

    assert as_question("Should Redis be introduced as a deduplication cache.") == (
        "Should Redis be introduced as a deduplication cache?"
    )
    assert as_question("Exact retry intervals remain unresolved.") == "Exact retry intervals remain unresolved."



def _run(notes: str, answers: dict):
    return MeetingAnalyzer(ScriptedLLM(answers)).run(notes)


def test_answered_question_is_not_an_open_question() -> None:
    notes = (
        "Meeting: Delivery\n"
        "Daniel: Are we requiring exactly-once processing?\n"
        "Vikram: No. Exactly-once is too expensive.\n"
        "Arjun: At-least-once delivery with idempotent consumers is sufficient.\n"
        "Rohan: How long do we keep transaction events?\n"
        "Arjun: We shouldn't choose retention until legal confirms.\n"
        "Daniel: Open question."
    )
    outcome = _run(notes, {"risks": {"risks": [], "open_questions": [
        {"question": "Should exactly-once processing be implemented?", "context": "", "lines": [2]},
        {"question": "How long should transaction events be kept?", "context": "", "lines": [5]},
    ]}})
    assert [q.question for q in outcome.analysis.open_questions] == ["How long should transaction events be kept?"]


def test_decision_on_an_undecided_line_is_dropped() -> None:
    notes = (
        "Meeting: Dedup\n"
        "Daniel: Is Redis deduplication staying?\n"
        "Vikram: Undecided. We could use Redis as a fast path.\n"
        "Arjun: I'd rather benchmark without Redis first."
    )
    outcome = _run(notes, {"decisions": {"decisions": [
        {"statement": "Do not use Redis deduplication for production.", "lines": [3, 4]},
    ]}})
    assert outcome.analysis.decisions == []


def test_someone_taking_on_work_is_a_task_not_a_requirement() -> None:
    notes = "Meeting: Tasks\nNeha: I'll document payment idempotency and fraud ordering requirements."
    outcome = _run(notes, {"requirements": {"requirements": [
        {"statement": "Payment idempotency and fraud ordering requirements must be documented.", "lines": [2]},
    ]}})
    assert outcome.analysis.requirements == []


def test_timing_constraint_is_not_a_task() -> None:
    notes = "Meeting: Gate\nMaya: One final point: no production schema change until the database benchmark is reviewed."
    outcome = _run(notes, {"tasks": {"tasks": [{
        "title": "Ensure no production schema change until the benchmark is reviewed",
        "owner": "Maya", "priority": "high", "acceptance_criteria": ["Benchmark reviewed"], "lines": [2],
    }]}})
    assert outcome.analysis.tasks == []


def test_should_stays_should_when_another_sentence_says_needs_to() -> None:
    from app.analysis.grounding import restore_modality

    evidence = (
        "Default Kafka partitioning should use order_id. If a downstream consumer needs stronger "
        "ordering, it needs to solve that within its own domain."
    )
    assert restore_modality("Kafka partitioning must use order_id as the default key.", evidence) == (
        "Kafka partitioning should use order_id as the default key."
    )


def test_eventually_consistent_is_not_a_time_qualifier() -> None:
    from app.analysis.grounding import restore_qualifiers

    claim = "Payment authorization timeout could result in a false payment failure."
    evidence = "The payment provider itself is eventually consistent. The API timeout doesn't mean payment failed."
    assert restore_qualifiers(claim, evidence) == claim
