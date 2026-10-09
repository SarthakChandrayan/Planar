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


_PREFERENCE = re.compile(r"\b(?:i|we)(?:'d| would) rather\b|\b(?:i|we) prefer\b", re.IGNORECASE)


def is_hedged(text: str) -> bool:
    """True when a line states an estimate, option or preference, not an obligation."""
    lowered = text.lower()
    words = set(re.findall(r"[a-z']+", lowered))
    if words & _FIRM or any(phrase in lowered for phrase in _FIRM_PHRASES):
        return False
    return bool(words & _HEDGES) or bool(_PREFERENCE.search(text))


_MONTHS = frozenset(
    """january february march april may june july august september october
    november december jan feb mar apr jun jul aug sep sept oct nov dec monday
    tuesday wednesday thursday friday saturday sunday""".split()
)


_LIST_NUMBER = re.compile(r"^[ \t]*(?:#+[ \t]*)?\d+[.)][ \t]+", re.MULTILINE)


def facts(text: str) -> set[str]:
    """The checkable specifics in a text: numbers and calendar words.

    "Launch ₹2,499 on November 4" -> {"2499", "november", "4"}. Used to make
    sure model-written text adds no number or date the record lacks.
    List and section numbering ("## 5. Retry Strategy", "5. Temporary
    failures ...") is not a fact anyone stated, so it is ignored.
    """
    lowered = _LIST_NUMBER.sub("", text.lower())
    numbers = {
        n.replace(",", "")
        for n in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![a-z])", lowered)
    }
    words = set(re.findall(r"[a-z]+", lowered)) & _MONTHS
    # "may" is usually the verb, not the month.
    words.discard("may")
    return numbers | words


def adds_facts(text: str, source: str) -> set[str]:
    """Numbers or dates in ``text`` that ``source`` does not contain."""
    return facts(text) - facts(source)


def word_set(text: str) -> set[str]:
    """Distinctive words of a text (no stopwords, plurals folded)."""
    return _expand(_tokens(text))


_PRESENT_PHRASES = ("currently", "presently", "at present", "right now", "at the moment")


def describes_present(text: str) -> bool:
    """True when a line describes how things are now, not what must be."""
    lowered = text.lower()
    if not any(phrase in lowered for phrase in _PRESENT_PHRASES):
        return False
    words = set(re.findall(r"[a-z']+", lowered))
    return not (words & _FIRM or any(phrase in lowered for phrase in _FIRM_PHRASES))


_NUMBER_QUALIFIER = re.compile(
    r"\b(approximately|about|around|roughly|nearly|almost|up to|at least|at most|"
    r"more than|less than|fewer than|over|under)\s+([₹$€£]?\d[\d,.]*)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![\w.])([₹$€£]?)(\d[\d,.]*)")
_QUALIFIER_WORDS = {
    "approximately", "about", "around", "roughly", "nearly", "almost", "up", "at",
    "more", "less", "fewer", "over", "under", "~",
}
_TIME_QUALIFIERS = ("initially", "eventually", "temporarily")
_LOWER_FIRST = frozenset("the a an this these those all each every any some".split())


def restore_qualifiers(claim: str, evidence: str) -> str:
    """Put back qualifiers the claim dropped from its evidence.

    "could reach 72%" from "reaches approximately 72%" -> "could reach
    approximately 72%"; "Kafka is used for X" from "Kafka should initially be
    introduced for X" -> "Initially, Kafka is used for X".
    """
    qualified = {}
    for match in _NUMBER_QUALIFIER.finditer(evidence):
        number = re.sub(r"[₹$€£]", "", match.group(2)).rstrip(".,")
        qualified.setdefault(number, match.group(1).lower())

    def fix_number(match: re.Match[str]) -> str:
        number = match.group(2).rstrip(".,")
        qualifier = qualified.get(number)
        if qualifier is None:
            return match.group(0)
        before = claim[: match.start()].split()
        if before and before[-1].lower().strip("(") in _QUALIFIER_WORDS:
            return match.group(0)
        if len(before) >= 2 and " ".join(before[-2:]).lower() in ("up to", "at least", "at most", "more than", "less than", "fewer than"):
            return match.group(0)
        return f"{qualifier} {match.group(0)}"

    claim = _NUMBER.sub(fix_number, claim)

    lowered_claim = claim.lower()
    for word in _TIME_QUALIFIERS:
        if re.search(rf"\b{word}\b(?!\s+consistent)", evidence, re.IGNORECASE) and word not in lowered_claim:
            if coverage(claim, evidence) < 0.5:
                continue  # the evidence says more than this claim is about
            first, _, rest = claim.partition(" ")
            if first.lower() in _LOWER_FIRST:
                first = first.lower()
            claim = f"{word.capitalize()}, {first} {rest}".strip()
            break
    return claim


