from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis import MeetingAnalyzer
from app.dependencies import get_run_manager
from app.domain import ImplementationPlan, MeetingAnalysis
from app.errors import error_message
from app.llm import LLMProvider, LLMUnavailableError
from app.main import app
from app.planning import ImplementationPlanner
from app.runs import Run, RunContext, RunManager
from tests.fakes import FailingLLM, ScriptedLLM
from tests.fixtures.payment_meeting import PAYMENT_MEETING_TRANSCRIPT

ANSWERS = {
    "decisions": {
        "decisions": [{"statement": "Settlement cut-off stays at 22:00 UTC.", "lines": [5]}]
    },
    "tasks": {
        "tasks": [
            {
                "title": "Add idempotency middleware to POST /v1/charges",
                "description": "",
                "owner": "Priya",
                "due": "",
                "priority": "high",
                "acceptance_criteria": [],
                "lines": [9],
                "requirement_ids": [],
            }
        ]
    },
}


def _runner(llm: LLMProvider):
    def run(job: Run, context: RunContext) -> tuple[MeetingAnalysis, ImplementationPlan | None]:
        outcome = MeetingAnalyzer(llm).run(job.transcript, context, extra_stages=1)
        plan = ImplementationPlanner(llm).plan(outcome.analysis, title=job.title, progress=context)
        return outcome.analysis, plan

    return run


@pytest.fixture
def make_client(tmp_path: Path) -> Iterator:
    managers: list[RunManager] = []

    def make(llm: LLMProvider) -> tuple[TestClient, RunManager]:
        manager = RunManager(tmp_path / "runs", _runner(llm), error_message=error_message)
        manager.start()
        managers.append(manager)
        app.dependency_overrides[get_run_manager] = lambda: manager
        return TestClient(app), manager

    yield make
    for manager in managers:
        manager.stop()
    app.dependency_overrides.clear()


def test_run_completes_and_is_retrievable(make_client) -> None:
    client, manager = make_client(ScriptedLLM(ANSWERS))

    created = client.post("/api/runs", json={"transcript": PAYMENT_MEETING_TRANSCRIPT})
    assert created.status_code == 202
    run_id = created.json()["id"]
    assert created.json()["status"] == "queued"

    manager.wait(run_id, timeout=5)
    body = client.get(f"/api/runs/{run_id}").json()

    assert body["status"] == "succeeded"
    assert body["title"] == "Payments platform weekly — 2026-09-04"
    assert body["analysis"]["tasks"][0]["owner"] == "Priya"
    assert body["plan"]["steps"][0]["related_task_ids"] == ["TSK-001"]
    assert body["progress"]["stage"] == "Done"
    assert body["progress"]["total_steps"] == 6


def test_runs_are_listed_newest_first_without_payload(make_client) -> None:
    client, manager = make_client(ScriptedLLM(ANSWERS))
    first = client.post("/api/runs", json={"transcript": "Meeting: Alpha\nLin: We will ship it."}).json()
    second = client.post("/api/runs", json={"transcript": "Meeting: Beta\nLin: We will ship it."}).json()
    manager.wait(second["id"], timeout=5)

    listed = client.get("/api/runs").json()
    assert [r["id"] for r in listed] == [second["id"], first["id"]]
    assert listed[0]["title"] == "Beta"
    assert "analysis" not in listed[0]


def test_failed_run_records_user_facing_error(make_client) -> None:
    client, manager = make_client(FailingLLM(LLMUnavailableError("Ollama is down.")))
    run_id = client.post("/api/runs", json={"transcript": PAYMENT_MEETING_TRANSCRIPT}).json()["id"]

    run = manager.wait(run_id, timeout=5)
    assert run.status == "failed"
    assert run.error == "Ollama is down."


