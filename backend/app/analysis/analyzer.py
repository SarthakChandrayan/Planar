import logging

from pydantic import ValidationError

from app.analysis.errors import AnalysisValidationError, EmptyTranscriptError
from app.analysis.excerpts import excerpt_supported_by_transcript, excerpt_supports_claim
from app.analysis.normalize import normalize_extracted_payload
from app.analysis.parsing import parse_json_object
from app.analysis.prompts import build_meeting_analysis_prompt
from app.analysis.schemas import (
    ExtractedMeetingAnalysis,
    ExtractedTask,
)
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
from app.llm import LLMProvider, LLMProviderError

logger = logging.getLogger(__name__)

_LLM_PREVIEW_CHARS = 500


class MeetingAnalyzer:
    """Turn a meeting transcript into a validated MeetingAnalysis via LLMProvider."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def analyze(self, transcript: str) -> MeetingAnalysis:
        cleaned = transcript.strip()
        if not cleaned:
            raise EmptyTranscriptError("transcript must not be empty")

        logger.info(
            "meeting_analysis_started transcript_chars=%d",
            len(cleaned),
        )

        prompt = build_meeting_analysis_prompt(cleaned)
        try:
            raw = self._llm.generate(prompt)
        except LLMProviderError:
            logger.exception("meeting_analysis_llm_failed")
            raise

        analysis = self._parse_and_validate(raw, transcript=cleaned)
        logger.info(
            "meeting_analysis_completed decisions=%d requirements=%d "
            "tasks=%d risks=%d open_questions=%d",
            len(analysis.decisions),
            len(analysis.requirements),
            len(analysis.tasks),
            len(analysis.risks),
            len(analysis.open_questions),
        )
        return analysis

    def _parse_and_validate(self, raw: str, *, transcript: str) -> MeetingAnalysis:
        try:
            payload = parse_json_object(raw)
            payload = normalize_extracted_payload(payload)
            extracted = ExtractedMeetingAnalysis.model_validate(payload)
            extracted = _drop_unsupported_excerpts(extracted, transcript)
            extracted = _drop_misaligned_evidence(extracted)
            return _to_domain(extracted)
        except AnalysisValidationError:
            raise
        except (ValueError, ValidationError) as exc:
            logger.warning(
                "meeting_analysis_validation_failed error=%s llm_preview=%s",
                exc,
                _preview(raw, _LLM_PREVIEW_CHARS),
            )
            raise AnalysisValidationError(
                "The language model returned invalid analysis output.",
                detail=str(exc),
            ) from exc


def _drop_unsupported_excerpts(
    extracted: ExtractedMeetingAnalysis,
    transcript: str,
) -> ExtractedMeetingAnalysis:
    """Keep only items whose source excerpts appear in the transcript."""
    decisions = [
        item
        for item in extracted.decisions
        if excerpt_supported_by_transcript(item.source_reference.excerpt, transcript)
    ]
    requirements = [
        item
        for item in extracted.requirements
        if excerpt_supported_by_transcript(item.source_reference.excerpt, transcript)
    ]
    tasks: list[ExtractedTask] = []
    for item in extracted.tasks:
        refs = [
            ref
            for ref in item.source_references
            if excerpt_supported_by_transcript(ref.excerpt, transcript)
        ]
        if refs:
            tasks.append(item.model_copy(update={"source_references": refs}))
    risks = [
        item
        for item in extracted.risks
        if excerpt_supported_by_transcript(item.source_reference.excerpt, transcript)
    ]
    open_questions = [
        item
        for item in extracted.open_questions
        if excerpt_supported_by_transcript(item.source_reference.excerpt, transcript)
    ]

    dropped = (
        len(extracted.decisions)
        + len(extracted.requirements)
        + len(extracted.tasks)
        + len(extracted.risks)
        + len(extracted.open_questions)
        - len(decisions)
        - len(requirements)
        - len(tasks)
        - len(risks)
        - len(open_questions)
    )
    if dropped:
        logger.warning("meeting_analysis_dropped_unsupported_excerpts count=%d", dropped)

    return extracted.model_copy(
        update={
            "decisions": decisions,
            "requirements": requirements,
            "tasks": tasks,
            "risks": risks,
            "open_questions": open_questions,
        }
    )


def _drop_misaligned_evidence(
    extracted: ExtractedMeetingAnalysis,
) -> ExtractedMeetingAnalysis:
    """Drop items whose transcript-backed excerpt does not support the claim."""
    decisions = [
        item
        for index, item in enumerate(extracted.decisions, start=1)
        if _keep_supported_item(
            category="decision",
            index=index,
            claim=item.statement,
            excerpt=item.source_reference.excerpt,
        )
    ]
    requirements = [
        item
        for index, item in enumerate(extracted.requirements, start=1)
        if _keep_supported_item(
            category="requirement",
            index=index,
            claim=item.statement,
            excerpt=item.source_reference.excerpt,
        )
    ]
    tasks: list[ExtractedTask] = []
    for index, item in enumerate(extracted.tasks, start=1):
        claim = f"{item.title} {item.description}".strip()
        refs = []
        for ref_index, ref in enumerate(item.source_references, start=1):
            if excerpt_supports_claim(claim, ref.excerpt):
                refs.append(ref)
            else:
                logger.warning(
                    "meeting_analysis_dropped_misaligned_evidence "
                    "category=task_reference index=%d ref_index=%d",
                    index,
                    ref_index,
                )
        if refs:
            tasks.append(item.model_copy(update={"source_references": refs}))
        else:
            logger.warning(
                "meeting_analysis_dropped_misaligned_evidence category=task index=%d",
                index,
            )
    risks = [
        item
        for index, item in enumerate(extracted.risks, start=1)
        if _keep_supported_item(
            category="risk",
            index=index,
            claim=item.description,
            excerpt=item.source_reference.excerpt,
        )
    ]
    open_questions = [
        item
        for index, item in enumerate(extracted.open_questions, start=1)
        if _keep_supported_item(
            category="open_question",
            index=index,
            claim=f"{item.question} {item.context}".strip(),
            excerpt=item.source_reference.excerpt,
        )
    ]
    return extracted.model_copy(
        update={
            "decisions": decisions,
            "requirements": requirements,
            "tasks": tasks,
            "risks": risks,
            "open_questions": open_questions,
        }
    )


def _keep_supported_item(
    *,
    category: str,
    index: int,
    claim: str,
    excerpt: str,
) -> bool:
    if excerpt_supports_claim(claim, excerpt):
        return True
    logger.warning(
        "meeting_analysis_dropped_misaligned_evidence category=%s index=%d",
        category,
        index,
    )
    return False


def _to_domain(extracted: ExtractedMeetingAnalysis) -> MeetingAnalysis:
    return MeetingAnalysis(
        decisions=[
            Decision(
                id=format_item_id(DEC_PREFIX, index),
                statement=item.statement,
                confidence=item.confidence,
                source_reference=SourceReference(excerpt=item.source_reference.excerpt),
            )
            for index, item in enumerate(extracted.decisions, start=1)
        ],
        requirements=[
            Requirement(
                id=format_item_id(REQ_PREFIX, index),
                statement=item.statement,
                confidence=item.confidence,
                source_reference=SourceReference(excerpt=item.source_reference.excerpt),
            )
            for index, item in enumerate(extracted.requirements, start=1)
        ],
        tasks=[
            Task(
                id=format_item_id(TSK_PREFIX, index),
                title=item.title,
                description=item.description,
                priority=item.priority,
                acceptance_criteria=list(item.acceptance_criteria),
                source_references=[
                    SourceReference(excerpt=ref.excerpt) for ref in item.source_references
                ],
            )
            for index, item in enumerate(extracted.tasks, start=1)
        ],
        risks=[
            Risk(
                id=format_item_id(RSK_PREFIX, index),
                description=item.description,
                severity=item.severity,
                source_reference=SourceReference(excerpt=item.source_reference.excerpt),
            )
            for index, item in enumerate(extracted.risks, start=1)
        ],
        open_questions=[
            OpenQuestion(
                id=format_item_id(OQ_PREFIX, index),
                question=item.question,
                context=item.context,
                source_reference=SourceReference(excerpt=item.source_reference.excerpt),
            )
            for index, item in enumerate(extracted.open_questions, start=1)
        ],
    )


def _preview(value: str, limit: int) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."
