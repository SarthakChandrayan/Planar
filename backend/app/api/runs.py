from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse

from app.analysis import TranscriptTooLongError
from app.api.schemas import CreateRunRequest
from app.config import Settings
from app.dependencies import get_run_manager, get_settings
from app.report import render_markdown
from app.runs import Estimate, Run, RunManager, RunNotFound, RunStatus, RunSummary

router = APIRouter(prefix="/api/runs", tags=["runs"])

Manager = Annotated[RunManager, Depends(get_run_manager)]


def _get(manager: RunManager, run_id: str) -> Run:
    try:
        return manager.get(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found.") from None


@router.post("", response_model=Run, status_code=status.HTTP_202_ACCEPTED)
def create_run(
    body: CreateRunRequest,
    manager: Manager,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Run:
    if len(body.transcript) > settings.max_transcript_chars:
        raise TranscriptTooLongError(
            f"Transcript is {len(body.transcript):,} characters; the limit is "
            f"{settings.max_transcript_chars:,}."
        )
    return manager.submit(body.transcript, body.title, body.include_plan)


@router.get("", response_model=list[RunSummary])
def list_runs(manager: Manager) -> list[RunSummary]:
    return manager.list()


@router.get("/estimate", response_model=Estimate)
def estimate_run(
    manager: Manager,
    chars: Annotated[int, Query(ge=0, le=10_000_000)],
    include_plan: bool = True,
) -> Estimate:
    """Expected run time for a transcript of this many characters."""
    return manager.estimate(chars, include_plan)


@router.get("/{run_id}", response_model=Run)
def get_run(run_id: str, manager: Manager) -> Run:
    return _get(manager, run_id)


@router.post("/{run_id}/cancel", response_model=Run)
def cancel_run(run_id: str, manager: Manager) -> Run:
    try:
        return manager.cancel(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found.") from None


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: str, manager: Manager) -> Response:
    try:
        manager.delete(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found.") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{run_id}/report.md", response_class=PlainTextResponse)
def run_report(run_id: str, manager: Manager) -> PlainTextResponse:
    run = _get(manager, run_id)
    if run.status != RunStatus.SUCCEEDED:
        raise HTTPException(status_code=409, detail="The run has not finished.")
    filename = "".join(c if c.isalnum() or c in "-_" else "-" for c in run.title)[:60]
    return PlainTextResponse(
        render_markdown(run),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename or "report"}.md"'
        },
    )
