"""Check that cited transcript lines actually support an extracted claim.

Small models cite the wrong line fairly often (usually off by one or two).
The grounder scores the cited lines, looks a few lines either side when the
citation is weak, and rejects claims nothing nearby supports.

Which words count as "distinctive" is learned from the transcript itself:
words on many lines (the meeting's topic, the team's name) carry no signal.
No domain vocabulary is hard-coded.
"""

import re
from dataclasses import dataclass

from app.analysis.transcript import NumberedTranscript, TranscriptLine

_STOPWORDS = frozenset(
    """
    a an the is are was were be been being am will must should would could may
    might can shall do does did done to of and or but if for in on at by with
    from as that this these those it its we our us they their them you your i
    me my he she his her not no also than then so into about up out over under
    there here any some other when which who what how why just still even only
    has have had get gets got let lets going go make makes made need needs
    one all more most very really yeah ok okay right well like think know want
    sure good great fine yes thing things something way lot bit maybe perhaps
    please actually basically probably now today agreed agree decision decide
    """.split()
)
_WINDOW = 3
# Fallback search over the whole transcript must cover this share of the
# claim's distinctive words on a single line.
_GLOBAL_MIN_COVERAGE = 0.5
# Lines longer than this are trimmed to the sentences that support the claim.
_EXCERPT_TRIM_CHARS = 220
_MAX_EXCERPT_SENTENCES = 2
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_MAX_EVIDENCE_LINES = 3
_COMMON_LINE_FRACTION = 0.15
_MIN_COMMON_LINES = 4


@dataclass(frozen=True)
class Grounding:
    lines: tuple[TranscriptLine, ...]
    score: float
    reanchored: bool

    @property
    def confidence(self) -> float:
        """Evidence strength in [0, 1]: how well the lines back the claim."""
        base = 0.55 + 0.1 * min(self.score, 4.0)
        if self.reanchored:
            base -= 0.1
        return round(max(0.3, min(base, 0.95)), 2)


class Grounder:
    def __init__(self, transcript: NumberedTranscript) -> None:
        self._transcript = transcript
        self._line_tokens = {
            line.number: _expand(_tokens(line.content)) for line in transcript.lines
        }
        frequency: dict[str, int] = {}
        for tokens in self._line_tokens.values():
            for token in tokens:
                frequency[token] = frequency.get(token, 0) + 1
        limit = max(_MIN_COMMON_LINES, int(len(self._line_tokens) * _COMMON_LINE_FRACTION))
        self._common = frozenset(tok for tok, count in frequency.items() if count > limit)

    def ground(self, claim: str, cited: list[int]) -> Grounding | None:
        claim_tokens = _expand(_tokens(claim)) - self._common
        if not claim_tokens:
            return None
        valid = sorted({n for n in cited if self._transcript.has(n)})

        best = self._best_cited(claim_tokens, valid)
        if best is not None and best[1] >= self._threshold(claim_tokens):
            return Grounding(best[0], best[1], reanchored=False)

        nearby = self._best_nearby(claim_tokens, valid)
        if nearby is not None and nearby[1] >= self._threshold(claim_tokens):
            return Grounding(nearby[0], nearby[1], reanchored=True)

        # Small models sometimes cite a line far from the right one. Accept a
        # line anywhere only if it clearly states most of the claim.
        anywhere = self._best_anywhere(claim_tokens)
        if anywhere is not None:
            return Grounding(anywhere[0], anywhere[1], reanchored=True)
        return None

    def excerpt(self, line: TranscriptLine, claim: str) -> str:
        """The part of a line that supports the claim (whole line if short)."""
        content = line.content
        if len(content) <= _EXCERPT_TRIM_CHARS:
            return content
        claim_tokens = _expand(_tokens(claim)) - self._common
        sentences = [s for s in _SENTENCE_SPLIT.split(content) if s.strip()]
        scored = [
            (len(claim_tokens & _expand(_tokens(sentence))), index)
            for index, sentence in enumerate(sentences)
        ]
        best = sorted((item for item in scored if item[0] > 0), reverse=True)
        keep = sorted(index for _, index in best[:_MAX_EXCERPT_SENTENCES])
        if not keep:
            return content
        parts = []
        for position, index in enumerate(keep):
            if position and index != keep[position - 1] + 1:
                parts.append("…")
            parts.append(sentences[index])
        prefix = "… " if keep[0] > 0 else ""
        suffix = " …" if keep[-1] < len(sentences) - 1 else ""
        return prefix + " ".join(parts) + suffix

    def _threshold(self, claim_tokens: set[str]) -> float:
        # Short claims cannot be expected to share many words with a line.
        return 1.0 if len(claim_tokens) <= 2 else 2.0

    def _score(self, claim_tokens: set[str], numbers: list[int]) -> float:
        line_tokens: set[str] = set()
        for number in numbers:
            line_tokens |= self._line_tokens.get(number, set())
        return float(len(claim_tokens & line_tokens))

    def _best_cited(
        self, claim_tokens: set[str], valid: list[int]
    ) -> tuple[tuple[TranscriptLine, ...], float] | None:
        if not valid:
            return None
        ranked = sorted(
            valid, key=lambda n: self._score(claim_tokens, [n]), reverse=True
        )
        # Evidence is one passage: keep only cited lines next to the best one.
        anchor = ranked[0]
        near = [n for n in ranked if abs(n - anchor) <= _MAX_EVIDENCE_LINES - 1]
        chosen = sorted(near[:_MAX_EVIDENCE_LINES])
        # Drop cited lines that add nothing.
        useful = [n for n in chosen if self._score(claim_tokens, [n]) > 0] or chosen[:1]
        return self._lines(useful), self._score(claim_tokens, useful)

    def _best_nearby(
        self, claim_tokens: set[str], valid: list[int]
    ) -> tuple[tuple[TranscriptLine, ...], float] | None:
        candidates: set[int] = set()
        for number in valid:
            for offset in range(-_WINDOW, _WINDOW + 1):
                if self._transcript.has(number + offset):
                    candidates.add(number + offset)
        if not candidates:
            return None
        best = max(sorted(candidates), key=lambda n: self._score(claim_tokens, [n]))
        score = self._score(claim_tokens, [best])
        if score <= 0:
            return None
        return self._lines([best]), score

    def _best_anywhere(
        self, claim_tokens: set[str]
    ) -> tuple[tuple[TranscriptLine, ...], float] | None:
        if not self._line_tokens:
            return None
        best = max(sorted(self._line_tokens), key=lambda n: self._score(claim_tokens, [n]))
        score = self._score(claim_tokens, [best])
        needed = max(self._threshold(claim_tokens), len(claim_tokens) * _GLOBAL_MIN_COVERAGE)
        if score < needed:
            return None
        return self._lines([best]), score

    def _lines(self, numbers: list[int]) -> tuple[TranscriptLine, ...]:
        return tuple(
            line for n in numbers if (line := self._transcript.get(n)) is not None
        )


