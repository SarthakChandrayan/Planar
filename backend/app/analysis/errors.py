class AnalysisError(Exception):
    """Base error for meeting analysis failures."""


class EmptyTranscriptError(AnalysisError):
    """Raised when the transcript is missing or blank."""


class TranscriptTooLongError(AnalysisError):
    """Raised when the transcript exceeds the configured size limit."""


class AnalysisValidationError(AnalysisError):
    """Raised when LLM output cannot be turned into a valid MeetingAnalysis."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail
