"""Progress reporting for long-running LLM work."""

from typing import Protocol


class Progress(Protocol):
    def stage(self, label: str, step: int, total: int) -> None:
        """A new stage started. ``step`` is 1-based."""

    def tokens(self, count: int) -> None:
        """Running count of tokens generated in the current stage. May raise to cancel."""


class NullProgress:
    def stage(self, label: str, step: int, total: int) -> None:
        return None

    def tokens(self, count: int) -> None:
        return None
