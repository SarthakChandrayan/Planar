from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.analysis import MeetingAnalyzer
from app.config import Settings
from app.domain import ImplementationPlan, MeetingAnalysis
from app.llm.ollama import OllamaProvider
from app.llm.provider import LLMProvider
from app.planning import ImplementationPlanner, PlanValidationError
from app.runs import PlanContext, PlanRunner, Run, RunContext, RunManager, Runner


@lru_cache
def get_settings() -> Settings:
    return Settings()


# A regenerated plan should be a real alternative, not a copy of the last one.
_REGENERATE_TEMPERATURE = 0.6


def build_provider(
    settings: Settings,
    *,
    temperature: float | None = None,
    seed: int | None = None,
) -> LLMProvider:
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        think=settings.ollama_think,
        timeout_seconds=settings.ollama_timeout_seconds,
        num_ctx=settings.ollama_num_ctx,
        temperature=settings.llm_temperature if temperature is None else temperature,
        seed=settings.llm_seed if seed is None else seed,
        max_output_tokens=settings.llm_max_output_tokens,
        keep_alive=settings.ollama_keep_alive,
    )


def build_analyzer(llm: LLMProvider, settings: Settings) -> MeetingAnalyzer:
    return MeetingAnalyzer(
        llm,
        chunk_max_tokens=settings.chunk_max_tokens,
        max_transcript_chars=settings.max_transcript_chars,
        second_look=settings.analysis_second_look,
        verify=settings.analysis_verify,
    )


def build_runner(settings: Settings) -> Runner:
    """The work a background run performs: analysis, then (optionally) a plan."""

    def run(job: Run, context: RunContext) -> tuple[MeetingAnalysis, ImplementationPlan | None]:
        llm = build_provider(settings)
        analyzer = build_analyzer(llm, settings)
        stages = analyzer.stage_labels(job.transcript) + (["Implementation plan"] if job.include_plan else [])
        context.plan_stages(stages)
        extra = 1 if job.include_plan else 0
        outcome = analyzer.run(job.transcript, context, extra_stages=extra)
        for warning in outcome.warnings:
            context.warn(warning)
        context.record_dropped(outcome.dropped)
        if not job.include_plan:
            return outcome.analysis, None

        context.stage("Implementation plan", len(stages), len(stages))
        try:
            plan = ImplementationPlanner(llm).plan(
                outcome.analysis, title=job.title, progress=context
            )
        except PlanValidationError:
            context.warn(
                "The implementation plan could not be generated. The meeting record is complete."
            )
            plan = None
        return outcome.analysis, plan

    return run


def build_plan_runner(settings: Settings) -> PlanRunner:
    """Regenerate: same record, some sampling randomness, a seed per version.

    Each version is still reproducible (same version, same seed), but differs
    from the previous one.
    """

    def run(job: Run, context: PlanContext, version: int) -> ImplementationPlan:
        llm = build_provider(
            settings,
            temperature=max(settings.llm_temperature, _REGENERATE_TEMPERATURE),
            seed=settings.llm_seed + version,
        )
        return ImplementationPlanner(llm).plan(job.analysis, title=job.title, progress=context)

    return run


def get_llm_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LLMProvider:
    return build_provider(settings)


def get_meeting_analyzer(
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeetingAnalyzer:
    return build_analyzer(llm, settings)


def get_implementation_planner(
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> ImplementationPlanner:
    return ImplementationPlanner(llm)


def get_run_manager(request: Request) -> RunManager:
    manager = getattr(request.app.state, "run_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="The run queue is not started.")
    return manager


def require_dev_endpoints(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.enable_dev_endpoints:
        raise HTTPException(status_code=404, detail="Not Found")
