"""Deterministic comparison of a MeetingAnalysis against a golden answer key.

Artifact scoring (values clamped to [0, 1]):

    overall_score =
        match_rate
        * (0.75 ** forbidden_count)
        * (1 - 0.10 * unexpected_fraction)
        * (1 - 0.05 * missing_source_fraction)

    match_rate = matched_expected / total_expected
    unexpected_fraction = unexpected_count / max(ai_artifact_count, 1)
    missing_source_fraction = missing_source_count / max(ai_artifact_count, 1)

Family scoring (independent of artifact match_rate):

    family_coverage_score =
        (matched_families + 0.5 * partial_families) / total_families

    A core_group is satisfied if ANY artifact key in that group is matched.
    Family status:
        matched  = every core_group is satisfied
        partial  = some but not all core_groups are satisfied
        missed   = no core_group is satisfied

This does not average raw artifact counts, so overlapping decision /
requirement / task restatements of one lock do not dominate the family score.
"""

from __future__ import annotations

import re
from math import ceil
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import MeetingAnalysis
from tests.evaluation.payment_platform_redesign_expected import (
    Category,
    ExpectedArtifact,
    ForbiddenConcept,
    GoldenAnswerKey,
    PAYMENT_PLATFORM_REDESIGN_GOLDEN,
)
from tests.evaluation.payment_platform_redesign_families import (
    CoverageFamily,
    PAYMENT_PLATFORM_REDESIGN_FAMILIES,
)

# Each forbidden promotion keeps 75% of the current score.
_FORBIDDEN_FACTOR = 0.75
# If every AI artifact is unexpected, subtract 10% of the remaining score.
_UNEXPECTED_WEIGHT = 0.10
# If every AI artifact is missing a source, subtract 5% of the remaining score.
_MISSING_SOURCE_WEIGHT = 0.05
# A partially covered family contributes half a matched family.
_PARTIAL_FAMILY_CREDIT = 0.5

_REJECTION_MARKERS = (
    "out of scope",
    "still out of scope",
    "not introducing",
    "do not introduce",
    "don't introduce",
    "do not need",
    "do not use",
    "don't use",
    "not using",
    "no new",
    "not the source",
    "can come later",
    "rejected",
    "was rejected",
    "in favor of",
    "instead of",
    "we are not",
    "we're not",
    "not accepted",
    "must not",
    "will not",
    "do not implement",
    "don't implement",
    "not implement",
    "could be",
    "might be",
    "leading to",
    "don't like",
    "do not like",
)

_PROMOTION_CUES = (
    "use ",
    "using ",
    "adopt",
    "implement",
    "we will",
    "will use",
    "must ",
    "should ",
    "required",
    "supported in",
    "as the source of truth",
    "source of truth for",
)

# Interchangeable phrases. If a golden keyword is in a group, any phrase
# in that group can satisfy the keyword.
_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "state machine",
            "state transitions",
            "internal state",
            "modeled explicitly",
            "modelled explicitly",
        }
    ),
    frozenset({"source of truth", "authoritative"}),
    frozenset(
        {
            "actual thresholds",
            "rollout thresholds",
            "rollback thresholds",
            "rollout threshold",
            "rollback threshold",
        }
    ),
    frozenset(
        {
            "open item",
            "not a decision yet",
            "not decided yet",
            "not decided",
        }
    ),
    frozenset(
        {
            "implement the consumer",
            "sqs consumer",
            "webhook consumer",
        }
    ),
    frozenset({"postgres", "postgresql"}),
    frozenset({"paymentintents", "payment intents", "payment intent"}),
    frozenset({"asynchronously", "asynchronous"}),
    frozenset({"same key", "same idempotency key"}),
    frozenset(
        {
            "not introducing kafka",
            "do not introduce kafka",
            "don't introduce kafka",
            "no new kafka",
            "do not need kafka",
        }
    ),
)

# Applied only to golden descriptions so paraphrases can overlap without
# leaking those synonyms onto unrelated AI artifacts.
_SYNONYM_TOKENS: dict[str, frozenset[str]] = {
    "machine": frozenset({"transitions", "modeled", "modelled"}),
    "thresholds": frozenset({"threshold"}),
    "rollout": frozenset({"rollback"}),
    "asynchronous": frozenset({"asynchronously"}),
    "verify": frozenset({"verified", "verification"}),
    "webhook": frozenset({"webhooks"}),
}

_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "for",
    "to",
    "of",
    "in",
    "on",
    "at",
    "as",
    "is",
    "be",
    "this",
    "that",
    "with",
    "from",
    "must",
    "should",
    "our",
    "we",
    "use",
    "using",
}

