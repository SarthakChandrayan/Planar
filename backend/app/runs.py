"""Background analysis runs.

A local model on a laptop CPU takes minutes per meeting, which is too long
for one HTTP request. A run is queued, processed by a single worker thread
(one model, one CPU: running two at once only makes both slower), and saved
as JSON under ``runs_dir`` so a browser refresh or a restart never loses it.
"""

import json
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from app.domain import ImplementationPlan, MeetingAnalysis
from app.eta import (
    HISTORY_RUNS,
    EtaModel,
    StageTiming,
    chunk_count,
    kilotokens_per_chunk,
    stage_key,
    stage_sequence,
)

logger = logging.getLogger(__name__)

_RUN_ID_CHARS = 12
_DEFAULT_CHUNK_MAX_TOKENS = 8000


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_FINISHED = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}


class RunProgress(BaseModel):
    stage: str = "Queued"
    step: int = 0
    total_steps: int = 0
    stage_tokens: int = 0
    total_tokens: int = 0
    # Estimated seconds until the run finishes; None once it has finished.
    eta_seconds: int | None = None


class RunSummary(BaseModel):
    id: str
    title: str
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    transcript_chars: int
    progress: RunProgress = Field(default_factory=RunProgress)
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class Run(RunSummary):
    transcript: str
    include_plan: bool = True
    analysis: MeetingAnalysis | None = None
    plan: ImplementationPlan | None = None
    # How long each stage took; feeds future time estimates.
    stage_timings: list[StageTiming] = Field(default_factory=list)

    def summary(self) -> RunSummary:
        return RunSummary.model_validate(self.model_dump(include=set(RunSummary.model_fields)))


class RunCancelled(Exception):
    """Raised inside a run when the user cancelled it."""


class RunNotFound(Exception):
    pass


class Estimate(BaseModel):
    seconds: int
    chunks: int
    basis: str


class RunContext:
    """Handed to the runner: reports progress and checks for cancellation."""

    def __init__(self, manager: "RunManager", run_id: str) -> None:
        self._manager = manager
        self._run_id = run_id

    def stage(self, label: str, step: int, total: int) -> None:
        self.check_cancelled()
        self._manager._update_progress(self._run_id, stage=label, step=step, total=total)

    def tokens(self, count: int) -> None:
        self.check_cancelled()
        self._manager._update_progress(self._run_id, tokens=count)

    def warn(self, message: str) -> None:
        self._manager._add_warning(self._run_id, message)

    def check_cancelled(self) -> None:
        if self._manager._is_cancel_requested(self._run_id):
            raise RunCancelled()


# Fills run.analysis / run.plan. Raises to fail the run.
Runner = Callable[[Run, RunContext], tuple[MeetingAnalysis, ImplementationPlan | None]]
ErrorMessage = Callable[[Exception], str]


