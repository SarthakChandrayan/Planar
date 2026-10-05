import logging

from pydantic import ValidationError

from app.analysis.parsing import parse_json_object
from app.domain import (
    PLAN_PREFIX,
    STEP_PREFIX,
    ImplementationPlan,
    ImplementationPlanStep,
    MeetingAnalysis,
    Requirement,
    SourceReference,
    Task,
    format_item_id,
)
from app.llm import LLMProvider, LLMProviderError
from app.planning.errors import PlanValidationError
from app.planning.prompts import build_implementation_plan_prompt
from app.planning.schemas import (
    PLAN_SCHEMA,
    ExtractedImplementationPlan,
    ExtractedPlanStep,
)
from app.progress import NullProgress, Progress

logger = logging.getLogger(__name__)

_DEFAULT_TITLE = "Implementation plan"
_EMPTY_SUMMARY = (
    "The meeting record has no requirements or tasks, so there is nothing to plan yet."
)
_MAX_EVIDENCE_PER_STEP = 3
_MAX_CRITERIA = 8


class ImplementationPlanner:
    """Turn a validated MeetingAnalysis into an ImplementationPlan via LLMProvider.

    The model orders and groups work and cites record IDs. Evidence comes
    from the cited items, so a plan step is always traceable to transcript
    lines. Tasks the model leaves out are appended as their own steps.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def plan(
        self,
        analysis: MeetingAnalysis,
        *,
        title: str | None = None,
        progress: Progress | None = None,
    ) -> ImplementationPlan:
        progress = progress or NullProgress()
        if not analysis.requirements and not analysis.tasks:
            return _plan(
                title or _DEFAULT_TITLE, _EMPTY_SUMMARY, [], [], analysis
            )

        logger.info(
            "implementation_plan_started requirements=%d tasks=%d",
            len(analysis.requirements),
            len(analysis.tasks),
        )
        prompt = build_implementation_plan_prompt(analysis)
        try:
            raw = self._llm.generate(prompt, schema=PLAN_SCHEMA, on_tokens=progress.tokens)
        except LLMProviderError:
            logger.exception("implementation_plan_llm_failed")
            raise

        try:
            extracted = ExtractedImplementationPlan.model_validate(parse_json_object(raw))
        except (ValueError, ValidationError) as exc:
            logger.warning("implementation_plan_validation_failed error=%s", exc)
            raise PlanValidationError(
                "The language model returned invalid implementation plan output.",
                detail=str(exc),
            ) from exc

        plan = _to_domain(extracted, analysis=analysis, title=title)
        logger.info(
            "implementation_plan_completed steps=%d acceptance_criteria=%d",
            len(plan.steps),
            len(plan.acceptance_criteria),
        )
        return plan


def _to_domain(
    extracted: ExtractedImplementationPlan,
    *,
    analysis: MeetingAnalysis,
    title: str | None,
) -> ImplementationPlan:
    requirements = {item.id: item for item in analysis.requirements}
    tasks = {item.id: item for item in analysis.tasks}

    drafts: list[tuple[str, str, list[str], list[str]]] = []
    covered_tasks: set[str] = set()
    for item in extracted.steps:
        draft = _ground_step(item, requirements, tasks)
        if draft is None:
            continue
        drafts.append(draft)
        covered_tasks.update(draft[3])

    for task in analysis.tasks:
        if task.id not in covered_tasks:
            logger.info("implementation_plan_added_uncovered_task id=%s", task.id)
            drafts.append(_task_step(task))

    steps = []
    for index, (step_title, description, req_ids, task_ids) in enumerate(drafts, start=1):
        steps.append(
            ImplementationPlanStep(
                id=format_item_id(STEP_PREFIX, index),
                title=step_title,
                description=description,
                related_requirement_ids=req_ids,
                related_task_ids=task_ids,
                evidence=_evidence(req_ids, task_ids, requirements, tasks),
            )
        )

    criteria = [c.strip() for c in extracted.acceptance_criteria if c.strip()]
    if not criteria:
        criteria = [c for task in analysis.tasks for c in task.acceptance_criteria]
    summary = extracted.summary.strip() or (
        f"{len(steps)} implementation steps covering {len(requirements)} requirements "
        f"and {len(tasks)} tasks."
    )
    plan_title = (title or extracted.title or _DEFAULT_TITLE).strip() or _DEFAULT_TITLE
    return _plan(plan_title, summary, steps, criteria[:_MAX_CRITERIA], analysis)


def _plan(
    title: str,
    summary: str,
    steps: list[ImplementationPlanStep],
    criteria: list[str],
    analysis: MeetingAnalysis,
) -> ImplementationPlan:
    return ImplementationPlan(
        id=format_item_id(PLAN_PREFIX, 1),
        title=title,
        summary=summary,
        steps=steps,
        acceptance_criteria=criteria,
        risks=list(analysis.risks),
        open_questions=list(analysis.open_questions),
    )


def _ground_step(
    item: ExtractedPlanStep,
    requirements: dict[str, Requirement],
    tasks: dict[str, Task],
) -> tuple[str, str, list[str], list[str]] | None:
    req_ids = _keep_known(item.requirement_ids, requirements, kind="requirement")
    task_ids = _keep_known(item.task_ids, tasks, kind="task")
    if not req_ids and not task_ids:
        logger.warning("implementation_plan_dropped_step_without_references")
        return None
    description = item.description.strip() or item.title
    return item.title, description, req_ids, task_ids


def _task_step(task: Task) -> tuple[str, str, list[str], list[str]]:
    return task.title, task.description, list(task.related_requirement_ids), [task.id]


def _keep_known(
    candidates: list[str], allowed: dict[str, Requirement] | dict[str, Task], *, kind: str
) -> list[str]:
    kept: list[str] = []
    for item_id in candidates:
        if item_id in kept:
            continue
        if item_id in allowed:
            kept.append(item_id)
        else:
            logger.warning(
                "implementation_plan_dropped_invalid_reference kind=%s id=%s", kind, item_id
            )
    return kept


def _evidence(
    req_ids: list[str],
    task_ids: list[str],
    requirements: dict[str, Requirement],
    tasks: dict[str, Task],
) -> list[SourceReference]:
    refs: list[SourceReference] = []
    for req_id in req_ids:
        refs.append(requirements[req_id].source_reference)
    for task_id in task_ids:
        refs.extend(tasks[task_id].source_references)
    unique: list[SourceReference] = []
    for ref in refs:
        if ref not in unique:
            unique.append(ref)
    return unique[:_MAX_EVIDENCE_PER_STEP]
