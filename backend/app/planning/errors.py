class PlanningError(Exception):
    """Base error for implementation-plan failures."""


class PlanValidationError(PlanningError):
    """Raised when LLM output cannot be turned into a valid ImplementationPlan."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail
