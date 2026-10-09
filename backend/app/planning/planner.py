import logging
import re
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
_MAX_WHEN_CHARS = 48
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
# An item cited by several steps stays only where it matches at least this
# share of its best-matching step: REQ "threat model" belongs to the
# threat-model step, not to every step that happens to say "event".
_LINK_OWNER_SHARE = 0.5
# A forgotten task this close to an existing step belongs to that step.
_TASK_STEP_MATCH = 0.6
# A step that cites no task of its own is usually the task the model forgot.
_TASKLESS_STEP_MATCH = 0.5
# A requirement no step cites goes to the step whose words it shares, but only
# when that step clearly wins; otherwise it is reported as not linked.
_PLACE_MIN_WORDS = 2
_PLACE_MARGIN = 2


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
    step's "when" may not contain a number or date the record lacks, or it is
    dropped. The plan's "done when" is its tasks' suggested criteria.
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
    _keep_links_where_they_belong(drafts, decisions, requirements, tasks)

    for task in analysis.tasks:
        if task.id in covered_tasks:
            continue
        # The model often writes a step for a task but forgets its ID; attach
        # the task there instead of adding the same step twice.
        match = _matching_step(task, drafts)
        if match is not None:
            logger.info("implementation_plan_attached_uncovered_task id=%s step=%s", task.id, match.title)
            match.task_ids.append(task.id)
            if match.when is None and task.due:
                match.when = task.due
        else:
            logger.info("implementation_plan_added_uncovered_task id=%s", task.id)
            drafts.append(_task_step(task))
    _place_unlinked_requirements(drafts, decisions, requirements, tasks)

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

    # "Done when" is the finished work, from each task's suggested criteria;
    # decisions are constraints on the plan, not results of it.
    criteria = _criteria_from_tasks(drafts, tasks)
    summary = _grounded_summary(extracted.summary, f"{record_text} {_evidence_text(analysis)}") or (
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


def _step_words(draft: _StepDraft, tasks: dict[str, Task]) -> set[str]:
    """Words of the step's title and its tasks (description only if it has none)."""
    if draft.task_ids:
        text = " ".join([draft.title] + [f"{tasks[t].title} {tasks[t].description}" for t in draft.task_ids])
    else:
        text = f"{draft.title} {draft.description}"
    return word_set(text)


def _keep_links_where_they_belong(
    drafts: list[_StepDraft],
    decisions: dict[str, Decision],
    requirements: dict[str, Requirement],
    tasks: dict[str, Task],
) -> None:
    texts = {**{k: v.statement for k, v in decisions.items()},
             **{k: v.statement for k, v in requirements.items()}}
    words = {draft_index: _step_words(d, tasks) for draft_index, d in enumerate(drafts)}
    citing: dict[str, list[int]] = {}
    for i, d in enumerate(drafts):
        for item_id in d.decision_ids + d.requirement_ids:
            citing.setdefault(item_id, []).append(i)

    for item_id, steps in citing.items():
        if len(steps) < 2:
            continue
        item_words = word_set(texts[item_id])
        scores = {i: len(words[i] & item_words) for i in steps}
        best = max(scores.values())
        if best < 2:
            continue  # no step clearly owns it
        for i in steps:
            d = drafts[i]
            refs = len(d.decision_ids) + len(d.requirement_ids) + len(d.task_ids)
            if scores[i] < best * _LINK_OWNER_SHARE and refs > 1:
                ids = d.decision_ids if item_id in d.decision_ids else d.requirement_ids
                ids.remove(item_id)
                logger.info(
                    "implementation_plan_dropped_weaker_link id=%s step=%s", item_id, d.title
                )


def _matching_step(task: Task, drafts: list[_StepDraft]) -> _StepDraft | None:
    """The existing step that is clearly this task, if any (best match wins)."""
    best: tuple[float, _StepDraft] | None = None
    for draft in drafts:
        score = max(
            coverage(task.title, draft.title),
            coverage(draft.title, task.title),
            coverage(task.title, f"{draft.title} {draft.description}"),
        )
        needed = _TASKLESS_STEP_MATCH if not draft.task_ids else _TASK_STEP_MATCH
        if score >= needed and (best is None or score > best[0]):
            best = (score, draft)
    return best[1] if best else None


def _common_words(
    decisions: dict[str, Decision],
    requirements: dict[str, Requirement],
    tasks: dict[str, Task],
) -> set[str]:
    """Words so frequent in this meeting ("kafka", "payment") they link nothing."""
    item_words = [word_set(d.statement) for d in decisions.values()]
    item_words += [word_set(r.statement) for r in requirements.values()]
    item_words += [word_set(f"{t.title} {t.description}") for t in tasks.values()]
    counts: dict[str, int] = {}
    for words in item_words:
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    limit = max(2, int(len(item_words) * _COMMON_WORD_SHARE))
    return {word for word, count in counts.items() if count > limit}


def _place_unlinked_requirements(
    drafts: list[_StepDraft],
    decisions: dict[str, Decision],
    requirements: dict[str, Requirement],
    tasks: dict[str, Task],
) -> None:
    """Give a requirement no step cites to the step it clearly belongs to.

    First the step that applies its decision ("payment stays synchronous"
    from DEC-012 goes where DEC-012 is); else the step that clearly shares its
    words. Anything left stays unlinked and the report says so.
    """
    cited = {r for d in drafts for r in d.requirement_ids}
    common = _common_words(decisions, requirements, tasks)
    words = [_step_words(d, tasks) for d in drafts]
    for req_id, req in requirements.items():
        if req_id in cited:
            continue
        by_decision = {
            i for i, d in enumerate(drafts) for dec_id in req.related_decision_ids if dec_id in d.decision_ids
        }
        target: int | None = None
        if len(by_decision) == 1:
            target = by_decision.pop()
        else:
            req_words = word_set(req.statement) - common
            scores = sorted(((len(req_words & w), i) for i, w in enumerate(words)), reverse=True)
            if scores:
                best, index = scores[0]
                runner_up = scores[1][0] if len(scores) > 1 else 0
                if best >= _PLACE_MIN_WORDS and best - runner_up >= _PLACE_MARGIN:
                    target = index
        if target is not None:
            drafts[target].requirement_ids.append(req_id)
            drafts[target].requirement_ids.sort()
            logger.info("implementation_plan_placed_requirement id=%s step=%s", req_id, drafts[target].title)


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
    common = _common_words(decisions, requirements, tasks)

    for draft in drafts:
        # Judge by the step's title and its tasks (grounded in the transcript),
        # not its description: the model writes that, and tends to justify its
        # own links in it ("align on deadlines and migration constraints").
        step_words = _step_words(draft, tasks)
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


# Plain words a summary may use without the meeting saying them.
_SUMMARY_FILLER = frozenset(
    """plan plans ensure ensures ensuring implement implements implementing introduce
    introduces introducing align aligns aligning include includes including key
    constraint constraints per handling prioritize prioritizes prioritizing secure
    observable launch launches maintain maintains maintaining deliver delivers
    delivering cover covers covering support supports supporting while using within
    migrate migrates migrating post launche evaluation evaluate""".split()
)


def _evidence_text(analysis: MeetingAnalysis) -> str:
    """What the meeting itself said, as quoted in the record's evidence."""
    items = [*analysis.decisions, *analysis.requirements, *analysis.risks, *analysis.open_questions]
    quotes = [item.source_reference.excerpt for item in items]
    quotes += [ref.excerpt for task in analysis.tasks for ref in task.source_references]
    return " ".join(quotes)


def _grounded_summary(summary: str, record_text: str) -> str:
    """The model's summary without sentences that bring in new terms.

    "Kafka-based event sourcing" when the meeting never said "event sourcing"
    names an architecture nobody chose; "compliance requirements" when nobody
    raised compliance invents a concern.
    """
    known = word_set(record_text) | _SUMMARY_FILLER
    for sentence in re.split(r"(?<=[.!?])\s+", summary.strip()):
        novel = word_set(sentence) - known
        if novel:
            # What is left after cutting a sentence out ("It ensures ...")
            # rarely reads as a summary; use the plain one instead.
            logger.info("implementation_plan_summary_dropped new_terms=%s", ",".join(sorted(novel)))
            return ""
    return summary.strip()


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
