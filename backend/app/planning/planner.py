import logging

from pydantic import ValidationError

from app.analysis.excerpts import excerpt_supported_by_transcript
from app.domain import (
    PLAN_PREFIX,
    STEP_PREFIX,
    ImplementationPlan,
    ImplementationPlanStep,
    MeetingAnalysis,
    SourceReference,
    format_item_id,
)
from app.llm import LLMProvider, LLMProviderError
from app.planning.errors import PlanValidationError
from app.planning.parsing import normalize_extracted_plan, parse_plan_json_object
from app.planning.prompts import build_implementation_plan_prompt
from app.planning.schemas import ExtractedImplementationPlan, ExtractedPlanStep

logger = logging.getLogger(__name__)

_LLM_PREVIEW_CHARS = 500
_DEFAULT_TITLE = "Implementation plan"


class ImplementationPlanner:
    """Turn a validated MeetingAnalysis into an ImplementationPlan via LLMProvider."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def plan(
        self,
        analysis: MeetingAnalysis,
        *,
        title: str | None = None,
    ) -> ImplementationPlan:
        logger.info(
            "implementation_plan_started decisions=%d requirements=%d "
            "tasks=%d risks=%d open_questions=%d",
            len(analysis.decisions),
            len(analysis.requirements),
            len(analysis.tasks),
            len(analysis.risks),
            len(analysis.open_questions),
        )
        prompt = build_implementation_plan_prompt(analysis)
        try:
            raw = self._llm.generate(prompt)
        except LLMProviderError:
            logger.exception("implementation_plan_llm_failed")
            raise

        plan = self._parse_and_validate(raw, analysis=analysis, title=title)
        logger.info(
            "implementation_plan_completed steps=%d acceptance_criteria=%d",
            len(plan.steps),
            len(plan.acceptance_criteria),
        )
        return plan

    def _parse_and_validate(
        self,
        raw: str,
        *,
        analysis: MeetingAnalysis,
        title: str | None,
    ) -> ImplementationPlan:
        try:
            payload = parse_plan_json_object(raw)
            payload = normalize_extracted_plan(payload)
            if title and not str(payload.get("title") or "").strip():
                payload["title"] = title
            extracted = ExtractedImplementationPlan.model_validate(payload)
            return _to_domain(extracted, analysis=analysis, title=title)
        except PlanValidationError:
            raise
        except (ValueError, ValidationError) as exc:
            logger.warning(
                "implementation_plan_validation_failed error=%s llm_preview=%s",
                exc,
                _preview(raw, _LLM_PREVIEW_CHARS),
            )
            raise PlanValidationError(
                "The language model returned invalid implementation plan output.",
                detail=str(exc),
            ) from exc


def _to_domain(
    extracted: ExtractedImplementationPlan,
    *,
    analysis: MeetingAnalysis,
    title: str | None,
) -> ImplementationPlan:
    requirement_ids = {item.id for item in analysis.requirements}
    task_ids = {item.id for item in analysis.tasks}
    allowed_excerpts = _record_excerpts(analysis)

    steps: list[ImplementationPlanStep] = []
    for item in extracted.steps:
        step = _ground_step(
            item,
            requirement_ids=requirement_ids,
            task_ids=task_ids,
            allowed_excerpts=allowed_excerpts,
        )
        if step is None:
            continue
        steps.append(
            ImplementationPlanStep(
                id=format_item_id(STEP_PREFIX, len(steps) + 1),
                title=step["title"],
                description=step["description"],
                related_requirement_ids=step["related_requirement_ids"],
                related_task_ids=step["related_task_ids"],
                evidence=step["evidence"],
            )
        )

    criteria = [item.strip() for item in extracted.acceptance_criteria if item.strip()]
    if not criteria:
        criteria = [
            criterion
            for task in analysis.tasks
            for criterion in task.acceptance_criteria
        ]

    plan_title = (title or extracted.title or _DEFAULT_TITLE).strip() or _DEFAULT_TITLE
    return ImplementationPlan(
        id=format_item_id(PLAN_PREFIX, 1),
        title=plan_title,
        summary=extracted.summary,
        steps=steps,
        acceptance_criteria=criteria,
        risks=list(analysis.risks),
        open_questions=list(analysis.open_questions),
    )


def _ground_step(
    item: ExtractedPlanStep,
    *,
    requirement_ids: set[str],
    task_ids: set[str],
    allowed_excerpts: list[str],
) -> dict[str, object] | None:
    kept_requirements = _keep_known_ids(
        item.related_requirement_ids,
        requirement_ids,
        kind="requirement",
    )
    kept_tasks = _keep_known_ids(item.related_task_ids, task_ids, kind="task")
    evidence: list[SourceReference] = []
    for ref in item.evidence:
        if _excerpt_from_record(ref.excerpt, allowed_excerpts):
            evidence.append(SourceReference(excerpt=ref.excerpt))
        else:
            logger.warning(
                "implementation_plan_dropped_fabricated_evidence",
            )

    if not evidence:
        logger.warning("implementation_plan_dropped_step_without_evidence")
        return None

    return {
        "title": item.title,
        "description": item.description,
        "related_requirement_ids": kept_requirements,
        "related_task_ids": kept_tasks,
        "evidence": evidence,
    }


def _keep_known_ids(
    candidates: list[str],
    allowed: set[str],
    *,
    kind: str,
) -> list[str]:
    kept: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        item_id = raw.strip()
        if not item_id or item_id in seen:
            continue
        if item_id in allowed:
            kept.append(item_id)
            seen.add(item_id)
            continue
        logger.warning(
            "implementation_plan_dropped_invalid_reference kind=%s id=%s",
            kind,
            item_id,
        )
    return kept


def _record_excerpts(analysis: MeetingAnalysis) -> list[str]:
    excerpts: list[str] = []
    for item in analysis.decisions:
        excerpts.append(item.source_reference.excerpt)
    for item in analysis.requirements:
        excerpts.append(item.source_reference.excerpt)
    for item in analysis.tasks:
        excerpts.extend(ref.excerpt for ref in item.source_references)
    for item in analysis.risks:
        excerpts.append(item.source_reference.excerpt)
    for item in analysis.open_questions:
        excerpts.append(item.source_reference.excerpt)
    return excerpts


def _excerpt_from_record(excerpt: str, allowed: list[str]) -> bool:
    return any(
        excerpt_supported_by_transcript(excerpt, source) for source in allowed
    )


def _preview(value: str, limit: int) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."