def text_mentioned(value: str, transcript: str) -> bool:
    """True when a short value (an owner name, a due date) appears in the transcript."""
    words = [w for w in _tokens(value) if len(w) >= 3]
    if not words:
        return False
    haystack = set(_tokens(transcript))
    return any(word in haystack for word in words)


def similarity(left: str, right: str) -> float:
    """Jaccard similarity of distinctive words, for de-duplicating items."""
    a = _expand(_tokens(left))
    b = _expand(_tokens(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def shared_words(left: str, right: str) -> tuple[int, float]:
    """Distinctive words two texts share, and that count over the shorter text.

    Unlike Jaccard, this does not penalise a short decision for being
    compared with a long requirement that restates and extends it.
    """
    a = _expand(_tokens(left))
    b = _expand(_tokens(right))
    if not a or not b:
        return 0, 0.0
    shared = len(a & b)
    return shared, shared / min(len(a), len(b))


def coverage(part: str, whole: str) -> float:
    """Share of ``part``'s distinctive words that also appear in ``whole``."""
    a = _expand(_tokens(part))
    if not a:
        return 0.0
    return len(a & _expand(_tokens(whole))) / len(a)


# Words that mark a statement as an estimate, option or opinion, not a commitment.
_HEDGES = frozenset(
    """
    estimate estimated estimates estimating approximately approx roughly around
    could might may possibly potentially perhaps maybe likely unlikely suggest
    suggested suggests proposed proposes propose considered consider wondered
    guess hope hopefully ideally
    """.split()
)
# Words that mark the statement as a real obligation even if it also hedges.
_FIRM = frozenset("must required require requires mandatory need needs".split())
_FIRM_PHRASES = ("has to", "have to", "will not", "won't", "cannot", "can't")


def is_hedged(text: str) -> bool:
    """True when a line states an estimate or option rather than an obligation."""
    lowered = text.lower()
    words = set(re.findall(r"[a-z']+", lowered))
    if words & _FIRM or any(phrase in lowered for phrase in _FIRM_PHRASES):
        return False
    return bool(words & _HEDGES)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 2 and w not in _STOPWORDS}


def _expand(tokens: set[str]) -> set[str]:
    """Collapse plurals so 'webhooks' matches 'webhook'."""
    out: set[str] = set()
    for token in tokens:
        out.add(_stem(token))
    return out


def _stem(token: str) -> str:
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token