def test_markdown_report(make_client) -> None:
    client, manager = make_client(ScriptedLLM(ANSWERS))
    run_id = client.post(
        "/api/runs", json={"transcript": PAYMENT_MEETING_TRANSCRIPT, "title": "Payments sync"}
    ).json()["id"]
    manager.wait(run_id, timeout=5)

    response = client.get(f"/api/runs/{run_id}/report.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "# Payments sync" in response.text
    assert "- [ ] **TSK-001** Add idempotency middleware" in response.text
    assert "(Priya, L13)" in response.text


def test_unknown_run_is_404(make_client) -> None:
    client, _ = make_client(ScriptedLLM())
    assert client.get("/api/runs/nope").status_code == 404
    assert client.post("/api/runs/nope/cancel").status_code == 404
    assert client.delete("/api/runs/nope").status_code == 404


def test_blank_transcript_is_rejected(make_client) -> None:
    client, _ = make_client(ScriptedLLM())
    assert client.post("/api/runs", json={"transcript": "  "}).status_code == 422


def test_runs_survive_a_restart(tmp_path: Path) -> None:
    manager = RunManager(tmp_path, _runner(ScriptedLLM(ANSWERS)))
    manager.start()
    run_id = manager.submit(PAYMENT_MEETING_TRANSCRIPT, "Kept", include_plan=True).id
    manager.wait(run_id, timeout=5)
    manager.stop()

    reloaded = RunManager(tmp_path, _runner(ScriptedLLM()))
    run = reloaded.get(run_id)
    assert run.status == "succeeded"
    assert run.analysis is not None and run.analysis.tasks


def test_interrupted_runs_are_marked_failed_on_restart(tmp_path: Path) -> None:
    manager = RunManager(tmp_path, _runner(ScriptedLLM()))  # worker never started
    run_id = manager.submit(PAYMENT_MEETING_TRANSCRIPT, None, include_plan=False).id

    reloaded = RunManager(tmp_path, _runner(ScriptedLLM()))
    run = reloaded.get(run_id)
    assert run.status == "failed"
    assert "stopped" in (run.error or "")


def test_cancel_queued_run(tmp_path: Path) -> None:
    manager = RunManager(tmp_path, _runner(ScriptedLLM()))  # worker not started
    run_id = manager.submit(PAYMENT_MEETING_TRANSCRIPT, None, include_plan=False).id
    assert manager.cancel(run_id).status == "cancelled"


def test_cancel_running_run_stops_at_next_token(tmp_path: Path) -> None:
    import threading

    started = threading.Event()
    release = threading.Event()

    def slow_runner(job: Run, context: RunContext):
        started.set()
        release.wait(5)
        context.tokens(1)  # raises RunCancelled once cancelled
        raise AssertionError("should have been cancelled")

    manager = RunManager(tmp_path, slow_runner)
    manager.start()
    run_id = manager.submit("Lin: hello there team", None, include_plan=False).id
    assert started.wait(5)
    manager.cancel(run_id)
    release.set()
    assert manager.wait(run_id, timeout=5).status == "cancelled"
    manager.stop()


def test_estimate_endpoint(make_client) -> None:
    client, _ = make_client(ScriptedLLM())
    small = client.get("/api/runs/estimate", params={"chars": 3000}).json()
    large = client.get("/api/runs/estimate", params={"chars": 60000}).json()

    assert small["chunks"] == 1 and small["basis"] == "default"
    assert large["chunks"] > 1
    assert large["seconds"] > small["seconds"] > 0
    assert client.get("/api/runs/estimate", params={"chars": -1}).status_code == 422


def test_title_comes_from_header_or_short_first_line(tmp_path: Path) -> None:
    from app.runs import _title_from

    assert _title_from("Meeting: Payments sync\nLin: hi") == "Payments sync"
    assert (
        _title_from("Technical Architecture Review\nMeeting Type: Review\nMaya: hi")
        == "Technical Architecture Review"
    )
    assert _title_from("# Weekly sync\nLin: hi") == "Weekly sync"
    assert _title_from("Lin: We will ship it.\nSam: Agreed.") == "Untitled meeting"
    assert _title_from("x" * 300) == "Untitled meeting"


def test_markdown_report_includes_plan_map_diagram() -> None:
    from app.report import plan_map_mermaid
    from tests.test_implementation_planner import PLAN, _analysis

    analysis = _analysis()
    plan = ImplementationPlanner(ScriptedLLM({"plan": PLAN})).plan(analysis)
    lines = plan_map_mermaid(analysis, plan)
    text = "\n".join(lines)

    assert lines[:4] == ["## Plan map", "", "```mermaid", "flowchart LR"]
    assert 'REQ_001["REQ-001: POST /v1/charges must honor an Idempotency-Key…"]' in text
    assert "REQ_001 --> STEP_001" in text
    assert "STEP_001 --> OWNER_Priya" in text
    assert "DEC_001 --> REQ_001" in text  # requirement's own decision link
    assert text.count("```") == 2


def test_markdown_shows_step_timing() -> None:
    from datetime import UTC, datetime

    from app.report import plan_map_mermaid, render_markdown
    from app.runs import Run
    from tests.test_implementation_planner import PLAN, _analysis

    analysis = _analysis()
    analysis.tasks[0].due = "Friday"
    steps = [dict(PLAN["steps"][0], when="By Friday", decision_ids=[])]
    plan = ImplementationPlanner(ScriptedLLM({"plan": dict(PLAN, steps=steps, outcomes=[])})).plan(analysis)
    run = Run(id="r", title="T", status="succeeded", created_at=datetime.now(UTC),
              transcript_chars=1, transcript="x", analysis=analysis, plan=plan)

    assert "1. **Build idempotency middleware** · By Friday" in render_markdown(run)
    assert "<br/><i>By Friday</i>" in "\n".join(plan_map_mermaid(analysis, plan))
