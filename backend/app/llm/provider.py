from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

# Called with the running count of generated tokens. May raise to abort.
TokenCallback = Callable[[int], None]


class LLMProvider(ABC):
    """Abstraction for sending a prompt to a language model."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        on_tokens: TokenCallback | None = None,
    ) -> str:
        """Send a prompt and return the generated text.

        ``schema`` is a JSON schema the output must follow, when the provider
        supports constrained decoding.
        """

    def check_ready(self) -> None:
        """Raise an LLMProviderError if the model cannot serve requests."""
        return None

    def warm_up(self) -> None:
        """Load the model into memory ahead of a request. Best effort."""
        return None
