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
    adds_facts,
    affirms,
    asserts_unstated_negative,
    coverage,
    describes_present,
    is_question,
    is_unresolved,
    restore_modality,
    is_hedged,
    as_question,
    is_commitment,
    is_gate,
    restore_present,
    restore_qualifiers,
    states_rule_without_concern,
    word_set,
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
    VERIFY_SCHEMA,
    VerifyPass,
)
from app.analysis.transcript import NumberedTranscript, TranscriptChunk, TranscriptLine
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
# Wherever its evidence comes from, a requirement this much made of one
# decision's words is that decision restated.
_RESTATED_DECISION_COVERAGE = 0.7
# Inferred links: wording overlap needed, lower when evidence lines are shared.
_LINK_SIMILARITY = 0.3
_LINK_SIMILARITY_SAME_LINES = 0.12
# Or: at least this many distinctive words shared, covering this much of the shorter text.
_LINK_MIN_SHARED_WORDS = 2
_LINK_MIN_OVERLAP = 0.5
_MAX_LINKS = 2
# After a question, look this many lines ahead for the answer; quote at most this many.
# Lines after an open question's evidence that may say it was left open.
_OPEN_WINDOW = 4
_ANSWER_WINDOW = 3
_MAX_ANSWER_LINES = 2
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


# Passes that get a second look. Measured on five answer-keyed meetings, a
# second look at decisions and requirements found 24 more real items with no
# more false ones; for tasks it mostly re-filed requirements as tasks.
_SECOND_LOOK_PASSES = frozenset({"decisions", "requirements"})


VERIFY_STAGE = "Checking decisions"
# Lines of context shown on each side of an item's evidence in the check.
_VERIFY_CONTEXT = 3
_VERIFY_LINE_CHARS = 260


def planned_stages(chunks: int, second_look: bool, verify: bool = False) -> list[str]:
    """Stage labels in the order MeetingAnalyzer.run reports them.

    The progress screen, the step counter and the time estimate all read this
    list, so none of them has to guess how many calls a run makes.
    """
    labels: list[str] = []
    for index in range(chunks):
        for spec in PASSES:
            label = spec.label if chunks == 1 else f"{spec.label} · part {index + 1}/{chunks}"
            labels.append(label)
            if second_look and spec.key in _SECOND_LOOK_PASSES:
                labels.append(f"{label} · second look")
    if verify:
        labels.append(VERIFY_STAGE)
    return labels


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
    # What the model proposed but a check removed: {"kind", "text", "reason"}.
    dropped: list[dict[str, str]] = field(default_factory=list)


