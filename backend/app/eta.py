"""Time estimates for analysis runs, learned from this machine's past runs.

Each stage's duration is modelled as seconds per 1k transcript tokens in the
chunk it processed. Defaults come from measured runs on a CPU-only laptop;
after a few finished runs the medians of real timings take over, so the
estimate follows whatever hardware and settings are actually in use. While a
run is going, a speed factor (actual vs expected for its finished stages)
corrects the rest of the estimate.
"""

import math
import re
import statistics
from collections.abc import Iterable, Sequence

from pydantic import BaseModel

from app.analysis.transcript import CHARS_PER_TOKEN

PASS_STAGES: tuple[str, ...] = (
    "Decisions",
    "Requirements",
    "Tasks",
    "Risks & open questions",
)
PLAN_STAGE = "Implementation plan"

# Seconds per 1k transcript tokens, measured with qwen3:4b on CPU.
DEFAULT_SECONDS_PER_KTOK: dict[str, float] = {
    "Decisions": 25.0,
    "Requirements": 39.0,
    "Tasks": 53.0,
    "Risks & open questions": 26.0,
    # The second look reuses the cached transcript and writes little.
    "Decisions · second look": 8.0,
    "Requirements · second look": 12.0,
    "Checking decisions": 12.0,
    PLAN_STAGE: 48.0,
}
# Short transcripts still pay fixed costs (model load, instructions, output).
MIN_KTOK = 1.5
HISTORY_RUNS = 10
_SPEED_BOUNDS = (0.3, 3.0)
# Shown while a stage runs over its expected time.
_OVERRUN_FLOOR_SECONDS = 15.0


class StageTiming(BaseModel):
    stage: str
    seconds: float
    kilotokens: float


_PART = re.compile(r"\s·\spart \d+/\d+")


def stage_key(label: str) -> str:
    """'Decisions · part 1/2' -> 'Decisions'; a second look keeps its own key."""
    return _PART.sub("", label).strip()


def chunk_count(transcript_chars: int, chunk_max_tokens: int) -> int:
    tokens = transcript_chars / CHARS_PER_TOKEN
    return max(1, math.ceil(tokens / chunk_max_tokens))


def kilotokens_per_chunk(transcript_chars: int, chunks: int) -> float:
    tokens = transcript_chars / CHARS_PER_TOKEN
    return max(tokens / max(chunks, 1) / 1000, MIN_KTOK)


def stage_sequence(
    chunks: int, include_plan: bool, second_look: bool = True, verify: bool = False
) -> list[str]:
    from app.analysis.analyzer import planned_stages

    stages = [stage_key(label) for label in planned_stages(chunks, second_look, verify)]
    if include_plan:
        stages.append(PLAN_STAGE)
    return stages


class EtaModel:
    def __init__(self, history: Iterable[Sequence[StageTiming]] = ()) -> None:
        rates: dict[str, list[float]] = {}
        runs = 0
        for timings in history:
            runs += 1
            for timing in timings:
                if timing.kilotokens > 0 and timing.seconds > 0:
                    rates.setdefault(timing.stage, []).append(timing.seconds / timing.kilotokens)
        self._rates = {stage: statistics.median(values) for stage, values in rates.items()}
        self.learned_runs = runs

    @property
    def basis(self) -> str:
        return "this machine" if self.learned_runs else "default"

    def expected(self, stage: str, kilotokens: float) -> float:
        rate = self._rates.get(stage, DEFAULT_SECONDS_PER_KTOK.get(stage, 40.0))
        return rate * max(kilotokens, MIN_KTOK)

    def total(
        self, transcript_chars: int, chunk_max_tokens: int, include_plan: bool, second_look: bool = True
    ) -> float:
        chunks = chunk_count(transcript_chars, chunk_max_tokens)
        ktok = kilotokens_per_chunk(transcript_chars, chunks)
        return sum(self.expected(s, ktok) for s in stage_sequence(chunks, include_plan, second_look))

    def remaining(
        self,
        stages: Sequence[str],
        current_index: int,
        elapsed_in_stage: float,
        kilotokens: float,
        done: Sequence[StageTiming],
    ) -> float:
        """Seconds left: rest of the current stage plus all later stages.

        ``current_index`` is 0-based into ``stages``; -1 means not started.
        """
        speed = self.speed_factor(done)
        later = stages[current_index + 1 :]
        left = sum(self.expected(stage, kilotokens) for stage in later) * speed
        if 0 <= current_index < len(stages):
            current = self.expected(stages[current_index], kilotokens) * speed
            left += max(current - elapsed_in_stage, _OVERRUN_FLOOR_SECONDS)
        return left

    def speed_factor(self, done: Sequence[StageTiming]) -> float:
        expected = sum(self.expected(t.stage, t.kilotokens) for t in done)
        actual = sum(t.seconds for t in done)
        if expected <= 0 or actual <= 0:
            return 1.0
        low, high = _SPEED_BOUNDS
        return min(max(actual / expected, low), high)
