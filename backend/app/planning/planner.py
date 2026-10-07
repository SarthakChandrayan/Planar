import logging
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.analysis.grounding import adds_facts, coverage, shared_words, similarity, word_set
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
    ExtractedOutcome,
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
_MAX_OUTCOMES = 8
_MAX_WHEN_CHARS = 48
# An outcome may rephrase the items it cites, but must stay about them.
_OUTCOME_MIN_COVERAGE = 0.4
_EMPTY_WHEN = frozenset({"", "n/a", "na", "none", "tbd", "unknown", "-", "not specified"})
_DUPLICATE_CRITERION_SIMILARITY = 0.6
# An ID cited on at least this many steps, and on more than this share of
# them, is a blanket citation: kept only where the step shares its wording.
_BLANKET_MIN_STEPS = 3
_BLANKET_SHARE = 0.6
_BLANKET_MIN_SHARED_WORDS = 2
# A word in more than this share of the record's items says nothing about a
# particular link ("transaction" in a transactions meeting).
_COMMON_WORD_SHARE = 0.3


@dataclass
class _StepDraft:
    title: str
    description: str
    decision_ids: list[str] = field(default_factory=list)
    requirement_ids: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    when: str | None = None


class ImplementationPlanner:
    """Turn a validated MeetingAnalysis into an ImplementationPlan via LLMProvider.

    The model orders and groups work and cites record IDs (the decisions a
    step applies, the requirements and tasks it delivers). Evidence comes
    from the cited items, so a plan step is always traceable to transcript
    lines. Tasks the model leaves out are appended as their own steps.

    Model-written text that states facts is checked against the record: a
    step's "when" and the plan's outcomes may not contain a number or date the
    record lacks. A failing outcome falls back to the cited decision's own
    words; a failing "when" is dropped.
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

    record_text = _record_text(analysis)
    drafts: list[_StepDraft] = []
    covered_tasks: set[str] = set()
    for item in extracted.steps:
        draft = _ground_step(item, decisions, requirements, tasks, record_text)
        if draft is None:
            continue
        drafts.append(draft)
        covered_tasks.update(draft.task_ids)
    _trim_blanket_citations(drafts, decisions, requirements, tasks)
    _trim_unrelated_links(drafts, decisions, requirements, tasks)

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
            when=draft.when,
        )
        for index, draft in enumerate(drafts, start=1)
    ]

    criteria = _outcomes(extracted.outcomes, drafts, decisions, requirements)
    if not criteria:
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


def _trim_unrelated_links(
    drafts: list[_StepDraft],
    decisions: dict[str, Decision],
    requirements: dict[str, Requirement],
    tasks: dict[str, Task],
) -> None:
    """Drop decision/requirement links that have nothing to do with the step.

    Small models hand IDs out almost in order ("Optimize indexing" citing
    "reject CREATED -> COMPLETED"). A link stays if the step shares a
    distinctive word with the item (or two of any kind), or if the step's own
    tasks or requirements already link to it.
    """
    texts = {**{k: v.statement for k, v in decisions.items()},
             **{k: v.statement for k, v in requirements.items()}}
    item_words = [word_set(t) for t in texts.values()]
    item_words += [word_set(f"{t.title} {t.description}") for t in tasks.values()]
    counts: dict[str, int] = {}
    for words in item_words:
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    limit = max(2, int(len(item_words) * _COMMON_WORD_SHARE))
    common = {word for word, count in counts.items() if count > limit}

    for draft in drafts:
        # Judge by the step's title and its tasks (grounded in the transcript),
        # not its description: the model writes that, and tends to justify its
        # own links in it ("align on deadlines and migration constraints").
        if draft.task_ids:
            step_text = " ".join(
                [draft.title] + [f"{tasks[t].title} {tasks[t].description}" for t in draft.task_ids]
            )
        else:
            step_text = f"{draft.title} {draft.description}"
        step_words = word_set(step_text)
        backed_reqs = {r for t in draft.task_ids for r in tasks[t].related_requirement_ids}

        def related(item_id: str) -> bool:
            shared = step_words & word_set(texts[item_id])
            return bool(shared - common) or len(shared) >= 2

        kept_reqs = [r for r in draft.requirement_ids if r in backed_reqs or related(r)]
        backed_decs = {d for r in kept_reqs for d in requirements[r].related_decision_ids}
        kept_decs = [d for d in draft.decision_ids if d in backed_decs or related(d)]

        if not (kept_reqs or kept_decs or draft.task_ids):
            continue  # all it has: keep rather than lose the step
        for item_id in set(draft.requirement_ids) - set(kept_reqs):
            logger.info("implementation_plan_dropped_unrelated_link id=%s step=%s", item_id, draft.title)
        for item_id in set(draft.decision_ids) - set(kept_decs):
            logger.info("implementation_plan_dropped_unrelated_link id=%s step=%s", item_id, draft.title)
        draft.requirement_ids = kept_reqs
        draft.decision_ids = kept_decs


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
    record_text: str,
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
        when=_grounded_when(item.when, record_text),
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
        when=task.due,
    )


def _record_text(analysis: MeetingAnalysis) -> str:
    """Everything the record states, for checking model-written facts."""
    parts: list[str] = []
    parts += [d.statement for d in analysis.decisions]
    parts += [r.statement for r in analysis.requirements]
    for t in analysis.tasks:
        parts += [t.title, t.description, t.due or "", *t.acceptance_criteria]
    parts += [r.description for r in analysis.risks]
    parts += [f"{q.question} {q.context}" for q in analysis.open_questions]
    return " ".join(parts)


def _grounded_when(raw: str, record_text: str) -> str | None:
    when = " ".join(raw.split()).strip(" .")
    if when.lower() in _EMPTY_WHEN or len(when) > _MAX_WHEN_CHARS:
        return None
    invented = adds_facts(when, record_text)
    if invented:
        logger.info("implementation_plan_dropped_when when=%s invented=%s", when, sorted(invented))
        return None
    return when


def _outcomes(
    extracted: list[ExtractedOutcome],
    drafts: list[_StepDraft],
    decisions: dict[str, Decision],
    requirements: dict[str, Requirement],
) -> list[str]:
    """Plan-level "done when": checked outcomes, else the decisions the plan applies."""
    statements = {**{k: v.statement for k, v in decisions.items()},
                  **{k: v.statement for k, v in requirements.items()}}
    outcomes: list[str] = []

    def add(text: str) -> None:
        if text and not any(similarity(text, kept) >= 0.6 for kept in outcomes):
            outcomes.append(text)

    for item in extracted:
        cited = [statements[i] for i in item.ids if i in statements]
        if not cited:
            continue
        source = " ".join(cited)
        text = item.text.strip()
        if text and not adds_facts(text, source) and coverage(text, source) >= _OUTCOME_MIN_COVERAGE:
            add(text)
        else:
            logger.info("implementation_plan_outcome_replaced text=%s", text)
            add(cited[0])
    if outcomes:
        return outcomes[:_MAX_OUTCOMES]

    # The model gave none: the decisions the plan applies, in plan order.
    for draft in drafts:
        for item_id in draft.decision_ids:
            add(statements[item_id])
    return outcomes[:_MAX_OUTCOMES]


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