class MeetingAnalyzer:
    """Turn a meeting transcript into a validated MeetingAnalysis via LLMProvider."""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        chunk_max_tokens: int = DEFAULT_CHUNK_MAX_TOKENS,
        max_transcript_chars: int | None = None,
        second_look: bool = False,
        verify: bool = False,
    ) -> None:
        self._llm = llm
        self._chunk_max_tokens = chunk_max_tokens
        self._max_transcript_chars = max_transcript_chars
        # After each pass, show the model what it found and ask only for what
        # it missed. Recall, not precision, is what a small model lacks.
        self._second_look = second_look
        # After extraction, label each decision and requirement against its
        # lines (agreed / deferred / proposed / open / assignment) and act on it.
        self._verify = verify

    def analyze(self, transcript: str, progress: Progress | None = None) -> MeetingAnalysis:
        return self.run(transcript, progress).analysis

    def stage_labels(self, transcript: str) -> list[str]:
        """The stages ``run`` will report, in order (one per model call)."""
        numbered = NumberedTranscript(transcript.strip())
        return planned_stages(len(numbered.chunks(self._chunk_max_tokens)), self._second_look, self._verify)

    def stage_count(self, transcript: str) -> int:
        """How many model calls (without retries) ``run`` will make."""
        return len(self.stage_labels(transcript))

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
        total = len(planned_stages(len(chunks), self._second_look, self._verify)) + extra_stages
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
                if not (self._second_look and spec.key in _SECOND_LOOK_PASSES):
                    continue
                step += 1
                progress.stage(f"{label} · second look", step, total)
                found = builder.already_found(spec.key)
                if not found:
                    continue  # the same prompt again would give the same answer
                more = self._run_pass(
                    spec, chunk, len(chunks), builder, progress, f"{label} · second look", second_look=found
                )
                if more is not None:
                    builder.add(spec.key, more)

        if self._verify:
            step += 1
            progress.stage(VERIFY_STAGE, step, total)
            self._run_verify(builder, progress)
        return self._finish(builder, chunks)

    def _run_verify(self, builder: "_RecordBuilder", progress: Progress) -> None:
        items = builder.verify_items()
        if not items:
            return
        prompt = prompts.build_verify_prompt(items)
        for attempt in (1, 2):
            try:
                raw = self._llm.generate(prompt, schema=VERIFY_SCHEMA, on_tokens=progress.tokens)
                result = VerifyPass.model_validate(parse_json_object(raw))
            except LLMOutputTruncatedError:
                logger.warning("analysis_verify_truncated attempt=%d", attempt)
                continue
            except LLMProviderError:
                logger.exception("analysis_verify_llm_failed")
                raise
            except (ValueError, ValidationError) as exc:
                logger.warning("analysis_verify_invalid attempt=%d error=%s", attempt, _first_line(str(exc)))
                continue
            builder.apply_checks(result.checks)
            return
        builder.warn("The final consistency check could not run; decisions were kept as extracted.")

    def _finish(self, builder: "_RecordBuilder", chunks: list[TranscriptChunk]) -> AnalysisOutcome:
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
        return AnalysisOutcome(analysis, list(builder.warnings), len(chunks), list(builder.dropped))

    def _run_pass(
        self,
        spec: _Pass,
        chunk: TranscriptChunk,
        total_chunks: int,
        builder: "_RecordBuilder",
        progress: Progress,
        label: str,
        *,
        second_look: list[str] | None = None,
    ) -> ExtractionModel | None:
        note: str | None = None
        for attempt in (1, 2):
            prompt = prompts.build_pass_prompt(
                chunk,
                total_chunks,
                spec.task,
                already_found=builder.already_found(spec.key) if chunk.index and not second_look else (),
                second_look=second_look or (),
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
        self.dropped: list[dict[str, str]] = []

    def _drop(self, kind: str, claim: str, reason: str, *, duplicate: bool = False) -> None:
        if duplicate:
            self.dropped_duplicates += 1
        else:
            self.dropped_ungrounded += 1
        self.dropped.append({"kind": kind, "text": claim, "reason": reason})
        logger.info("analysis_dropped kind=%s reason=%s claim=%s", kind, reason, _preview(claim, 120))

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
            self._drop(kind, claim, "no line in the transcript supports it")
            return None
        if reject is not None and reject(grounding):
            return None
        if self._is_duplicate(claim, grounding, self._seen[kind]):
            self._drop(kind, claim, "duplicate", duplicate=True)
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
        grounding = self._accept(
            "decision", item.statement, item.lines, reject=lambda g: self._reject_decision(item.statement, g)
        )
        if grounding is None:
            return
        if all(is_question(line.content) for line in grounding.lines):
            grounding = self._with_answer(grounding, item.statement)
        self.decisions.append(
            Decision(
                id=format_item_id(DEC_PREFIX, len(self.decisions) + 1),
                statement=_faithful(item.statement, grounding),
                confidence=grounding.confidence,
                source_reference=self._source(grounding, item.statement),
            )
        )

    def _add_requirement(self, item: ExtractedRequirement) -> None:
        if any(
            similarity(item.statement, d.statement) >= _RESTATED_DECISION_SIMILARITY
            for d in self.decisions
        ):
            self._drop("requirement", item.statement, "restates a decision", duplicate=True)
            return
        grounding = self._accept(
            "requirement",
            item.statement,
            item.lines,
            reject=lambda g: self._reject_requirement(item.statement, g),
        )
        if grounding is None:
            return
        grounding = self._with_answer(grounding, item.statement)
        self.requirements.append(
            Requirement(
                id=format_item_id(REQ_PREFIX, len(self.requirements) + 1),
                statement=_faithful(item.statement, grounding),
                confidence=grounding.confidence,
                source_reference=self._source(grounding, item.statement),
            )
        )

    def _reject_decision(self, statement: str, grounding: Grounding) -> bool:
        if any(is_unresolved(line.content) for line in grounding.lines):
            # "Undecided. ... I'd rather benchmark without Redis first" is not
            # a decision against Redis.
            self._drop("decision", statement, "the meeting left this undecided")
            return True
        return False

    def _reject_requirement(self, statement: str, grounding: Grounding) -> bool:
        if all(is_commitment(line.content) for line in grounding.lines):
            self._drop("requirement", statement, "someone took this on as work; it is a task")
            return True
        if any(
            coverage(statement, d.statement) >= _RESTATED_DECISION_COVERAGE
            for d in self.decisions
        ):
            self._drop("requirement", statement, "restates a decision", duplicate=True)
            return True
        if self._restates_decisions(statement, grounding):
            self._drop("requirement", statement, "restates the decisions list", duplicate=True)
            return True
        if _upgrades_hedge(statement, grounding):
            self._drop("requirement", statement, "turns an estimate or suggestion into a must")
            return True
        if describes_present(_evidence_text(grounding)):
            self._drop("requirement", statement, "describes how things are now, not a requirement")
            return True
        return False

    def _reject_risk(self, description: str, grounding: Grounding) -> bool:
        evidence = _evidence_text(grounding)
        if all(is_unresolved(line.content) for line in grounding.lines):
            # "needs to determine X" is an open question; any consequence the
            # model attached ("could lead to data loss") was its own idea.
            self._drop("risk", description, "an unresolved item, not a risk; kept as an open question")
            self._add_open_question(
                ExtractedOpenQuestion(
                    question=_sentence_case(
                        re.sub(r"^(?:so|then|okay|ok|and)\b,?\s*", "", grounding.lines[0].content, flags=re.IGNORECASE)
                    ),
                    context="Left unresolved in the meeting.",
                    lines=[line.number for line in grounding.lines],
                )
            )
            return True
        if asserts_unstated_negative(description, evidence):
            self._drop("risk", description, "claims something is not so; nobody said that")
            return True
        if states_rule_without_concern(evidence):
            self._drop("risk", description, "restates a rule as a risk; nobody raised a concern")
            return True
        if all(is_question(line.content) for line in grounding.lines):
            answer = self._next_line(grounding)
            if answer is None or not affirms(answer.content):
                self._drop("risk", description, "only a question, and nobody confirmed it")
                return True
            if states_rule_without_concern(_evidence_text(self._with_answer(grounding, description))):
                self._drop("risk", description, "restates a rule as a risk; nobody raised a concern")
                return True
        return False

    def _next_line(self, grounding: Grounding) -> TranscriptLine | None:
        return self._transcript.get(grounding.lines[-1].number + 1)

    def _with_answer(self, grounding: Grounding, claim: str) -> Grounding:
        """Evidence that is only a question also shows the answer.

        The answer is the following line(s) that best support the claim, not
        simply the next line: after "Arjun asked whether exactly-once was
        required", "He recommended at-least-once delivery" is the conclusion.
        """
        if not all(is_question(line.content) for line in grounding.lines):
            return grounding
        last = grounding.lines[-1].number
        following = [
            line
            for n in range(last + 1, last + 1 + _ANSWER_WINDOW)
            if (line := self._transcript.get(n)) is not None
        ]
        if not following:
            return grounding
        # The direct reply comes first when it confirms ("Mehul acknowledged
        # that it could"), even though it shares no words with the claim.
        chosen = [following[0]] if affirms(following[0].content) else []
        claim_words = word_set(claim)
        scored = [
            (len(claim_words & word_set(line.content)), line)
            for line in following
            if line not in chosen
        ]
        for score, line in sorted(scored, key=lambda s: -s[0]):
            if score <= 0 or len(chosen) >= _MAX_ANSWER_LINES:
                break
            chosen.append(line)
        answer = sorted(chosen, key=lambda l: l.number) or following[:1]
        return Grounding(grounding.lines + tuple(answer), grounding.score, grounding.reanchored)

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
        grounding = self._accept("task", claim, item.lines, reject=lambda g: self._reject_task(claim, g))
        if grounding is None:
            return
        criteria = []
        for criterion in (c.strip() for c in item.acceptance_criteria if c and c.strip()):
            invented = adds_facts(criterion, self._transcript.text)
            if invented:
                self._drop("task criterion", criterion, f"number or date not in the meeting: {', '.join(sorted(invented))}")
                continue
            criteria.append(criterion)
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

    def _reject_task(self, claim: str, grounding: Grounding) -> bool:
        evidence = _evidence_text(grounding)
        if is_gate(evidence) and not is_commitment(evidence):
            # "No production schema change until the benchmark is reviewed" is
            # a constraint; nobody took it on as work.
            self._drop("task", claim, "a constraint on timing, not a piece of work")
            return True
        return False

    def _add_risk(self, item: ExtractedRisk) -> None:
        grounding = self._accept(
            "risk",
            item.description,
            item.lines,
            reject=lambda g: self._reject_risk(item.description, g),
        )
        if grounding is None:
            return
        grounding = self._with_answer(grounding, item.description)
        self.risks.append(
            Risk(
                id=format_item_id(RSK_PREFIX, len(self.risks) + 1),
                description=restore_present(_faithful(item.description, grounding), _evidence_text(grounding)),
                severity=item.severity,
                source_reference=self._source(grounding, item.description),
            )
        )

    def _add_open_question(self, item: ExtractedOpenQuestion) -> None:
        claim = f"{item.question} {item.context}".strip()
        grounding = self._accept(
            "open_question", claim, item.lines, reject=lambda g: self._reject_open_question(claim, g)
        )
        if grounding is None:
            return
        context = item.context.strip() or grounding.lines[0].content
        self.open_questions.append(
            OpenQuestion(
                id=format_item_id(OQ_PREFIX, len(self.open_questions) + 1),
                question=as_question(item.question),
                context=context,
                source_reference=self._source(grounding, claim),
            )
        )

    def _reject_open_question(self, claim: str, grounding: Grounding) -> bool:
        """A question the meeting answered is not open.

        "Are we requiring exactly-once?" ... "At-least-once is sufficient"
        was settled; an open question needs something left open nearby.
        """
        source_lines = {line.source_line for line in grounding.lines}
        question = word_set(claim.split("?")[0])
        for other in self.open_questions:
            if _ref_lines([other.source_reference]) == source_lines and question & word_set(other.question):
                # Same line, same subject ("thresholds"): the same question.
                self._drop("open question", claim, "duplicate", duplicate=True)
                return True
        last = grounding.lines[-1].number
        nearby = [line.content for line in grounding.lines]
        nearby += [
            line.content
            for n in range(last + 1, last + 1 + _OPEN_WINDOW)
            if (line := self._transcript.get(n)) is not None
        ]
        if any(is_unresolved(text) for text in nearby):
            return False
        self._drop("open question", claim, "the meeting answered it")
        return True

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

    # ------------------------------------------------------------ verify pass

    def verify_items(self) -> list[tuple[str, str, list[str]]]:
        """Each decision and requirement with the lines around its evidence."""
        items = []
        for item_id, statement, ref in (
            [(d.id, d.statement, d.source_reference) for d in self.decisions]
            + [(r.id, r.statement, r.source_reference) for r in self.requirements]
        ):
            dense = self._dense_lines(ref)
            if not dense:
                continue
            window = range(min(dense) - _VERIFY_CONTEXT, max(dense) + _VERIFY_CONTEXT + 1)
            lines = []
            for n in window:
                line = self._transcript.get(n)
                if line is not None:
                    text = line.text if len(line.text) <= _VERIFY_LINE_CHARS else line.text[:_VERIFY_LINE_CHARS] + "…"
                    lines.append(f"L{line.source_line} {text}")
            items.append((item_id, statement, lines))
        return items

    def apply_checks(self, checks: list[Any]) -> None:
        """Act on the verify labels: drop proposals and assignments, move open
        items to open questions, and add deferred ones as open questions too."""
        by_id = {c.id.strip().upper(): c for c in checks}
        kept_decisions = [d for d in self.decisions if self._apply_check("decision", d.statement, d.source_reference, by_id.get(d.id))]
        kept_requirements = [r for r in self.requirements if self._apply_check("requirement", r.statement, r.source_reference, by_id.get(r.id))]
        self.decisions = [d.model_copy(update={"id": format_item_id(DEC_PREFIX, i)}) for i, d in enumerate(kept_decisions, 1)]
        self.requirements = [r.model_copy(update={"id": format_item_id(REQ_PREFIX, i)}) for i, r in enumerate(kept_requirements, 1)]

    def _apply_check(self, kind: str, statement: str, ref: SourceReference, check: Any) -> bool:
        if check is None or check.status == "agreed":
            return True
        if check.status == "proposed":
            self._drop(kind, statement, "only proposed; the meeting did not agree it")
            return False
        if check.status == "assignment":
            self._drop(kind, statement, "work someone was asked to do; it is a task")
            return False
        question = check.question.strip()
        if check.status == "open":
            self._drop(kind, statement, "the meeting left this undecided; kept as an open question")
            self._question_from(question or statement, "Left undecided in the meeting.", ref)
            return False
        # deferred: the "not yet" stands, and the decision is still to be made.
        if question:
            self._question_from(question, "Deferred until the analysis is reviewed.", ref)
        return True

    def _question_from(self, question: str, context: str, ref: SourceReference) -> None:
        dense = self._dense_lines(ref)
        grounding = self._grounder.ground(question, dense[:2]) if dense else None
        if grounding is None:
            self._drop("open question", question, "no line in the transcript supports it")
            return
        if self._is_duplicate(question, grounding, self._seen["open_question"]):
            self._drop("open question", question, "duplicate", duplicate=True)
            return
        self._seen["open_question"].append((question, grounding))
        self.open_questions.append(
            OpenQuestion(
                id=format_item_id(OQ_PREFIX, len(self.open_questions) + 1),
                question=as_question(question),
                context=context,
                source_reference=ref,
            )
        )

    def _dense_lines(self, ref: SourceReference) -> list[int]:
        if ref.line_start is None:
            return []
        end = ref.line_end or ref.line_start
        return [line.number for line in self._transcript.lines if ref.line_start <= line.source_line <= end]

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


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def _evidence_text(grounding: Grounding) -> str:
    return " ".join(line.content for line in grounding.lines)


def _faithful(claim: str, grounding: Grounding) -> str:
    """The claim with the evidence's qualifiers and modal strength put back."""
    evidence = _evidence_text(grounding)
    return restore_modality(restore_qualifiers(claim, evidence), evidence)


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