_WEAK_TOKENS = _STOPWORDS | {
    "payment",
    "payments",
    "implement",
    "implementation",
    "implemented",
    "state",
    "states",
    "question",
    "questions",
    "open",
    "item",
    "items",
    "need",
    "needs",
    "needed",
    "make",
    "made",
    "add",
    "added",
    "create",
    "created",
    "existing",
    "process",
    "processing",
    "processed",
    "system",
    "team",
    "will",
    "can",
    "could",
    "would",
    "also",
    "more",
    "than",
    "then",
    "into",
    "used",
    "based",
    "related",
    "work",
    "task",
    "tasks",
    "requirement",
    "decision",
    "risk",
    "thing",
    "things",
    "normal",
    "counts",
    "what",
    "how",
    "when",
    "where",
    "which",
    "their",
    "have",
    "has",
    "been",
    "being",
    "does",
    "done",
    "just",
    "only",
    "some",
    "any",
    "all",
    "each",
    "other",
    "about",
    "after",
    "before",
    "over",
    "still",
    "scope",
    "november",
    "release",
    "same",
}


class UnexpectedArtifact(BaseModel):
    id: str
    category: Category
    text: str


class ForbiddenViolation(BaseModel):
    forbidden_key: str
    artifact_id: str
    category: Category
    text: str


class MissingSourceReference(BaseModel):
    artifact_id: str
    category: Category


FamilyStatus = Literal["matched", "partial", "missed"]


class FamilyCoverageResult(BaseModel):
    key: str
    status: FamilyStatus
    satisfied_core_groups: int
    total_core_groups: int
    matched_artifact_keys: list[str] = Field(default_factory=list)
    missed_artifact_keys: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    total_expected: int
    matched_expected: int
    missed_expected: int
    match_rate: float
    unexpected_artifacts: list[UnexpectedArtifact] = Field(default_factory=list)
    forbidden_violations: list[ForbiddenViolation] = Field(default_factory=list)
    missing_source_references: list[MissingSourceReference] = Field(default_factory=list)
    matched_expected_keys: list[str] = Field(default_factory=list)
    missed_expected_keys: list[str] = Field(default_factory=list)
    overall_score: float
    family_results: list[FamilyCoverageResult] = Field(default_factory=list)
    matched_families: list[str] = Field(default_factory=list)
    partial_families: list[str] = Field(default_factory=list)
    missed_families: list[str] = Field(default_factory=list)
    family_coverage_score: float = 0.0


class _AiItem:
    def __init__(
        self,
        artifact_id: str,
        category: Category,
        body: str,
        excerpts: tuple[str, ...],
        has_source: bool,
    ) -> None:
        self.artifact_id = artifact_id
        self.category = category
        self.body = body
        self.excerpts = excerpts
        self.has_source = has_source
        self.normalized_body = normalize_text(body)


def evaluate(
    analysis: MeetingAnalysis,
    golden: GoldenAnswerKey = PAYMENT_PLATFORM_REDESIGN_GOLDEN,
    families: tuple[CoverageFamily, ...] = PAYMENT_PLATFORM_REDESIGN_FAMILIES,
) -> EvaluationResult:
    """Compare analysis to golden. Does not call an LLM."""
    ai_items = _collect_ai_items(analysis)
    expected_all = (
        list(golden.decisions)
        + list(golden.requirements)
        + list(golden.tasks)
        + list(golden.risks)
        + list(golden.open_questions)
    )

    matched_keys: list[str] = []
    matched_ai_ids: set[str] = set()
    for expected in expected_all:
        hits = _matching_items(expected, ai_items)
        if hits:
            matched_keys.append(expected.key)
            matched_ai_ids.update(item.artifact_id for item in hits)

    expected_keys = [item.key for item in expected_all]
    missed_keys = [key for key in expected_keys if key not in matched_keys]

    unexpected = [
        UnexpectedArtifact(
            id=item.artifact_id,
            category=item.category,
            text=item.body,
        )
        for item in ai_items
        if item.artifact_id not in matched_ai_ids
    ]

    forbidden = _find_forbidden_violations(ai_items, golden.forbidden)
    missing_sources = [
        MissingSourceReference(artifact_id=item.artifact_id, category=item.category)
        for item in ai_items
        if not item.has_source
    ]

    total = len(expected_all)
    matched = len(matched_keys)
    match_rate = (matched / total) if total else 1.0
    overall = _overall_score(
        match_rate=match_rate,
        forbidden_count=len(forbidden),
        unexpected_count=len(unexpected),
        missing_source_count=len(missing_sources),
        ai_count=len(ai_items),
    )
    family_results, family_score = _evaluate_families(families, set(matched_keys))
    matched_families = [item.key for item in family_results if item.status == "matched"]
    partial_families = [item.key for item in family_results if item.status == "partial"]
    missed_families = [item.key for item in family_results if item.status == "missed"]

    return EvaluationResult(
        total_expected=total,
        matched_expected=matched,
        missed_expected=len(missed_keys),
        match_rate=round(match_rate, 4),
        unexpected_artifacts=unexpected,
        forbidden_violations=forbidden,
        missing_source_references=missing_sources,
        matched_expected_keys=matched_keys,
        missed_expected_keys=missed_keys,
        overall_score=round(overall, 4),
        family_results=family_results,
        matched_families=matched_families,
        partial_families=partial_families,
        missed_families=missed_families,
        family_coverage_score=round(family_score, 4),
    )


