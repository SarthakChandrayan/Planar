from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.analysis import MeetingAnalyzer
from app.config import Settings
from app.llm.ollama import OllamaProvider
from app.llm.provider import LLMProvider
from app.planning import ImplementationPlanner


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_llm_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LLMProvider:
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        think=settings.ollama_think,
        timeout_seconds=settings.ollama_timeout_seconds,
        num_ctx=settings.ollama_num_ctx,
    )


def get_meeting_analyzer(
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> MeetingAnalyzer:
    return MeetingAnalyzer(llm)


def get_implementation_planner(
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> ImplementationPlanner:
    return ImplementationPlanner(llm)