_MUST = re.compile(r"\bmust\b", re.IGNORECASE)
_SHOULD = re.compile(r"\bshould\b", re.IGNORECASE)


def restore_modality(claim: str, evidence: str) -> str:
    """Keep the speaker's strength: evidence that says "should" stays "should".

    "Services should authenticate with short-lived credentials" must not
    become "Services must authenticate ...".
    """
    claim = _keep_never(claim, evidence)
    evidence = _closest_sentence(claim, evidence)
    if not _MUST.search(claim) or not _SHOULD.search(evidence):
        return claim
    words = set(re.findall(r"[a-z']+", evidence.lower()))
    if words & _FIRM or any(phrase in evidence.lower() for phrase in _FIRM_PHRASES):
        return claim  # the evidence states a real obligation too
    return _MUST.sub(lambda m: "Should" if m.group(0)[0].isupper() else "should", claim)


_NOT_AFTER_MODAL = re.compile(r"\b(must|should|will|shall)\s+not\b", re.IGNORECASE)


def _closest_sentence(claim: str, evidence: str) -> str:
    """The evidence sentence the claim is about.

    "Default partitioning should use order_id. If a consumer needs stronger
    ordering, it needs to solve that itself": the "needs to" belongs to the
    second sentence and must not make the first one a "must".
    """
    sentences = [s for s in re.split(r"(?<=[.!?;])\s+|\s+…\s+", evidence) if s.strip()]
    if len(sentences) < 2:
        return evidence
    closest = max(sentences, key=lambda s: coverage(claim, s))
    lowered = closest.lower()
    has_modal = _SHOULD.search(closest) or set(re.findall(r"[a-z']+", lowered)) & _FIRM or any(
        phrase in lowered for phrase in _FIRM_PHRASES
    )
    # A sentence with no modal verb says nothing about strength: judge the whole.
    return closest if has_modal else evidence


def _keep_never(claim: str, evidence: str) -> str:
    """ "must never" in the evidence stays "must never", not "must not". """
    if not re.search(r"\bnever\b", evidence, re.IGNORECASE) or re.search(r"\bnever\b", claim, re.IGNORECASE):
        return claim
    return _NOT_AFTER_MODAL.sub(lambda m: f"{m.group(1)} never", claim, count=1)


_NEGATIONS = frozenset(
    """not no never without lacks lack lacking missing absent cannot isn't wasn't
    aren't weren't hasn't haven't hadn't doesn't don't didn't can't won't""".split()
)
# A negative stated as present fact: "was not yet enabled", "is missing", "lacks".
# Modal negatives ("could not", "may not") are possibilities, which is what a
# risk is, so they don't count.
_STATE_NEGATIVE = re.compile(
    r"\b(?:not yet|lacks?|lacking|missing|absent)\b"
    r"|\b(?:is|are|was|were|has|have|had|does|do|did)(?:\s+\w+)?\s+not\b"
    r"|\b(?:isn't|aren't|wasn't|weren't|hasn't|haven't|hadn't|doesn't|don't|didn't)\b",
    re.IGNORECASE,
)
# ...unless it sits in a condition: "duplicates if retries are not handled".
_CONDITION = re.compile(r"\b(?:if|unless|when|whenever|in case)\b", re.IGNORECASE)


def asserts_unstated_negative(claim: str, evidence: str) -> bool:
    """The claim states as fact that something is NOT so; the evidence never says that.

    "Encryption at rest was not yet enabled" from "Arjun said it should be
    enabled" turns a recommendation into a claim about the current state.
    """
    for match in _STATE_NEGATIVE.finditer(claim):
        clause = re.split(r"[,;:]", claim[: match.start()])[-1]
        if _CONDITION.search(clause):
            continue
        evidence_words = set(re.findall(r"[a-z']+", evidence.lower()))
        if not (evidence_words & _NEGATIONS or "n't" in evidence.lower()):
            return True
    return False


