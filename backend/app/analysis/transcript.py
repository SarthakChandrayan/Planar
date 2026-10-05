"""Line-numbered view of a transcript.

The model cites line numbers instead of copying quotes: far fewer output
tokens on slow hardware, and evidence is looked up exactly by the backend.

Only non-blank lines are numbered, densely (L1, L2, ...): small models cite
small, gap-free numbers more accurately. ``source_line`` keeps the line's
position in the original text for display.
"""

import re
from dataclasses import dataclass

# "Maya: ...", "Maya (EM): ...", "[00:12:03] Maya: ...", "Maya - ..." is not a speaker.
_SPEAKER = re.compile(
    r"^\s*(?:\[[^\]]{1,20}\]\s*)?"
    r"(?P<name>[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"
    r"(?:\s*\([^)]{0,40}\))?\s*:\s+(?P<text>\S.*)$"
)
# Header keys that look like speakers but are not.
_NOT_SPEAKERS = frozenset(
    {"meeting", "participants", "attendees", "date", "time", "agenda", "notes",
     "summary", "title", "subject", "location", "duration", "action items"}
)
# Rough chars-per-token for English with code-ish terms. Errs on the high side
# for token counts, so chunks stay inside the context window.
CHARS_PER_TOKEN = 3.2


@dataclass(frozen=True)
class TranscriptLine:
    number: int
    source_line: int
    text: str
    speaker: str | None
    content: str


@dataclass(frozen=True)
class TranscriptChunk:
    index: int
    lines: tuple[TranscriptLine, ...]

    @property
    def first(self) -> int:
        return self.lines[0].number

    @property
    def last(self) -> int:
        return self.lines[-1].number

    def render(self) -> str:
        return "\n".join(f"L{line.number}: {line.text}" for line in self.lines)


class NumberedTranscript:
    def __init__(self, transcript: str) -> None:
        self._lines: dict[int, TranscriptLine] = {}
        for source_line, raw in enumerate(transcript.splitlines(), start=1):
            text = " ".join(raw.split())
            if not text:
                continue
            speaker, content = _split_speaker(text)
            number = len(self._lines) + 1
            self._lines[number] = TranscriptLine(number, source_line, text, speaker, content)
        self.text = transcript
        self.speakers = sorted({ln.speaker for ln in self._lines.values() if ln.speaker})

    @property
    def lines(self) -> list[TranscriptLine]:
        return list(self._lines.values())

    def get(self, number: int) -> TranscriptLine | None:
        return self._lines.get(number)

    def has(self, number: int) -> bool:
        return number in self._lines

    def estimated_tokens(self) -> int:
        return estimate_tokens(self.text)

    def chunks(self, max_tokens: int, overlap_lines: int = 8) -> list[TranscriptChunk]:
        """Split into chunks of at most ``max_tokens`` with a small line overlap."""
        lines = self.lines
        if not lines:
            return []
        budget_chars = int(max_tokens * CHARS_PER_TOKEN)
        chunks: list[TranscriptChunk] = []
        start = 0
        while start < len(lines):
            end = start
            size = 0
            while end < len(lines):
                cost = len(lines[end].text) + 8
                if end > start and size + cost > budget_chars:
                    break
                size += cost
                end += 1
            chunks.append(TranscriptChunk(len(chunks), tuple(lines[start:end])))
            if end >= len(lines):
                break
            start = max(end - overlap_lines, start + 1)
        return chunks


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _split_speaker(text: str) -> tuple[str | None, str]:
    match = _SPEAKER.match(text)
    if not match:
        return None, text
    name = match.group("name").strip()
    if name.lower() in _NOT_SPEAKERS:
        return None, text
    return name, match.group("text").strip()
