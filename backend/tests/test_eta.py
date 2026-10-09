from pathlib import Path

import pytest

from app.domain import MeetingAnalysis
from app.eta import (
    DEFAULT_SECONDS_PER_KTOK,
    PLAN_STAGE,
    EtaModel,
    StageTiming,
    chunk_count,
    stage_key,
    stage_sequence,
)
from app.runs import Run, RunContext, RunManager

PAYMENT_SAMPLE_CHARS = 10_188  # measured: 9.9 min end to end on CPU


def test_default_estimate_matches_measured_cpu_run() -> None:
    minutes = EtaModel().total(PAYMENT_SAMPLE_CHARS, 8000, include_plan=True) / 60
    assert 8.5 <= minutes <= 11.5


def test_bigger_meetings_take_longer_and_get_chunked() -> None:
    model = EtaModel()
    one_hour = 9000 * 6  # ~9k words
    assert chunk_count(one_hour, 8000) == 3
    assert model.total(one_hour, 8000, True) > model.total(PAYMENT_SAMPLE_CHARS, 8000, True)


def test_tiny_transcripts_still_pay_fixed_costs() -> None:
    assert EtaModel().total(200, 8000, True) == EtaModel().total(2000, 8000, True)


def test_stage_sequence_and_keys() -> None:
    assert stage_sequence(2, True, second_look=False)[-1] == PLAN_STAGE
    assert len(stage_sequence(2, True, second_look=False)) == 9
    assert len(stage_sequence(1, False, second_look=False)) == 4
    assert stage_key("Tasks · part 2/3") == "Tasks"


def test_second_look_stages_are_planned_and_timed_separately() -> None:
    stages = stage_sequence(2, True)
    # Per part: four passes plus a second look at decisions and requirements.
    assert len(stages) == 2 * 6 + 1
    assert stages[:4] == ["Decisions", "Decisions · second look", "Requirements", "Requirements · second look"]
    assert stage_key("Decisions · part 1/2 · second look") == "Decisions · second look"


def test_history_replaces_defaults() -> None:
    fast = [StageTiming(stage="Decisions", seconds=10, kilotokens=2)]
    model = EtaModel([fast])
    assert model.basis == "this machine"
    assert model.expected("Decisions", 2) == pytest.approx(10)
    # Stages without history keep their defaults.
    assert model.expected("Tasks", 2) == pytest.approx(DEFAULT_SECONDS_PER_KTOK["Tasks"] * 2)


def test_remaining_counts_down_and_adapts_to_speed() -> None:
    model = EtaModel()
    stages = stage_sequence(1, True, second_look=False)
    ktok = 2.0
    at_start = model.remaining(stages, 0, 0, ktok, [])
    later = model.remaining(stages, 0, 30, ktok, [])
    assert at_start - later == pytest.approx(30)

    # First stage ran twice as fast as expected -> the rest is halved.
    done = [StageTiming(stage="Decisions", seconds=model.expected("Decisions", ktok) / 2, kilotokens=ktok)]
    rest = sum(model.expected(s, ktok) for s in stages[1:])
    assert model.remaining(stages, 1, 0, ktok, done) == pytest.approx(rest / 2)


def test_overrunning_stage_never_shows_zero() -> None:
    model = EtaModel()
    stages = stage_sequence(1, False, second_look=False)
    assert model.remaining(stages, 3, 10_000, 2.0, []) >= 15


def _runner(job: Run, context: RunContext):
    for step, stage in enumerate(stage_sequence(1, True, second_look=False), start=1):
        context.stage(stage, step, 5)
    return MeetingAnalysis(), None


def test_runs_record_stage_timings_and_report_eta(tmp_path: Path) -> None:
    manager = RunManager(tmp_path, _runner)
    queued = manager.submit("Lin: We will ship it. " * 100, None, include_plan=True)
    assert queued.progress.eta_seconds and queued.progress.eta_seconds > 0
    assert manager.estimate(2200).basis == "default"

    manager.start()
    run = manager.wait(queued.id, timeout=5)
    manager.stop()

    assert [t.stage for t in run.stage_timings] == stage_sequence(1, True, second_look=False)
    assert run.progress.eta_seconds is None
    # The finished run now informs estimates, and survives a restart.
    assert manager.estimate(2200).basis == "this machine"
    assert RunManager(tmp_path, _runner).estimate(2200).basis == "this machine"
