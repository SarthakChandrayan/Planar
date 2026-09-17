from typing import Annotated

from fastapi import APIRouter, Depends

from app.analysis import MeetingAnalyzer
from app.api.schemas import AnalyzeMeetingRequest, CreateImplementationPlanRequest
from app.dependencies import get_implementation_planner, get_meeting_analyzer
from app.domain import ImplementationPlan, MeetingAnalysis
from app.planning import ImplementationPlanner

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


@router.post("/analyze", response_model=MeetingAnalysis)
def analyze_meeting(
    body: AnalyzeMeetingRequest,
    analyzer: Annotated[MeetingAnalyzer, Depends(get_meeting_analyzer)],
) -> MeetingAnalysis:
    return analyzer.analyze(body.transcript)


@router.post("/implementation-plan", response_model=ImplementationPlan)
def create_implementation_plan(
    body: CreateImplementationPlanRequest,
    planner: Annotated[ImplementationPlanner, Depends(get_implementation_planner)],
) -> ImplementationPlan:
    return planner.plan(body.analysis, title=body.title)
