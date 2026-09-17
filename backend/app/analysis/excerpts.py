import re

_PHRASE_ALIASES: tuple[tuple[str, str], ...] = (
    ("source of truth", "source_of_truth"),
    ("authoritative", "source_of_truth"),
)

_TOKEN_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"db", "database"}),
    frozenset({"postgres", "postgresql"}),
    frozenset({"webhook", "webhooks"}),
    frozenset({"idempotency", "idempotent"}),
    frozenset({"async", "asynchronous"}),
)

# Function words, hedges, and generic evidence-speak. Domain terms stay
# meaningful (stripe, webhook, database, postgres, pending, and so on).
_WEAK_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "will",
        "must",
        "should",
        "would",
        "could",
        "may",
        "might",
        "can",
        "shall",
        "do",
        "does",
        "did",
        "to",
        "of",
        "and",
        "or",
        "but",
        "if",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "we",
        "our",
        "they",
        "their",
        "them",
        "not",
        "no",
        "also",
        "than",
        "then",
        "so",
        "into",
        "about",
        "use",
        "using",
        "system",
        "payment",
        "payments",
        "request",
        "requests",
        "one",
        "ones",
        "same",
        "concern",
        "concerns",
        "concerned",
        "key",
        "keys",
        "different",
        "behavior",
        "behaviour",
        "behaviors",
        "behaviours",
        "body",
        "bodies",
        "cause",
        "causes",
        "causing",
        "inconsistent",
        "maybe",
        "perhaps",
        "please",
        "there",
        "here",
        "any",
        "some",
        "other",
        "when",
        "which",
        "who",
        "what",
        "how",
        "why",
        "just",
        "still",
        "even",
        "only",
        "has",
        "have",
        "had",
        "get",
        "gets",
        "got",
    }
)


def excerpt_supported_by_transcript(excerpt: str, transcript: str) -> bool:
    """True when excerpt appears in the transcript, ignoring case and extra spaces."""
    if excerpt in transcript:
        return True
    transcript_lower = transcript.lower()
    excerpt_lower = excerpt.lower()
    if excerpt_lower in transcript_lower:
        return True
    return _normalize_whitespace(excerpt_lower) in _normalize_whitespace(transcript_lower)


def excerpt_supports_claim(claim: str, excerpt: str) -> bool:
    """True when the excerpt has enough distinctive lexical overlap to support the claim.

    Conservatively keeps short or generic claims that cannot be judged.
    Generic evidence-speak (concern, key, behavior, and similar) never counts.
    """
    claim_norm = _normalize_support_text(claim)
    excerpt_norm = _normalize_support_text(excerpt)
    claim_tokens = _meaningful_tokens(claim_norm)
    excerpt_tokens = _meaningful_tokens(excerpt_norm)
    overlap = _expanded_token_set(claim_tokens) & _expanded_token_set(excerpt_tokens)

    if _has_strong_phrase_match(claim_norm, excerpt_norm):
        return True
    if len(claim_tokens) < 2:
        return True
    return len(overlap) >= 2


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _normalize_support_text(value: str) -> str:
    text = value.lower().replace("/", " ")
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = _normalize_whitespace(text)
    for phrase, canonical in _PHRASE_ALIASES:
        text = text.replace(phrase, canonical)
    return text


def _meaningful_tokens(normalized: str) -> list[str]:
    tokens: list[str] = []
    for token in normalized.split():
        if token in _WEAK_WORDS or len(token) < 2:
            continue
        tokens.append(token)
    return tokens


def _expanded_token_set(tokens: list[str]) -> set[str]:
    expanded: set[str] = set()
    for token in tokens:
        for form in _plural_forms(token):
            expanded.update(_alias_group(form))
    return expanded


def _plural_forms(token: str) -> set[str]:
    forms = {token}
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        forms.add(token[:-1])
    else:
        forms.add(token + "s")
    return forms


def _alias_group(token: str) -> frozenset[str]:
    for group in _TOKEN_ALIAS_GROUPS:
        if token in group:
            return group
    return frozenset({token})


def _has_strong_phrase_match(claim_norm: str, excerpt_norm: str) -> bool:
    tokens = claim_norm.split()
    padded_excerpt = f" {excerpt_norm} "
    for index in range(len(tokens) - 1):
        left, right = tokens[index], tokens[index + 1]
        if left in _WEAK_WORDS or right in _WEAK_WORDS:
            continue
        if len(left) < 2 or len(right) < 2:
            continue
        if f" {left} {right} " in padded_excerpt:
            return True
    return False
