import pytest

from app.analysis import (
    AnalysisValidationError,
    EmptyTranscriptError,
    MeetingAnalyzer,
    TranscriptTooLongError,
)
from app.domain import MeetingAnalysis, Priority, Severity
from app.llm import LLMOutputTruncatedError, LLMUnavailableError
from tests.fakes import FailingLLM, ScriptedLLM
from tests.fixtures.payment_meeting import PAYMENT_MEETING_TRANSCRIPT

# Original line numbers in PAYMENT_MEETING_TRANSCRIPT. The model sees only
# non-blank lines, numbered densely, so it cites e.g. L3 for original line 4:
#  4 Omar: Agreed. We will route all new card-not-present charges through Stripe PaymentIntents.
#  7 Omar: Settlement cut-off stays at 22:00 UTC. ...
# 10 Priya: POST /v1/charges must honor an Idempotency-Key header. ...
# 13 Priya: Concrete work: add idempotency middleware to POST /v1/charges.
# 14 Omar: Done means a repeated request with the same key and body returns the original charge.
# 18 Omar: Also document capture decline codes for client teams.
# 20 Priya: Risk: if the webhook handler and the nightly capture worker both settle ...
# 23 Omar: Should Apple Pay go out with this PaymentIntents rollout, or is that a follow-up?

DECISIONS = {
    "decisions": [
        {
            "statement": "Route all new card-not-present charges through Stripe PaymentIntents.",
            "lines": [3],
        },
        {"statement": "Settlement cut-off stays at 22:00 UTC this quarter.", "lines": [5]},
    ]
}
REQUIREMENTS = {
    "requirements": [
        {
            "statement": "POST /v1/charges must honor an Idempotency-Key header.",
            "lines": [7],
            "decision_ids": ["DEC-001", "DEC-999"],
        }
    ]
}
TASKS = {
    "tasks": [
        {
            "title": "Add idempotency middleware to POST /v1/charges",
            "description": "Middleware that replays the original charge for a repeated key.",
            "owner": "Priya",
            "due": "",
            "priority": "high",
            "acceptance_criteria": [
                "A repeated request with the same key and body returns the original charge."
            ],
            "lines": [9, 10],
            "requirement_ids": ["REQ-001"],
        },
        {
            "title": "Document capture decline codes for client teams",
            "description": "",
            "owner": "the team",
            "due": "next Tuesday",
            "priority": "urgent!!",
            "acceptance_criteria": [],
            "lines": [13],
            "requirement_ids": [],
        },
    ]
}
RISKS = {
    "risks": [
        {
            "description": "Webhook handler and nightly capture worker may both settle the same PaymentIntent and double-charge customers.",
            "severity": "critical",
            "lines": [14],
            "requirement_ids": ["REQ-001"],
        }
    ],
    "open_questions": [
        {
            "question": "Should Apple Pay ship with the PaymentIntents rollout or as a follow-up?",
            "context": "",
            "lines": [16],
            "requirement_ids": [],
        }
    ],
}


def _full_llm() -> ScriptedLLM:
    return ScriptedLLM(
        {"decisions": DECISIONS, "requirements": REQUIREMENTS, "tasks": TASKS, "risks": RISKS}
    )


def test_runs_four_focused_passes_in_order() -> None:
    llm = _full_llm()
    MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    assert [key for key, _ in llm.calls] == ["decisions", "requirements", "tasks", "risks"]


def test_prompts_share_the_transcript_prefix_for_cache_reuse() -> None:
    llm = _full_llm()
    MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    prefixes = {prompt.split("END OF TRANSCRIPT")[0] for _, prompt in llm.calls}
    assert len(prefixes) == 1
    assert "L3: Omar: Agreed." in next(iter(prefixes))


