"""One place that maps internal exceptions to HTTP status + user-facing text.

Used by the API exception handlers and by background runs, so a failed run
shows the same message the synchronous endpoint would have returned.
"""

from app.analysis import (
    AnalysisValidationError,
    EmptyTranscriptError,
    TranscriptTooLongError,
)
from app.llm import (
    LLMHTTPError,
    LLMProviderError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.planning import PlanValidationError

HANDLED_ERRORS: tuple[type[Exception], ...] = (
    LLMUnavailableError,
    LLMTimeoutError,
    LLMHTTPError,
    LLMResponseError,
    LLMProviderError,
    EmptyTranscriptError,
    TranscriptTooLongError,
    AnalysisValidationError,
    PlanValidationError,
)


def describe_error(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, LLMUnavailableError):
        return 503, str(exc)
    if isinstance(exc, LLMTimeoutError):
        return 504, (
            f"{exc} The model stopped responding; on a slow machine try a "
            "shorter transcript or raise OLLAMA_TIMEOUT_SECONDS."
        )
    if isinstance(exc, (LLMHTTPError, LLMResponseError, LLMProviderError)):
        return 502, str(exc)
    if isinstance(exc, EmptyTranscriptError):
        return 422, str(exc)
    if isinstance(exc, TranscriptTooLongError):
        return 413, str(exc)
    if isinstance(exc, AnalysisValidationError):
        return 502, "The language model returned invalid analysis output."
    if isinstance(exc, PlanValidationError):
        return 502, "The language model returned invalid implementation plan output."
    return 500, "Unexpected server error."


def error_message(exc: Exception) -> str:
    return describe_error(exc)[1]