class RunManager:
    def __init__(
        self,
        runs_dir: Path,
        runner: Runner,
        error_message: ErrorMessage = str,
        chunk_max_tokens: int = _DEFAULT_CHUNK_MAX_TOKENS,
    ) -> None:
        self._dir = runs_dir
        self._runner = runner
        self._error_message = error_message
        self._chunk_max_tokens = chunk_max_tokens
        self._lock = threading.Lock()
        self._runs: dict[str, Run] = {}
        self._stage_started: dict[str, float] = {}
        self._eta = EtaModel()
        self._cancel: set[str] = set()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._dir.mkdir(parents=True, exist_ok=True)
        self._load()
        self._refresh_eta_model()

    # ------------------------------------------------------------------ public

    def start(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._work, name="run-worker", daemon=True)
            self._worker.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._lock:
            self._cancel.update(
                run_id for run_id, run in self._runs.items() if run.status not in _FINISHED
            )
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout)

    def submit(self, transcript: str, title: str | None, include_plan: bool) -> Run:
        run = Run(
            id=uuid.uuid4().hex[:_RUN_ID_CHARS],
            title=title or _title_from(transcript),
            status=RunStatus.QUEUED,
            created_at=_now(),
            transcript_chars=len(transcript),
            transcript=transcript,
            include_plan=include_plan,
        )
        with self._lock:
            self._runs[run.id] = run
            snapshot = self._view(run)
        self._save(snapshot)
        self._queue.put(run.id)
        logger.info("run_queued id=%s chars=%d", run.id, run.transcript_chars)
        return snapshot

    def get(self, run_id: str) -> Run:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFound(run_id)
            return self._view(run)

    def list(self, limit: int = 50) -> list[RunSummary]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
            return [self._view(run).summary() for run in runs[:limit]]

    def estimate(self, transcript_chars: int, include_plan: bool = True) -> Estimate:
        """How long a transcript of this size should take on this machine."""
        with self._lock:
            seconds = self._eta.total(transcript_chars, self._chunk_max_tokens, include_plan)
            return Estimate(
                seconds=round(seconds),
                chunks=chunk_count(transcript_chars, self._chunk_max_tokens),
                basis=self._eta.basis,
            )

    def cancel(self, run_id: str) -> Run:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFound(run_id)
            if run.status in _FINISHED:
                return run.model_copy(deep=True)
            self._cancel.add(run_id)
            if run.status == RunStatus.QUEUED:
                self._finish_locked(run, RunStatus.CANCELLED, error=None)
            return self._view(run)

    def delete(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFound(run_id)
            if run.status not in _FINISHED:
                self._cancel.add(run_id)
            del self._runs[run_id]
        self._path(run_id).unlink(missing_ok=True)

    def wait(self, run_id: str, timeout: float) -> Run:
        """Block until a run finishes (for tests and scripts)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.get(run_id)
            if run.status in _FINISHED:
                return run
            time.sleep(0.02)
        raise TimeoutError(run_id)

    # ----------------------------------------------------------------- worker

    def _work(self) -> None:
        while True:
            run_id = self._queue.get()
            if run_id is None:
                return
            with self._lock:
                run = self._runs.get(run_id)
                if run is None or run.status != RunStatus.QUEUED:
                    continue
                run.status = RunStatus.RUNNING
                run.started_at = _now()
                run.progress = RunProgress(stage="Starting")
                snapshot = run.model_copy(deep=True)
            self._save(snapshot)
            self._execute(snapshot)

    def _execute(self, snapshot: Run) -> None:
        context = RunContext(self, snapshot.id)
        logger.info("run_started id=%s", snapshot.id)
        try:
            analysis, plan = self._runner(snapshot, context)
        except RunCancelled:
            self._finish(snapshot.id, RunStatus.CANCELLED, error=None)
            logger.info("run_cancelled id=%s", snapshot.id)
            return
        except Exception as exc:  # noqa: BLE001 - every failure must end the run
            logger.exception("run_failed id=%s", snapshot.id)
            self._finish(snapshot.id, RunStatus.FAILED, error=self._error_message(exc))
            return
        self._finish(snapshot.id, RunStatus.SUCCEEDED, error=None, analysis=analysis, plan=plan)
        logger.info("run_succeeded id=%s", snapshot.id)

    # ---------------------------------------------------------------- updates

    def _update_progress(
        self,
        run_id: str,
        *,
        stage: str | None = None,
        step: int | None = None,
        total: int | None = None,
        tokens: int | None = None,
    ) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            progress = run.progress
            if stage is not None:
                self._close_stage_locked(run)
                self._stage_started[run_id] = time.monotonic()
                progress.stage = stage
                progress.step = step or progress.step
                progress.total_steps = total or progress.total_steps
                progress.stage_tokens = 0
            if tokens is not None:
                progress.total_tokens += max(tokens - progress.stage_tokens, 0)
                progress.stage_tokens = tokens

    def _add_warning(self, run_id: str, message: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                run.warnings.append(message)

    def _is_cancel_requested(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._cancel or run_id not in self._runs

    def _finish(self, run_id: str, status: RunStatus, *, error: str | None, **result) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            for key, value in result.items():
                setattr(run, key, value)
            if status == RunStatus.SUCCEEDED:
                self._close_stage_locked(run)
            self._finish_locked(run, status, error=error)
            if status == RunStatus.SUCCEEDED:
                self._refresh_eta_model_locked()

    def _finish_locked(self, run: Run, status: RunStatus, *, error: str | None) -> None:
        self._stage_started.pop(run.id, None)
        run.progress.eta_seconds = None
        run.status = status
        run.error = error
        run.finished_at = _now()
        run.progress.stage = {
            RunStatus.SUCCEEDED: "Done",
            RunStatus.FAILED: "Failed",
            RunStatus.CANCELLED: "Cancelled",
        }[status]
        self._cancel.discard(run.id)
        self._save(run)

    # ----------------------------------------------------------------- timing

    def _chunks_of(self, run: Run) -> int:
        plan_steps = 1 if run.include_plan else 0
        if run.progress.total_steps > plan_steps:
            return max(1, (run.progress.total_steps - plan_steps) // 4)
        return chunk_count(run.transcript_chars, self._chunk_max_tokens)

    def _close_stage_locked(self, run: Run) -> None:
        """Record how long the stage that is ending took."""
        started = self._stage_started.get(run.id)
        if started is None or run.progress.step <= 0:
            return
        run.stage_timings.append(
            StageTiming(
                stage=stage_key(run.progress.stage),
                seconds=round(time.monotonic() - started, 1),
                kilotokens=round(
                    kilotokens_per_chunk(run.transcript_chars, self._chunks_of(run)), 2
                ),
            )
        )

    def _refresh_eta_model(self) -> None:
        with self._lock:
            self._refresh_eta_model_locked()

    def _refresh_eta_model_locked(self) -> None:
        finished = sorted(
            (r for r in self._runs.values() if r.status == RunStatus.SUCCEEDED and r.stage_timings),
            key=lambda r: r.created_at,
            reverse=True,
        )
        self._eta = EtaModel(run.stage_timings for run in finished[:HISTORY_RUNS])

    def _view(self, run: Run) -> Run:
        """A copy of the run with a fresh time estimate."""
        view = run.model_copy(deep=True)
        if run.status == RunStatus.QUEUED:
            view.progress.eta_seconds = round(
                self._eta.total(run.transcript_chars, self._chunk_max_tokens, run.include_plan)
            )
        elif run.status == RunStatus.RUNNING:
            chunks = self._chunks_of(run)
            started = self._stage_started.get(run.id)
            elapsed = time.monotonic() - started if started is not None else 0.0
            view.progress.eta_seconds = round(
                self._eta.remaining(
                    stage_sequence(chunks, run.include_plan),
                    run.progress.step - 1,
                    elapsed,
                    kilotokens_per_chunk(run.transcript_chars, chunks),
                    run.stage_timings,
                )
            )
        else:
            view.progress.eta_seconds = None
        return view

    # ------------------------------------------------------------ persistence

    def _path(self, run_id: str) -> Path:
        return self._dir / f"{run_id}.json"

    def _save(self, run: Run) -> None:
        path = self._path(run.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def _load(self) -> None:
        for path in sorted(self._dir.glob("*.json")):
            try:
                run = Run.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                logger.warning("run_load_failed path=%s error=%s", path.name, exc)
                continue
            if run.status not in _FINISHED:
                # The process stopped mid-run; the work is gone.
                run.status = RunStatus.FAILED
                run.error = "The server stopped before this run finished. Start it again."
                run.finished_at = run.finished_at or _now()
                self._save(run)
            self._runs[run.id] = run


def _now() -> datetime:
    return datetime.now(UTC)


_MAX_TITLE_LINE_CHARS = 100


def _title_from(transcript: str) -> str:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    for line in lines:
        if line.lower().startswith(("meeting:", "title:", "subject:")):
            title = line.split(":", 1)[1].strip()
            if title:
                return title[:120]
    # Otherwise a short first line that isn't someone speaking ("Maya: ...").
    if lines:
        first = lines[0].lstrip("#").strip()
        speaking = ":" in first and not first.endswith(":")
        if first and len(first) <= _MAX_TITLE_LINE_CHARS and not speaking:
            return first
    return "Untitled meeting"