def test_items_get_ids_and_evidence_from_cited_lines() -> None:
    analysis = MeetingAnalyzer(_full_llm()).analyze(PAYMENT_MEETING_TRANSCRIPT)

    first = analysis.decisions[0]
    assert first.id == "DEC-001"
    assert first.source_reference.line_start == 4
    assert first.source_reference.speaker == "Omar"
    assert "Stripe PaymentIntents" in first.source_reference.excerpt
    assert 0.0 < first.confidence <= 1.0
    assert [d.id for d in analysis.decisions] == ["DEC-001", "DEC-002"]


def test_passes_never_see_other_passes_items() -> None:
    llm = _full_llm()
    MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)

    # A small model copies any list it is shown, so none is shown.
    assert "DEC-001" not in llm.prompts_for("requirements")[0]
    assert "Route all new card-not-present charges" not in llm.prompts_for("requirements")[0].split("END OF TRANSCRIPT")[1]
    assert "REQ-001" not in llm.prompts_for("tasks")[0]


def test_links_are_inferred_from_wording_and_shared_lines() -> None:
    analysis = MeetingAnalyzer(_full_llm()).analyze(PAYMENT_MEETING_TRANSCRIPT)

    # The idempotency task clearly implements the idempotency requirement.
    assert analysis.tasks[0].related_requirement_ids == ["REQ-001"]
    # The docs task and the routing decision share no distinctive wording.
    assert analysis.tasks[1].related_requirement_ids == []
    assert analysis.requirements[0].related_decision_ids == []


def test_requirement_risk_links_are_mirrored() -> None:
    risks = {
        "risks": [
            {
                "description": "Clients may not honor the Idempotency-Key header on POST /v1/charges.",
                "severity": "high",
                "lines": [7],
            }
        ],
        "open_questions": [],
    }
    llm = ScriptedLLM({"requirements": REQUIREMENTS, "risks": risks})
    analysis = MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)

    assert analysis.risks[0].related_requirement_ids == ["REQ-001"]
    assert analysis.requirements[0].related_risk_ids == ["RSK-001"]


def test_requirement_restating_a_decision_is_dropped() -> None:
    llm = ScriptedLLM(
        {
            "decisions": DECISIONS,
            "requirements": {
                "requirements": [
                    {"statement": "Route all new card-not-present charges through Stripe PaymentIntents.", "lines": [3]}
                ]
            },
        }
    )
    analysis = MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    assert analysis.requirements == []


def test_task_owner_due_priority_are_cleaned() -> None:
    analysis = MeetingAnalyzer(_full_llm()).analyze(PAYMENT_MEETING_TRANSCRIPT)
    middleware, docs = analysis.tasks

    assert middleware.owner == "Priya"
    assert middleware.due is None
    assert middleware.priority == Priority.HIGH
    assert middleware.acceptance_criteria
    assert middleware.source_references[0].line_start == 13

    assert docs.owner is None  # generic owner rejected
    assert docs.due is None  # "next Tuesday" is not in the transcript
    assert docs.priority == Priority.MEDIUM  # unknown priority falls back
    assert docs.description == docs.title


def test_risks_and_open_questions() -> None:
    analysis = MeetingAnalyzer(_full_llm()).analyze(PAYMENT_MEETING_TRANSCRIPT)
    assert analysis.risks[0].severity == Severity.CRITICAL
    question = analysis.open_questions[0]
    assert question.id == "OQ-001"
    # Empty context falls back to the cited line.
    assert "Apple Pay" in question.context


def test_claim_unsupported_by_cited_lines_is_dropped() -> None:
    llm = ScriptedLLM(
        {
            "decisions": {
                "decisions": [
                    {"statement": "Adopt Kubernetes autoscaling for the fraud cluster.", "lines": [3]}
                ]
            }
        }
    )
    analysis = MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    assert analysis.decisions == []


def test_off_by_one_citation_is_reanchored_nearby() -> None:
    llm = ScriptedLLM(
        {
            "decisions": {
                "decisions": [
                    {
                        "statement": "Use the existing Postgres unique constraint instead of Redis.",
                        "lines": [20],
                    }
                ]
            }
        }
    )
    analysis = MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    assert analysis.decisions[0].source_reference.line_start == 30


