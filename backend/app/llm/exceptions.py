class LLMProviderError(Exception):
    """Base error for LLM provider failures."""


class LLMUnavailableError(LLMProviderError):
    """Raised when the LLM server cannot be reached or the model is missing."""


class LLMTimeoutError(LLMProviderError):
    """Raised when the LLM request times out."""


class LLMHTTPError(LLMProviderError):
    """Raised when the LLM server returns an HTTP error."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMResponseError(LLMProviderError):
    """Raised when the LLM server returns a malformed or unexpected payload."""


class LLMOutputTruncatedError(LLMResponseError):
    """Raised when generation stopped at the output token limit."""
