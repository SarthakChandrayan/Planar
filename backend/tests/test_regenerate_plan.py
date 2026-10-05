import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_run_manager
from app.domain import ImplementationPlan, MeetingAnalysis
from app.errors import error_message
from app.llm import LLMUnavailableError
from app.main import app
from app.planning import ImplementationPlanner
from app.runs import PlanContext, Run, RunContext, RunManager
from tests.fakes import ScriptedLLM
from tests.test_implementation_planner import PLAN, _analysis


def _analyze(job: Run, context: RunContext) -> tuple[MeetingAnalysis, ImplementationPlan]:
    analysis = _analysis()
    return analysis, ImplementationPlanner(ScriptedLLM({"plan": PLAN})).plan(analysis)


def _replan(job: Run, context: PlanContext, version: int) -> ImplementationPlan:
    context.tokens(1)
    answer = dict(PLAN, summary=f"Plan version {version}.")
    return ImplementationPlanner(ScriptedLLM({"plan": answer})).plan(job.analysis, progress=context)


def _wait_plan(manager: RunManager, run_id: str, timeout: float = 5) -> Run:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.get(run_id)
        if run.plan_job is None or run.plan_job.status == "failed":
            return run
        time.sleep(0.02)
    raise TimeoutError(run_id)


@pytest.fixture
def finished(tmp_path: Path) -> Iterator[tuple[RunManager, str]]:
    manager = RunManager(tmp_path, _analyze, error_message=error_message, plan_runner=_replan)
    manager.start()
    run_id = manager.submit("Lin: We will ship it on Friday.", "Ship", include_plan=True).id
    manager.wait(run_id, timeout=5)
    yield manager, run_id
    manager.stop()


def test_regenerated_plan_replaces_and_is_saved(finished, tmp_path: Path) -> None:
    manager, run_id = finished
    queued = manager.regenerate_plan(run_id)
    assert queued.plan_job is not None and queued.plan_job.version == 2
    assert queued.plan_job.eta_seconds and queued.plan_job.eta_seconds > 0

    run = _wait_plan(manager, run_id)
    assert run.plan_job is None
    assert run.plan_version == 2
    assert run.plan.summary == "Plan version 2."
    assert run.stage_timings[-1].stage == "Implementation plan"
    # Saved: a restarted server sees the new plan.
    assert RunManager(tmp_path, _analyze).get(run_id).plan.summary == "Plan version 2."

    manager.regenerate_plan(run_id)
    assert _wait_plan(manager, run_id).plan.summary == "Plan version 3."


def test_regenerate_rejects_unfinished_or_busy_runs(tmp_path: Path) -> None:
    gate = threading.Event()

    def slow_replan(job: Run, context: PlanContext, version: int) -> ImplementationPlan:
        gate.wait(5)
        return _replan(job, context, version)

    manager = RunManager(tmp_path, _analyze, plan_runner=slow_replan)
    queued_id = manager.submit("Lin: hello there.", None, include_plan=True).id
    with pytest.raises(Exception, match="has to finish"):
        manager.regenerate_plan(queued_id)  # worker not started: still queued

    manager.start()
    manager.wait(queued_id, timeout=5)
    manager.regenerate_plan(queued_id)
    with pytest.raises(Exception, match="already being written"):
        manager.regenerate_plan(queued_id)
    gate.set()
    _wait_plan(manager, queued_id)
    manager.stop()


def test_cancel_running_plan_keeps_old_plan(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_replan(job: Run, context: PlanContext, version: int) -> ImplementationPlan:
        started.set()
        release.wait(5)
        context.tokens(5)  # raises once cancelled
        raise AssertionError("should have been cancelled")

    manager = RunManager(tmp_path, _analyze, plan_runner=blocking_replan)
    manager.start()
    run_id = manager.submit("Lin: hello there.", None, include_plan=True).id
    old_summary = manager.wait(run_id, timeout=5).plan.summary

    manager.regenerate_plan(run_id)
    assert started.wait(5)
    cancelled = manager.cancel_plan(run_id)
    assert cancelled.plan_job is None
    release.set()

    run = manager.get(run_id)
    assert run.plan.summary == old_summary and run.plan_version == 1
    manager.stop()


def test_failed_plan_reports_error_and_can_retry(tmp_path: Path) -> None:
    attempts: list[int] = []

    def flaky(job: Run, context: PlanContext, version: int) -> ImplementationPlan:
        attempts.append(version)
        if len(attempts) == 1:
            raise LLMUnavailableError("Ollama is not reachable.")
        return _replan(job, context, version)

    manager = RunManager(tmp_path, _analyze, error_message=error_message, plan_runner=flaky)
    manager.start()
    run_id = manager.submit("Lin: hello there.", None, include_plan=True).id
    manager.wait(run_id, timeout=5)

    manager.regenerate_plan(run_id)
    failed = _wait_plan(manager, run_id)
    assert failed.plan_job.status == "failed"
    assert failed.plan_job.error == "Ollama is not reachable."
    assert failed.plan_version == 1

    manager.regenerate_plan(run_id)  # a failed job doesn't block a retry
    assert _wait_plan(manager, run_id).plan_version == 2
    manager.stop()


def test_interrupted_plan_job_is_marked_failed_on_restart(tmp_path: Path) -> None:
    manager = RunManager(tmp_path, _analyze, plan_runner=_replan)
    manager.start()
    run_id = manager.submit("Lin: hello there.", None, include_plan=True).id
    manager.wait(run_id, timeout=5)
    manager.stop()

    paused = RunManager(tmp_path, _analyze, plan_runner=_replan)  # worker not started
    paused.regenerate_plan(run_id)

    reloaded = RunManager(tmp_path, _analyze, plan_runner=_replan)
    job = reloaded.get(run_id).plan_job
    assert job is not None and job.status == "failed" and "stopped" in job.error


def test_each_version_samples_differently(monkeypatch) -> None:
    from app import dependencies
    from app.config import Settings

    calls: list[dict] = []

    def fake_provider(settings, **kwargs):
        calls.append(kwargs)
        return ScriptedLLM({"plan": PLAN})

    monkeypatch.setattr(dependencies, "build_provider", fake_provider)
    runner = dependencies.build_plan_runner(Settings(_env_file=None, llm_seed=42))
    job = Run(
        id="x", title="t", status="succeeded", created_at="2026-01-01T00:00:00Z",
        transcript_chars=1, transcript="x", analysis=_analysis(),
    )
    ctx = type("Ctx", (), {"tokens": lambda self, n: None, "stage": lambda *a: None})()
    runner(job, ctx, 2)
    runner(job, ctx, 3)
    assert calls[0]["temperature"] > 0 and calls[0]["seed"] == 44
    assert calls[1]["seed"] == 45


def test_api_endpoints(finished) -> None:
    manager, run_id = finished
    app.dependency_overrides[get_run_manager] = lambda: manager
    try:
        client = TestClient(app)
        response = client.post(f"/api/runs/{run_id}/plan")
        assert response.status_code == 202
        assert response.json()["plan_job"]["version"] == 2
        _wait_plan(manager, run_id)

        report = client.get(f"/api/runs/{run_id}/report.md").text
        assert "Plan version 2." in report  # downloads use the saved new plan

        assert client.post("/api/runs/missing/plan").status_code == 404
        assert client.post(f"/api/runs/{run_id}/plan/cancel").status_code == 200
    finally:
        app.dependency_overrides.clear()