def test_out_of_range_lines_are_ignored() -> None:
    llm = ScriptedLLM(
        {
            "decisions": {
                "decisions": [
                    {"statement": "Settlement cut-off stays at 22:00 UTC.", "lines": [5, 999, "L0"]}
                ]
            }
        }
    )
    analysis = MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    ref = analysis.decisions[0].source_reference
    assert (ref.line_start, ref.line_end) == (7, 7)


def test_duplicates_are_merged() -> None:
    llm = ScriptedLLM(
        {
            "decisions": {
                "decisions": [
                    {"statement": "Settlement cut-off stays at 22:00 UTC.", "lines": [5]},
                    {"statement": "The settlement cut-off stays at 22:00 UTC this quarter.", "lines": [5]},
                ]
            }
        }
    )
    analysis = MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    assert len(analysis.decisions) == 1


def test_invalid_pass_output_is_retried_with_a_note() -> None:
    llm = ScriptedLLM({"decisions": ["not json at all", DECISIONS]})
    analysis = MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)

    prompts = llm.prompts_for("decisions")
    assert len(prompts) == 2
    assert "did not match the required JSON shape" in prompts[1]
    assert len(analysis.decisions) == 2


def test_truncated_pass_is_retried_asking_for_fewer_items() -> None:
    llm = ScriptedLLM({"decisions": [LLMOutputTruncatedError("too long"), DECISIONS]})
    MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    assert "too long" in llm.prompts_for("decisions")[1]


def test_a_failing_pass_becomes_a_warning_not_a_failure() -> None:
    llm = ScriptedLLM({"decisions": "garbage", "tasks": TASKS})
    outcome = MeetingAnalyzer(llm).run(PAYMENT_MEETING_TRANSCRIPT)

    assert outcome.analysis.decisions == []
    assert len(outcome.analysis.tasks) == 2
    assert any("Decisions" in warning for warning in outcome.warnings)


def test_all_passes_failing_raises_validation_error() -> None:
    llm = ScriptedLLM(
        {"decisions": "x", "requirements": "x", "tasks": "x", "risks": "x"}
    )
    with pytest.raises(AnalysisValidationError):
        MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)


def test_provider_errors_propagate() -> None:
    with pytest.raises(LLMUnavailableError):
        MeetingAnalyzer(FailingLLM(LLMUnavailableError("down"))).analyze(
            PAYMENT_MEETING_TRANSCRIPT
        )


def test_empty_and_oversized_transcripts_are_rejected() -> None:
    with pytest.raises(EmptyTranscriptError):
        MeetingAnalyzer(ScriptedLLM()).analyze("   ")
    with pytest.raises(TranscriptTooLongError):
        MeetingAnalyzer(ScriptedLLM(), max_transcript_chars=10).analyze(
            PAYMENT_MEETING_TRANSCRIPT
        )


def test_long_transcripts_are_chunked_and_told_what_was_found() -> None:
    llm = ScriptedLLM({"decisions": DECISIONS})
    analyzer = MeetingAnalyzer(llm, chunk_max_tokens=500)
    long_transcript = PAYMENT_MEETING_TRANSCRIPT + "\n" + "\n".join(
        f"Omar: Filler discussion line {n} about lunch plans." for n in range(150)
    )
    outcome = analyzer.run(long_transcript)

    assert outcome.chunks > 1
    assert len(llm.prompts_for("decisions")) == outcome.chunks
    assert "part 2 of" in llm.prompts_for("decisions")[1]
    assert "ALREADY FOUND" in llm.prompts_for("decisions")[1]
    # Same answer from every chunk is merged, not duplicated.
    assert len(outcome.analysis.decisions) == 2


