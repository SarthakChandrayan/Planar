import logging
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.analysis.grounding import shared_words, similarity
from app.analysis.parsing import parse_json_object
from app.domain import (
    DEC_PREFIX,
    PLAN_PREFIX,
    REQ_PREFIX,
    STEP_PREFIX,
    TSK_PREFIX,
    Decision,
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
_MAX_CRITERIA = 20
_DUPLICATE_CRITERION_SIMILARITY = 0.6
# An ID cited on at least this many steps, and on more than this share of
# them, is a blanket citation: kept only where the step shares its wording.
_BLANKET_MIN_STEPS = 3
_BLANKET_SHARE = 0.6
_BLANKET_MIN_SHARED_WORDS = 2


@dataclass
class _StepDraft:
    title: str
    description: str
    decision_ids: list[str] = field(default_factory=list)
    requirement_ids: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)


class ImplementationPlanner:
    """Turn a validated MeetingAnalysis into an ImplementationPlan via LLMProvider.

    The model orders and groups work and cites record IDs (the decisions a
    step applies, the requirements and tasks it delivers). Evidence comes
    from the cited items, so a plan step is always traceable to transcript
    lines. Tasks the model leaves out are appended as their own steps.

    The plan's "done when" list is not written by the model: it is the tasks'
    own criteria, which come from the action items. Free-written plan targets
    were the one unchecked output, and small models invented numbers there.
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
    decisions = {item.id: item for item in analysis.decisions}
    requirements = {item.id: item for item in analysis.requirements}
    tasks = {item.id: item for item in analysis.tasks}

    drafts: list[_StepDraft] = []
    covered_tasks: set[str] = set()
    for item in extracted.steps:
        draft = _ground_step(item, decisions, requirements, tasks)
        if draft is None:
            continue
        drafts.append(draft)
        covered_tasks.update(draft.task_ids)
    _trim_blanket_citations(drafts, decisions, requirements, tasks)

    for task in analysis.tasks:
        if task.id not in covered_tasks:
            logger.info("implementation_plan_added_uncovered_task id=%s", task.id)
            drafts.append(_task_step(task))

    steps = [
        ImplementationPlanStep(
            id=format_item_id(STEP_PREFIX, index),
            title=draft.title,
            description=draft.description,
            related_decision_ids=draft.decision_ids,
            related_requirement_ids=draft.requirement_ids,
            related_task_ids=draft.task_ids,
            evidence=_evidence(draft, decisions, requirements, tasks),
        )
        for index, draft in enumerate(drafts, start=1)
    ]

    criteria = _criteria_from_tasks(drafts, tasks)
    summary = extracted.summary.strip() or (
        f"{len(steps)} implementation steps covering {len(requirements)} requirements "
        f"and {len(tasks)} tasks."
    )
    plan_title = (title or extracted.title or _DEFAULT_TITLE).strip() or _DEFAULT_TITLE
    return _plan(plan_title, summary, steps, criteria[:_MAX_CRITERIA], analysis)


def _criteria_from_tasks(drafts: list[_StepDraft], tasks: dict[str, Task]) -> list[str]:
    """The plan's checklist: each task's own criteria, in plan order, de-duplicated."""
    ordered: list[str] = []
    for draft in drafts:
        for task_id in draft.task_ids:
            if task_id not in ordered:
                ordered.append(task_id)
    for task_id in tasks:
        if task_id not in ordered:
            ordered.append(task_id)
    criteria: list[str] = []
    for task_id in ordered:
        for criterion in tasks[task_id].acceptance_criteria:
            text = criterion.strip()
            if text and not any(
                similarity(text, kept) >= _DUPLICATE_CRITERION_SIMILARITY for kept in criteria
            ):
                criteria.append(text)
    return criteria


def _trim_blanket_citations(
    drafts: list[_StepDraft],
    decisions: dict[str, Decision],
    requirements: dict[str, Requirement],
    tasks: dict[str, Task],
) -> None:
    """Drop an ID the model attached to most steps where the step has nothing to do with it.

    With one requirement in the record, a small model cites it on every step.
    """
    if len(drafts) < _BLANKET_MIN_STEPS:
        return
    texts = {**{k: v.statement for k, v in decisions.items()},
             **{k: v.statement for k, v in requirements.items()}}
    counts: dict[str, int] = {}
    for draft in drafts:
        for item_id in draft.decision_ids + draft.requirement_ids:
            counts[item_id] = counts.get(item_id, 0) + 1
    blanket = {
        item_id
        for item_id, count in counts.items()
        if count >= _BLANKET_MIN_STEPS and count / len(drafts) > _BLANKET_SHARE
    }
    for item_id in blanket:
        for draft in drafts:
            ids = draft.decision_ids if item_id in draft.decision_ids else draft.requirement_ids
            if item_id not in ids:
                continue
            step_text = " ".join(
                [draft.title, draft.description]
                + [f"{tasks[t].title} {tasks[t].description}" for t in draft.task_ids]
            )
            shared, _ = shared_words(step_text, texts[item_id])
            if shared >= _BLANKET_MIN_SHARED_WORDS:
                continue
            remaining = len(draft.decision_ids) + len(draft.requirement_ids) + len(draft.task_ids)
            if remaining <= 1:
                continue  # its only reference: keep rather than lose the step
            ids.remove(item_id)
            logger.info(
                "implementation_plan_dropped_blanket_citation id=%s step=%s", item_id, draft.title
            )


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
    decisions: dict[str, Decision],
    requirements: dict[str, Requirement],
    tasks: dict[str, Task],
) -> _StepDraft | None:
    # Sort every cited ID by its prefix: a small model sometimes puts a
    # DEC- or TSK- ID in the wrong list, and the ID is still meaningful.
    cited = item.decision_ids + item.requirement_ids + item.task_ids
    by_prefix: dict[str, list[str]] = {DEC_PREFIX: [], REQ_PREFIX: [], TSK_PREFIX: []}
    for item_id in cited:
        prefix = item_id.split("-", 1)[0]
        if prefix in by_prefix:
            by_prefix[prefix].append(item_id)
        else:
            logger.warning("implementation_plan_dropped_invalid_reference id=%s", item_id)
    draft = _StepDraft(
        title=item.title,
        description=item.description.strip() or item.title,
        decision_ids=_keep_known(by_prefix[DEC_PREFIX], decisions, kind="decision"),
        requirement_ids=_keep_known(by_prefix[REQ_PREFIX], requirements, kind="requirement"),
        task_ids=_keep_known(by_prefix[TSK_PREFIX], tasks, kind="task"),
    )
    if not (draft.decision_ids or draft.requirement_ids or draft.task_ids):
        logger.warning("implementation_plan_dropped_step_without_references")
        return None
    return draft


def _task_step(task: Task) -> _StepDraft:
    return _StepDraft(
        title=task.title,
        description=task.description,
        requirement_ids=list(task.related_requirement_ids),
        task_ids=[task.id],
    )


def _keep_known(
    candidates: list[str],
    allowed: dict[str, Decision] | dict[str, Requirement] | dict[str, Task],
    *,
    kind: str,
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
    draft: _StepDraft,
    decisions: dict[str, Decision],
    requirements: dict[str, Requirement],
    tasks: dict[str, Task],
) -> list[SourceReference]:
    """Transcript evidence for a step: what its tasks, requirements and decisions cite."""
    refs: list[SourceReference] = []
    for task_id in draft.task_ids:
        refs.extend(tasks[task_id].source_references)
    for req_id in draft.requirement_ids:
        refs.append(requirements[req_id].source_reference)
    for dec_id in draft.decision_ids:
        refs.append(decisions[dec_id].source_reference)
    unique: list[SourceReference] = []
    for ref in refs:
        if ref not in unique:
            unique.append(ref)
    return unique[:_MAX_EVIDENCE_PER_STEP]
