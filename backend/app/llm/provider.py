from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstraction for sending a prompt to a language model."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the generated text."""