def test_progress_is_reported_per_stage() -> None:
    stages: list[tuple[str, int, int]] = []

    class Recorder:
        def stage(self, label: str, step: int, total: int) -> None:
            stages.append((label, step, total))

        def tokens(self, count: int) -> None:
            pass

    MeetingAnalyzer(_full_llm()).run(PAYMENT_MEETING_TRANSCRIPT, Recorder(), extra_stages=1)
    assert stages[0] == ("Decisions", 1, 5)
    assert stages[-1] == ("Risks & open questions", 4, 5)


def test_short_decision_links_to_longer_requirement_that_extends_it() -> None:
    llm = ScriptedLLM(
        {
            "decisions": {
                "decisions": [
                    {"statement": "Use the existing Postgres unique constraint for keys.", "lines": [21]}
                ]
            },
            "requirements": {
                "requirements": [
                    {
                        "statement": "Repeated charge requests must be rejected by the Postgres unique constraint on idempotency keys within 24 hours.",
                        "lines": [7],
                    }
                ]
            },
        }
    )
    analysis = MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    assert analysis.requirements[0].related_decision_ids == ["DEC-001"]


LAUNCH = """Meeting: Launch planning
Karan: I estimated the team could comfortably support approximately 50 new premium accounts.
Dee: The sync API must accept per-field timestamps and return the merged record.
Decisions:
1. The November 4 launch date remains the target.
2. October 28 will be the internal readiness checkpoint.
3. If the critical feature is not stable by October 28, the launch will move to November 11."""


def _launch_analysis(requirements: list[dict]) -> "MeetingAnalysis":
    llm = ScriptedLLM(
        {
            "decisions": {
                "decisions": [
                    {"statement": "The November 4 launch date remains the target.", "lines": [5]},
                    {"statement": "October 28 is the internal readiness checkpoint.", "lines": [6]},
                    {"statement": "If the critical feature is not stable by October 28, the launch moves to November 11.", "lines": [7]},
                ]
            },
            "requirements": {"requirements": requirements},
        }
    )
    return MeetingAnalysis.model_validate(MeetingAnalyzer(llm).analyze(LAUNCH).model_dump())


def test_requirement_combining_decisions_is_dropped() -> None:
    analysis = _launch_analysis(
        [
            {
                "statement": "The launch must remain scheduled for November 4 unless the critical feature fails the October 28 readiness review.",
                "lines": [5, 7],
            }
        ]
    )
    assert analysis.requirements == []


def test_estimate_does_not_become_an_obligation() -> None:
    analysis = _launch_analysis(
        [
            {"statement": "The customer-success team must handle up to 50 new premium accounts.", "lines": [2]},
            {"statement": "The customer-success team could support approximately 50 new premium accounts.", "lines": [2]},
            {"statement": "The sync API must accept per-field timestamps.", "lines": [3]},
        ]
    )
    statements = [r.statement for r in analysis.requirements]
    # The "must" version of an estimate is dropped; a faithful hedged one stays.
    assert statements == [
        "The customer-success team could support approximately 50 new premium accounts.",
        "The sync API must accept per-field timestamps.",
    ]


def test_requirement_mostly_made_of_one_decision_is_dropped_wherever_cited() -> None:
    llm = ScriptedLLM(
        {
            "decisions": DECISIONS,
            "requirements": {
                "requirements": [
                    # Restates DEC-002 from a discussion line, not the decisions list.
                    {"statement": "The settlement cut-off must stay at 22:00 UTC.", "lines": [6]},
                    {"statement": "POST /v1/charges must honor an Idempotency-Key header.", "lines": [7]},
                ]
            },
        }
    )
    analysis = MeetingAnalyzer(llm).analyze(PAYMENT_MEETING_TRANSCRIPT)
    assert [r.statement for r in analysis.requirements] == [
        "POST /v1/charges must honor an Idempotency-Key header."
    ]


def test_task_schema_requires_a_done_when() -> None:
    from app.analysis.schemas import TASKS_SCHEMA

    criteria = TASKS_SCHEMA["properties"]["tasks"]["items"]["properties"]["acceptance_criteria"]
    assert criteria["minItems"] == 1