_QUESTION = re.compile(r"\?\s*$|\basked (?:whether|if|how|what|why)\b|\bwondered\b", re.IGNORECASE)
_AFFIRMS = re.compile(
    r"\b(acknowledged|agreed|confirmed|yes|true|correct|right|could|might|would|will|possible|likely)\b",
    re.IGNORECASE,
)


_UNRESOLVED = re.compile(
    r"\b(?:needs? to (?:determine|decide|confirm|define|agree on|work out)"
    r"|(?:has|have) not (?:yet )?(?:been )?(?:decided|determined|finalized|resolved|agreed)"
    r"|not (?:yet )?(?:been )?(?:decided|determined|finalized|resolved)"
    r"|remains? (?:unresolved|open|undecided)|undecided|to be (?:decided|determined|confirmed)"
    r"|remains? to be (?:defined|decided|determined|finalized|confirmed)"
    r"|still (?:open|needs? to be (?:finalized|defined|decided|determined|confirmed))"
    r"|open questions?|unresolved|will determine whether|^not yet"
    r"|tbd)\b",
    re.IGNORECASE,
)


def is_unresolved(text: str) -> bool:
    """A line that leaves something open ("the team needs to determine X")."""
    return bool(_UNRESOLVED.search(text))


_RULE = re.compile(
    r"\b(?:must|required|requires?|needs?|has to|have to|gate)\b"
    r"|\b(?:no|not|never)\b[^.]*\buntil\b|n't\b[^.]*\buntil\b",
    re.IGNORECASE,
)
_GATE = re.compile(r"\b(?:no|not|never)\b[^.]*\buntil\b|n't\b[^.]*\buntil\b", re.IGNORECASE)
_COMMITMENT = re.compile(r"(?:^|[.!?]\s+)(?:I|we)(?:'ll| will)\b", re.IGNORECASE)


def is_gate(text: str) -> bool:
    """A constraint on timing ("no production schema change until X")."""
    return bool(_GATE.search(text))


def is_commitment(text: str) -> bool:
    """Someone taking on work ("I'll document the requirements")."""
    return bool(_COMMITMENT.search(text.strip()))
_CONCERN = re.compile(
    r"\b(?:could|might|may|would|risks?|risky|concerns?|concerned|worr\w*|warn\w*|fail\w*"
    r"|delay\w*|issues?|problems?|unstable|instability|danger\w*|afraid|exposure|exposed?"
    r"|lag|load|slow\w*|break\w*|lose|losing|loss)\b",
    re.IGNORECASE,
)


def states_rule_without_concern(text: str) -> bool:
    """A rule ("the review must be completed before X") with no concern voiced.

    A risk built on it ("if the review is not completed, Y") invents Y.
    """
    return bool(_RULE.search(text)) and not _CONCERN.search(text)


_ONGOING = re.compile(
    r"\b(?:is|are)\s+(?:already\s+)?(?:causing|contributing to|leading to|creating|resulting in)\b",
    re.IGNORECASE,
)
_POSSIBLE = re.compile(
    r"\b(?:could|might|may|can|would)\s+(?:cause|contribute to|lead to|create|result in)\b",
    re.IGNORECASE,
)


def restore_present(claim: str, evidence: str) -> str:
    """A problem that is already happening stays present, not "could".

    "Inconsistent policies are contributing to cascading failures" must not
    become "Inconsistent policies could cause cascading failures".
    """
    ongoing = _ONGOING.search(evidence)
    if ongoing is None or _ONGOING.search(claim):
        return claim
    return _POSSIBLE.sub(ongoing.group(0).lower(), claim, count=1)


_QUESTION_START = re.compile(
    r"^(?:should|is|are|was|were|does|do|did|can|could|will|would|what|how|when|where|which|who|why|whether)\b",
    re.IGNORECASE,
)


def as_question(text: str) -> str:
    """ "Should Redis be introduced." reads as a question, so it ends with "?"."""
    text = text.strip()
    if _QUESTION_START.match(text) and not text.endswith("?"):
        return text.rstrip(".!") + "?"
    return text


def is_question(text: str) -> bool:
    return bool(_QUESTION.search(text.strip()))


def affirms(text: str) -> bool:
    """A reply that confirms what was asked ("Mehul acknowledged that it could")."""
    return bool(_AFFIRMS.search(text))


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
    # "retries"/"retried" -> "retry", "policies" -> "policy"
    if len(token) > 4 and token.endswith(("ies", "ied")):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token
