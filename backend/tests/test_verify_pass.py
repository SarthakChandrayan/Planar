"""The optional verify pass: label decisions and requirements against their lines."""

from app.analysis.analyzer import VERIFY_STAGE, MeetingAnalyzer
from tests.fakes import ScriptedLLM

NOTES = (
    "Meeting: Q4 budget\n"                                                                        # L1
    "Sameer: I'd rather cut the conference entirely until the pipeline improves.\n"              # L2
    "Rahul: That would be premature. Two larger deals came from last year's event.\n"             # L3
    "Priya: We're not deciding that now. Rahul, split the travel budget by Tuesday.\n"            # L4
    "Ananya: The support vendor wants a six-month commitment for a 9% discount.\n"                # L5
    "Priya: Then don't sign the six-month support contract yet.\n"                               # L6
    "Meera: I haven't finalized the conversion threshold for the second tranche.\n"              # L7
    "Priya: We keep the approved Q4 budget of 1.75 crore as the control baseline."               # L8
)

DECISIONS = {"decisions": [
    {"statement": "Do not cut the conference entirely.", "lines": [2]},
    {"statement": "Do not sign the six-month support contract yet.", "lines": [6]},
    {"statement": "Keep the approved Q4 budget of 1.75 crore as the control baseline.", "lines": [8]},
]}
REQUIREMENTS = {"requirements": [
    {"statement": "The travel budget must be split by Tuesday.", "lines": [4]},
    {"statement": "The second tranche must have a conversion threshold.", "lines": [7]},
]}
CHECKS = {"checks": [
    {"id": "DEC-001", "status": "proposed", "question": ""},
    {"id": "DEC-002", "status": "deferred", "question": "Whether to sign the six-month support contract"},
    {"id": "DEC-003", "status": "agreed", "question": ""},
    {"id": "REQ-001", "status": "assignment", "question": ""},
    {"id": "REQ-002", "status": "open", "question": "Which conversion threshold releases the second tranche"},
]}


def _run(verify: bool):
    llm = ScriptedLLM({"decisions": DECISIONS, "requirements": REQUIREMENTS, "checks": CHECKS})
    analyzer = MeetingAnalyzer(llm, verify=verify)
    return llm, analyzer, analyzer.run(NOTES)


def test_verify_is_off_by_default() -> None:
    llm = ScriptedLLM({"decisions": DECISIONS})
    MeetingAnalyzer(llm).run(NOTES)
    assert "checks" not in [key for key, _ in llm.calls]


def test_proposals_and_assignments_go_open_and_deferred_become_questions() -> None:
    _, _, outcome = _run(verify=True)
    a = outcome.analysis
    assert [d.statement for d in a.decisions] == [
        "Do not sign the six-month support contract yet.",
        "Keep the approved Q4 budget of 1.75 crore as the control baseline.",
    ]
    # Renumbered after the proposal was dropped.
    assert [d.id for d in a.decisions] == ["DEC-001", "DEC-002"]
    assert a.requirements == []
    assert [q.question for q in a.open_questions] == [
        "Whether to sign the six-month support contract?",
        "Which conversion threshold releases the second tranche?",
    ]
    reasons = {d["text"]: d["reason"] for d in outcome.dropped}
    assert "only proposed" in reasons["Do not cut the conference entirely."]
    assert "task" in reasons["The travel budget must be split by Tuesday."]


def test_the_check_sees_the_lines_around_each_item() -> None:
    llm, _, _ = _run(verify=True)
    prompt = llm.prompts_for("checks")[0]
    block = prompt.split("DEC-001: Do not cut the conference entirely.")[1].split("DEC-002")[0]
    assert "We're not deciding that now" in block  # two lines after the cited one


def test_verify_stage_is_planned_and_reported() -> None:
    reported: list[str] = []

    class Recorder:
        def stage(self, label: str, step: int, total: int) -> None:
            reported.append(label)

        def tokens(self, count: int) -> None:
            pass

    analyzer = MeetingAnalyzer(ScriptedLLM({"decisions": DECISIONS, "checks": CHECKS}), verify=True)
    analyzer.run(NOTES, Recorder())
    assert reported[-1] == VERIFY_STAGE
    assert reported == analyzer.stage_labels(NOTES)


def test_unusable_check_keeps_everything_and_warns() -> None:
    llm = ScriptedLLM({"decisions": DECISIONS, "checks": "not json"})
    outcome = MeetingAnalyzer(llm, verify=True).run(NOTES)
    assert len(outcome.analysis.decisions) == 3
    assert any("consistency check" in w for w in outcome.warnings)