def normalize_text(value: str) -> str:
    lowered = value.lower().replace("/", " ")
    cleaned = re.sub(r"[^a-z0-9\s{}_-]", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def _overall_score(
    *,
    match_rate: float,
    forbidden_count: int,
    unexpected_count: int,
    missing_source_count: int,
    ai_count: int,
) -> float:
    artifact_count = max(ai_count, 1)
    unexpected_fraction = min(unexpected_count / artifact_count, 1.0)
    missing_fraction = min(missing_source_count / artifact_count, 1.0)
    score = (
        match_rate
        * (_FORBIDDEN_FACTOR**forbidden_count)
        * (1.0 - _UNEXPECTED_WEIGHT * unexpected_fraction)
        * (1.0 - _MISSING_SOURCE_WEIGHT * missing_fraction)
    )
    return max(0.0, min(1.0, score))


def _evaluate_families(
    families: tuple[CoverageFamily, ...],
    matched_keys: set[str],
) -> tuple[list[FamilyCoverageResult], float]:
    if not families:
        return [], 1.0
    results: list[FamilyCoverageResult] = []
    matched_count = 0
    partial_count = 0
    for family in families:
        result = _evaluate_family(family, matched_keys)
        results.append(result)
        if result.status == "matched":
            matched_count += 1
        elif result.status == "partial":
            partial_count += 1
    score = (matched_count + _PARTIAL_FAMILY_CREDIT * partial_count) / len(families)
    return results, max(0.0, min(1.0, score))


def _evaluate_family(
    family: CoverageFamily,
    matched_keys: set[str],
) -> FamilyCoverageResult:
    matched_in_family = [key for key in family.artifact_keys if key in matched_keys]
    missed_in_family = [key for key in family.artifact_keys if key not in matched_keys]
    total_groups = len(family.core_groups)
    satisfied = sum(
        1
        for group in family.core_groups
        if any(key in matched_keys for key in group)
    )
    if total_groups == 0 or satisfied == 0:
        status: FamilyStatus = "missed"
    elif satisfied == total_groups:
        status = "matched"
    else:
        status = "partial"
    return FamilyCoverageResult(
        key=family.key,
        status=status,
        satisfied_core_groups=satisfied,
        total_core_groups=total_groups,
        matched_artifact_keys=matched_in_family,
        missed_artifact_keys=missed_in_family,
    )


def _collect_ai_items(analysis: MeetingAnalysis) -> list[_AiItem]:
    items: list[_AiItem] = []
    for decision in analysis.decisions:
        items.append(
            _AiItem(
                decision.id,
                "decision",
                decision.statement,
                (decision.source_reference.excerpt,),
                _excerpt_present(decision.source_reference.excerpt),
            )
        )
    for requirement in analysis.requirements:
        items.append(
            _AiItem(
                requirement.id,
                "requirement",
                requirement.statement,
                (requirement.source_reference.excerpt,),
                _excerpt_present(requirement.source_reference.excerpt),
            )
        )
    for task in analysis.tasks:
        body = " ".join(
            [task.title, task.description, *task.acceptance_criteria]
        )
        excerpts = tuple(ref.excerpt for ref in task.source_references)
        items.append(
            _AiItem(
                task.id,
                "task",
                body,
                excerpts,
                any(_excerpt_present(excerpt) for excerpt in excerpts),
            )
        )
    for risk in analysis.risks:
        items.append(
            _AiItem(
                risk.id,
                "risk",
                risk.description,
                (risk.source_reference.excerpt,),
                _excerpt_present(risk.source_reference.excerpt),
            )
        )
    for question in analysis.open_questions:
        body = f"{question.question} {question.context}"
        items.append(
            _AiItem(
                question.id,
                "open_question",
                body,
                (question.source_reference.excerpt,),
                _excerpt_present(question.source_reference.excerpt),
            )
        )
    return items


def _excerpt_present(excerpt: str) -> bool:
    return bool(excerpt.strip())


def _matching_items(
    expected: ExpectedArtifact,
    ai_items: list[_AiItem],
) -> list[_AiItem]:
    """Prefer same-category hits; allow a strong cross-category paraphrase."""
    same = [
        item
        for item in ai_items
        if item.category == expected.category and _matches_expected(expected, item)
    ]
    if same:
        return same
    return [
        item
        for item in ai_items
        if item.category != expected.category
        and _matches_expected(expected, item, cross_category=True)
    ]


def _matches_expected(
    expected: ExpectedArtifact,
    item: _AiItem,
    *,
    cross_category: bool = False,
) -> bool:
    text = item.normalized_body
    hits = sum(1 for keyword in expected.keywords if _keyword_present(keyword, text))
    required = _required_keyword_hits(len(expected.keywords))
    overlap = _description_token_overlap(expected.description, text)
    # Cross-category matches need a distinctive phrase or multiple keyword
    # hits. A single shared word like "rollout" must not claim unrelated items.
    if cross_category:
        return hits >= 1 and overlap >= 2 and (
            hits >= 2 or _has_multiword_keyword_hit(expected, text)
        )
    if hits >= required:
        return True
    return hits >= 1 and overlap >= 2


def _required_keyword_hits(keyword_count: int) -> int:
    if keyword_count <= 1:
        return keyword_count
    return max(2, ceil(keyword_count / 2))


def _keyword_present(keyword: str, text: str) -> bool:
    return any(_contains_phrase(text, phrase) for phrase in _alias_phrases(keyword))


def _has_multiword_keyword_hit(expected: ExpectedArtifact, text: str) -> bool:
    for keyword in expected.keywords:
        for phrase in _alias_phrases(keyword):
            if " " in normalize_text(phrase) and _contains_phrase(text, phrase):
                return True
    return False


def _alias_phrases(keyword: str) -> tuple[str, ...]:
    normalized = normalize_text(keyword)
    if not normalized:
        return ()
    for group in _ALIAS_GROUPS:
        normalized_group = tuple(normalize_text(phrase) for phrase in group)
        if normalized in normalized_group:
            return normalized_group
    return (normalized,)


def _contains_phrase(haystack: str, needle: str) -> bool:
    normalized = normalize_text(needle)
    if not normalized:
        return False
    if " " in normalized or "/" in normalized or "{" in normalized:
        if normalized in haystack:
            return True
        compact_hay = haystack.replace(" ", "")
        compact_needle = normalized.replace(" ", "")
        return len(compact_needle) >= 4 and compact_needle in compact_hay
    tokens = haystack.split()
    if normalized in tokens:
        return True
    # Allow webhooks/webhook, asynchronously/asynchronous for longer stems.
    return any(
        len(normalized) >= 6 and (token.startswith(normalized) or normalized.startswith(token))
        for token in tokens
        if len(token) >= 6
    )


def _description_token_overlap(description: str, text: str) -> int:
    expected_tokens = _expand_synonyms(_distinctive_tokens(description))
    item_tokens = _distinctive_tokens(text)
    return len(expected_tokens & item_tokens)


def _distinctive_tokens(text: str) -> set[str]:
    return {
        token
        for token in normalize_text(text).split()
        if len(token) >= 4 and token not in _WEAK_TOKENS
    }


def _expand_synonyms(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for token in tokens:
        expanded.update(_SYNONYM_TOKENS.get(token, ()))
    return expanded


def _find_forbidden_violations(
    ai_items: list[_AiItem],
    forbidden: tuple[ForbiddenConcept, ...],
) -> list[ForbiddenViolation]:
    # Inspect artifact bodies only. Source excerpts can quote a rejected idea
    # without promoting it.
    violations: list[ForbiddenViolation] = []
    for item in ai_items:
        for concept in forbidden:
            if _promotes_forbidden(item.normalized_body, concept):
                violations.append(
                    ForbiddenViolation(
                        forbidden_key=concept.key,
                        artifact_id=item.artifact_id,
                        category=item.category,
                        text=item.body,
                    )
                )
    return violations


def _promotes_forbidden(text: str, concept: ForbiddenConcept) -> bool:
    """True when the artifact adopts the concept, not when it rejects it."""
    keywords = [normalize_text(keyword) for keyword in concept.keywords if keyword.strip()]
    if not keywords or not _contains_phrase(text, keywords[0]):
        return False
    extra = keywords[1:]
    if extra and not any(_contains_phrase(text, keyword) for keyword in extra):
        return False
    if _signals_rejection(text):
        return False
    return _signals_promotion(text)


def _signals_rejection(text: str) -> bool:
    return any(marker in text for marker in _REJECTION_MARKERS)


def _signals_promotion(text: str) -> bool:
    return any(cue in text for cue in _PROMOTION_CUES)
