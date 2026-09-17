from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.analysis import AnalysisValidationError, EmptyTranscriptError
from app.api import meetings_router
from app.config import Settings
from app.dependencies import get_llm_provider, get_settings
from app.llm import (
    LLMHTTPError,
    LLMProvider,
    LLMProviderError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.planning import PlanValidationError

DEV_LLM_PING_PROMPT = "Explain what an API is in one sentence."


class HealthResponse(BaseModel):
    status: str


class LLMPingResponse(BaseModel):
    model: str
    prompt: str
    response: str


app = FastAPI(title="SpecForge")
app.include_router(meetings_router)


@app.exception_handler(LLMUnavailableError)
def llm_unavailable_handler(
    _request: Request, exc: LLMUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(LLMTimeoutError)
def llm_timeout_handler(_request: Request, exc: LLMTimeoutError) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": str(exc)})


@app.exception_handler(LLMHTTPError)
def llm_http_handler(_request: Request, exc: LLMHTTPError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(LLMResponseError)
def llm_response_handler(_request: Request, exc: LLMResponseError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(LLMProviderError)
def llm_provider_handler(_request: Request, exc: LLMProviderError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(EmptyTranscriptError)
def empty_transcript_handler(
    _request: Request, exc: EmptyTranscriptError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(AnalysisValidationError)
def analysis_validation_handler(
    _request: Request, _exc: AnalysisValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": "The language model returned invalid analysis output."},
    )


@app.exception_handler(PlanValidationError)
def plan_validation_handler(
    _request: Request, _exc: PlanValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "detail": "The language model returned invalid implementation plan output."
        },
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/dev/llm-ping", response_model=LLMPingResponse)
def llm_ping(
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LLMPingResponse:
    return LLMPingResponse(
        model=settings.ollama_model,
        prompt=DEV_LLM_PING_PROMPT,
        response=provider.generate(DEV_LLM_PING_PROMPT),
    )
