"""Multi-pass, line-cited meeting analysis.

For each transcript chunk the model runs four focused passes:

    decisions -> requirements -> tasks -> risks & open questions

Each pass is a small job a small local model can do well. Output is
constrained to a JSON schema, items cite transcript line numbers, and the
backend looks up the evidence and checks that it supports the claim.

Links between items (requirement -> decision, task -> requirement, ...) are
inferred here from shared transcript lines and distinctive wording, not
asked of the model: shown a list of earlier items, a small model copies it.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.analysis import prompts
from app.analysis.errors import (
    AnalysisValidationError,
    EmptyTranscriptError,
    TranscriptTooLongError,
)
from app.analysis.grounding import (
    Grounder,
    Grounding,
    coverage,
    is_hedged,
    shared_words,
    similarity,
    text_mentioned,
)
from app.analysis.parsing import parse_json_object
from app.analysis.schemas import (
    DECISIONS_SCHEMA,
    REQUIREMENTS_SCHEMA,
    RISKS_QUESTIONS_SCHEMA,
    TASKS_SCHEMA,
    DecisionsPass,
    ExtractedDecision,
    ExtractedOpenQuestion,
    ExtractedRequirement,
    ExtractedRisk,
    ExtractedTask,
    ExtractionModel,
    RequirementsPass,
    RisksQuestionsPass,
    TasksPass,
)
from app.analysis.transcript import NumberedTranscript, TranscriptChunk
from app.domain import (
    DEC_PREFIX,
    OQ_PREFIX,
    REQ_PREFIX,
    RSK_PREFIX,
    TSK_PREFIX,
    Decision,
    MeetingAnalysis,
    OpenQuestion,
    Requirement,
    Risk,
    SourceReference,
    Task,
    format_item_id,
)
from app.llm import LLMOutputTruncatedError, LLMProvider, LLMProviderError
from app.progress import NullProgress, Progress

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_MAX_TOKENS = 8000
_DUPLICATE_SIMILARITY = 0.6
_DUPLICATE_SIMILARITY_SAME_LINES = 0.35
# A requirement this close to a decision is the decision restated.
_RESTATED_DECISION_SIMILARITY = 0.75
# A requirement whose evidence is only decision lines, and whose wording is
# mostly those decisions' wording, restates them and adds nothing.
_RESTATED_DECISIONS_COVERAGE = 0.5
# Inferred links: wording overlap needed, lower when evidence lines are shared.
_LINK_SIMILARITY = 0.3
_LINK_SIMILARITY_SAME_LINES = 0.12
# Or: at least this many distinctive words shared, covering this much of the shorter text.
_LINK_MIN_SHARED_WORDS = 2
_LINK_MIN_OVERLAP = 0.5
_MAX_LINKS = 2
_MAX_ACCEPTANCE_CRITERIA = 4
_GENERIC_OWNERS = frozenset(
    {"", "none", "n/a", "na", "tbd", "unknown", "unassigned", "team", "the team",
     "everyone", "all", "we", "us", "someone", "nobody", "anyone", "group",
     "the group"}
)
_GENERIC_DUE = frozenset(
    {"", "none", "n/a", "na", "tbd", "unknown", "not specified", "unspecified",
     "no deadline", "not mentioned", "asap"}
)
_RETRY_INVALID = (
    "NOTE: your previous answer did not match the required JSON shape. "
    "Follow the shape exactly."
)
_RETRY_TOO_LONG = (
    "NOTE: your previous answer was too long. List at most 8 items and keep "
    "each one short."
)


@dataclass(frozen=True)
class _Pass:
    key: str
    label: str
    task: str
    schema: dict[str, Any]
    model: type[ExtractionModel]


PASSES: tuple[_Pass, ...] = (
    _Pass("decisions", "Decisions", prompts.DECISIONS_TASK, DECISIONS_SCHEMA, DecisionsPass),
    _Pass(
        "requirements",
        "Requirements",
        prompts.REQUIREMENTS_TASK,
        REQUIREMENTS_SCHEMA,
        RequirementsPass,
    ),
    _Pass("tasks", "Tasks", prompts.TASKS_TASK, TASKS_SCHEMA, TasksPass),
    _Pass(
        "risks",
        "Risks & open questions",
        prompts.RISKS_QUESTIONS_TASK,
        RISKS_QUESTIONS_SCHEMA,
        RisksQuestionsPass,
    ),
)


@dataclass
class AnalysisOutcome:
    analysis: MeetingAnalysis
    warnings: list[str] = field(default_factory=list)
    chunks: int = 1


class MeetingAnalyzer:
    """Turn a meeting transcript into a validated MeetingAnalysis via LLMProvider."""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        chunk_max_tokens: int = DEFAULT_CHUNK_MAX_TOKENS,
        max_transcript_chars: int | None = None,
    ) -> None:
        self._llm = llm
        self._chunk_max_tokens = chunk_max_tokens
        self._max_transcript_chars = max_transcript_chars

    def analyze(self, transcript: str, progress: Progress | None = None) -> MeetingAnalysis:
        return self.run(transcript, progress).analysis

    def stage_count(self, transcript: str) -> int:
        """How many model calls (without retries) ``run`` will make."""
        numbered = NumberedTranscript(transcript.strip())
        return len(numbered.chunks(self._chunk_max_tokens)) * len(PASSES)

    def run(
        self,
        transcript: str,
        progress: Progress | None = None,
        *,
        extra_stages: int = 0,
    ) -> AnalysisOutcome:
        progress = progress or NullProgress()
        cleaned = transcript.strip()
        if not cleaned:
            raise EmptyTranscriptError("transcript must not be empty")
        if self._max_transcript_chars and len(cleaned) > self._max_transcript_chars:
            raise TranscriptTooLongError(
                f"Transcript is {len(cleaned):,} characters; the limit is "
                f"{self._max_transcript_chars:,}."
            )

        numbered = NumberedTranscript(cleaned)
        chunks = numbered.chunks(self._chunk_max_tokens)
        total = len(chunks) * len(PASSES) + extra_stages
        logger.info(
            "meeting_analysis_started transcript_chars=%d est_tokens=%d chunks=%d speakers=%d",
            len(cleaned),
            numbered.estimated_tokens(),
            len(chunks),
            len(numbered.speakers),
        )

        builder = _RecordBuilder(numbered)
        step = 0
        for chunk in chunks:
            for spec in PASSES:
                step += 1
                label = spec.label
                if len(chunks) > 1:
                    label = f"{label} · part {chunk.index + 1}/{len(chunks)}"
                progress.stage(label, step, total)
                result = self._run_pass(spec, chunk, len(chunks), builder, progress, label)
                if result is not None:
                    builder.add(spec.key, result)

        if builder.successful_passes == 0:
            raise AnalysisValidationError(
                "The language model returned invalid analysis output.",
                detail="; ".join(builder.warnings),
            )

        analysis = builder.build()
        logger.info(
            "meeting_analysis_completed decisions=%d requirements=%d tasks=%d "
            "risks=%d open_questions=%d dropped_ungrounded=%d dropped_duplicates=%d",
            len(analysis.decisions),
            len(analysis.requirements),
            len(analysis.tasks),
            len(analysis.risks),
            len(analysis.open_questions),
            builder.dropped_ungrounded,
            builder.dropped_duplicates,
        )
        return AnalysisOutcome(analysis, list(builder.warnings), len(chunks))

    def _run_pass(
        self,
        spec: _Pass,
        chunk: TranscriptChunk,
        total_chunks: int,
        builder: "_RecordBuilder",
        progress: Progress,
        label: str,
    ) -> ExtractionModel | None:
        note: str | None = None
        for attempt in (1, 2):
            prompt = prompts.build_pass_prompt(
                chunk,
                total_chunks,
                spec.task,
                already_found=builder.already_found(spec.key) if chunk.index else (),
                retry_note=note,
            )
            try:
                raw = self._llm.generate(prompt, schema=spec.schema, on_tokens=progress.tokens)
            except LLMOutputTruncatedError:
                logger.warning("analysis_pass_truncated pass=%s attempt=%d", spec.key, attempt)
                note = _RETRY_TOO_LONG
                continue
            except LLMProviderError:
                logger.exception("analysis_pass_llm_failed pass=%s", spec.key)
                raise
            try:
                return spec.model.model_validate(parse_json_object(raw))
            except (ValueError, ValidationError) as exc:
                logger.warning(
                    "analysis_pass_invalid pass=%s attempt=%d error=%s preview=%s",
                    spec.key,
                    attempt,
                    _first_line(str(exc)),
                    _preview(raw),
                )
                note = _RETRY_INVALID
        builder.warn(f"{label}: the model's answer could not be used, so this section may be incomplete.")
        return None


class _RecordBuilder:
    """Accumulates grounded, de-duplicated items across passes and chunks."""

    def __init__(self, transcript: NumberedTranscript) -> None:
        self._transcript = transcript
        self._grounder = Grounder(transcript)
        self.decisions: list[Decision] = []
        self.requirements: list[Requirement] = []
        self.tasks: list[Task] = []
        self.risks: list[Risk] = []
        self.open_questions: list[OpenQuestion] = []
        self._seen: dict[str, list[tuple[str, Grounding]]] = {
            "decision": [],
            "requirement": [],
            "task": [],
            "risk": [],
            "open_question": [],
        }
        self.warnings: list[str] = []
        self.successful_passes = 0
        self.dropped_ungrounded = 0
        self.dropped_duplicates = 0

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    # ------------------------------------------------------------ prompt context

    def already_found(self, key: str) -> list[str]:
        if key == "decisions":
            return [d.statement for d in self.decisions]
        if key == "requirements":
            return [r.statement for r in self.requirements]
        if key == "tasks":
            return [t.title for t in self.tasks]
        return [r.description for r in self.risks] + [q.question for q in self.open_questions]

    # ------------------------------------------------------------------ adding

    def add(self, key: str, result: ExtractionModel) -> None:
        self.successful_passes += 1
        handlers: dict[str, Callable[[Any], None]] = {
            "decisions": lambda r: [self._add_decision(i) for i in r.decisions],
            "requirements": lambda r: [self._add_requirement(i) for i in r.requirements],
            "tasks": lambda r: [self._add_task(i) for i in r.tasks],
            "risks": lambda r: (
                [self._add_risk(i) for i in r.risks],
                [self._add_open_question(i) for i in r.open_questions],
            ),
        }
        handlers[key](result)

    def _accept(
        self,
        kind: str,
        claim: str,
        lines: list[int],
        reject: Callable[[Grounding], bool] | None = None,
    ) -> Grounding | None:
        """Ground a claim, apply ``reject``, then de-duplicate.

        Rejection runs before the item is remembered, so a rejected item can
        never block a later, valid version of the same claim.
        """
        grounding = self._grounder.ground(claim, lines)
        if grounding is None:
            self.dropped_ungrounded += 1
            logger.info("analysis_dropped_ungrounded kind=%s claim=%s", kind, _preview(claim, 120))
            return None
        if reject is not None and reject(grounding):
            return None
        if self._is_duplicate(claim, grounding, self._seen[kind]):
            self.dropped_duplicates += 1
            return None
        self._seen[kind].append((claim, grounding))
        return grounding

    @staticmethod
    def _is_duplicate(
        claim: str, grounding: Grounding, seen: list[tuple[str, Grounding]]
    ) -> bool:
        lines = {line.number for line in grounding.lines}
        for other_claim, other in seen:
            score = similarity(claim, other_claim)
            if score >= _DUPLICATE_SIMILARITY:
                return True
            if score >= _DUPLICATE_SIMILARITY_SAME_LINES and lines & {
                line.number for line in other.lines
            }:
                return True
        return False

    def _add_decision(self, item: ExtractedDecision) -> None:
        grounding = self._accept("decision", item.statement, item.lines)
        if grounding is None:
            return
        self.decisions.append(
            Decision(
                id=format_item_id(DEC_PREFIX, len(self.decisions) + 1),
                statement=item.statement,
                confidence=grounding.confidence,
                source_reference=self._source(grounding, item.statement),
            )
        )

    def _add_requirement(self, item: ExtractedRequirement) -> None:
        if any(
            similarity(item.statement, d.statement) >= _RESTATED_DECISION_SIMILARITY
            for d in self.decisions
        ):
            self.dropped_duplicates += 1
            return
        grounding = self._accept(
            "requirement",
            item.statement,
            item.lines,
            reject=lambda g: self._reject_requirement(item.statement, g),
        )
        if grounding is None:
            return
        self.requirements.append(
            Requirement(
                id=format_item_id(REQ_PREFIX, len(self.requirements) + 1),
                statement=item.statement,
                confidence=grounding.confidence,
                source_reference=self._source(grounding, item.statement),
            )
        )

    def _reject_requirement(self, statement: str, grounding: Grounding) -> bool:
        if self._restates_decisions(statement, grounding):
            self.dropped_duplicates += 1
            logger.info("analysis_dropped_restated_decisions claim=%s", _preview(statement, 120))
            return True
        if _upgrades_hedge(statement, grounding):
            self.dropped_ungrounded += 1
            logger.info("analysis_dropped_hedged_requirement claim=%s", _preview(statement, 120))
            return True
        return False

    def _restates_decisions(self, statement: str, grounding: Grounding) -> bool:
        lines = {line.source_line for line in grounding.lines}
        on_lines = [
            d.statement for d in self.decisions if _ref_lines([d.source_reference]) & lines
        ]
        decision_lines: set[int] = set()
        for d in self.decisions:
            decision_lines |= _ref_lines([d.source_reference])
        if not on_lines or not lines <= decision_lines:
            return False
        return coverage(statement, " ".join(on_lines)) >= _RESTATED_DECISIONS_COVERAGE

    def _add_task(self, item: ExtractedTask) -> None:
        owner = self._owner(item.owner)
        description = item.description.strip() or item.title
        claim = " ".join(part for part in (item.title, description, owner or "") if part)
        grounding = self._accept("task", claim, item.lines)
        if grounding is None:
            return
        criteria = [c.strip() for c in item.acceptance_criteria if c and c.strip()]
        self.tasks.append(
            Task(
                id=format_item_id(TSK_PREFIX, len(self.tasks) + 1),
                title=item.title,
                description=description,
                priority=item.priority,
                owner=owner,
                due=self._due(item.due),
                acceptance_criteria=criteria[:_MAX_ACCEPTANCE_CRITERIA],
                source_references=[self._source(grounding, claim)],
            )
        )

    def _add_risk(self, item: ExtractedRisk) -> None:
        grounding = self._accept("risk", item.description, item.lines)
        if grounding is None:
            return
        self.risks.append(
            Risk(
                id=format_item_id(RSK_PREFIX, len(self.risks) + 1),
                description=item.description,
                severity=item.severity,
                source_reference=self._source(grounding, item.description),
            )
        )

    def _add_open_question(self, item: ExtractedOpenQuestion) -> None:
        claim = f"{item.question} {item.context}".strip()
        grounding = self._accept("open_question", claim, item.lines)
        if grounding is None:
            return
        context = item.context.strip() or grounding.lines[0].content
        self.open_questions.append(
            OpenQuestion(
                id=format_item_id(OQ_PREFIX, len(self.open_questions) + 1),
                question=item.question,
                context=context,
                source_reference=self._source(grounding, claim),
            )
        )

    def _source(self, grounding: Grounding, claim: str) -> SourceReference:
        return _source(grounding, self._grounder, claim)

    def _owner(self, raw: str | None) -> str | None:
        name = (raw or "").strip().strip(".")
        if name.lower() in _GENERIC_OWNERS:
            return None
        for speaker in self._transcript.speakers:
            if speaker.lower() == name.lower():
                return speaker
        return name if text_mentioned(name, self._transcript.text) else None

    def _due(self, raw: str | None) -> str | None:
        due = (raw or "").strip().strip(".")
        if due.lower() in _GENERIC_DUE:
            return None
        return due if text_mentioned(due, self._transcript.text) else None

    # ------------------------------------------------------------------- build

    def build(self) -> MeetingAnalysis:
        decs = [_target(d.id, d.statement, [d.source_reference]) for d in self.decisions]
        reqs = [_target(r.id, r.statement, [r.source_reference]) for r in self.requirements]

        def links(text: str, refs: list[SourceReference], targets: list[_Target]) -> list[str]:
            return _infer_links(text, _ref_lines(refs), targets)

        tasks = [
            t.model_copy(update={"related_requirement_ids": links(
                f"{t.title} {t.description}", t.source_references, reqs)})
            for t in self.tasks
        ]
        risks = [
            r.model_copy(update={"related_requirement_ids": links(
                r.description, [r.source_reference], reqs)})
            for r in self.risks
        ]
        questions = [
            q.model_copy(update={"related_requirement_ids": links(
                f"{q.question} {q.context}", [q.source_reference], reqs)})
            for q in self.open_questions
        ]
        risk_links: dict[str, list[str]] = {}
        for risk in risks:
            for req_id in risk.related_requirement_ids:
                risk_links.setdefault(req_id, []).append(risk.id)
        requirements = [
            r.model_copy(update={
                "related_decision_ids": links(r.statement, [r.source_reference], decs),
                "related_risk_ids": risk_links.get(r.id, []),
            })
            for r in self.requirements
        ]
        return MeetingAnalysis(
            decisions=self.decisions,
            requirements=requirements,
            tasks=tasks,
            risks=risks,
            open_questions=questions,
        )


def _source(grounding: Grounding, grounder: Grounder, claim: str) -> SourceReference:
    lines = grounding.lines
    speakers = {line.speaker for line in lines}
    speaker = next(iter(speakers)) if len(speakers) == 1 else None
    parts = []
    for line in lines:
        text = grounder.excerpt(line, claim)
        if speaker is None and line.speaker:
            text = f"{line.speaker}: {text}"
        parts.append(text)
    # Trimmed lines carry their own "…", so joining can double them up.
    excerpt = re.sub(r"…(?:\s*…)+", "…", " … ".join(parts))
    return SourceReference(
        excerpt=excerpt,
        line_start=lines[0].source_line,
        line_end=lines[-1].source_line,
        speaker=speaker,
    )


def _upgrades_hedge(claim: str, grounding: Grounding) -> bool:
    """The evidence is an estimate or option, but the claim states an obligation.

    "Karan estimated the team could support approximately 50" must not become
    "the team must handle 50".
    """
    evidence = " ".join(line.content for line in grounding.lines)
    return is_hedged(evidence) and not is_hedged(claim)


_Target = tuple[str, str, set[int]]


def _target(item_id: str, text: str, refs: list[SourceReference]) -> _Target:
    return item_id, text, _ref_lines(refs)


def _ref_lines(refs: list[SourceReference]) -> set[int]:
    lines: set[int] = set()
    for ref in refs:
        if ref.line_start is not None:
            lines.update(range(ref.line_start, (ref.line_end or ref.line_start) + 1))
    return lines


def _infer_links(text: str, lines: set[int], targets: list[_Target]) -> list[str]:
    """IDs of the targets this item most plausibly relates to, best first."""
    scored: list[tuple[float, str]] = []
    for target_id, target_text, target_lines in targets:
        score = similarity(text, target_text)
        needed = _LINK_SIMILARITY_SAME_LINES if lines & target_lines else _LINK_SIMILARITY
        shared, overlap = shared_words(text, target_text)
        if score >= needed:
            scored.append((score, target_id))
        elif shared >= _LINK_MIN_SHARED_WORDS and overlap >= _LINK_MIN_OVERLAP:
            scored.append((overlap / 2, target_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [target_id for _, target_id in scored[:_MAX_LINKS]]


def _first_line(value: str) -> str:
    return value.splitlines()[0] if value else value


def _preview(value: str, limit: int = 300) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit] + "..."
