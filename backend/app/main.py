import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api import meetings_router, runs_router, samples_router
from app.config import Settings
from app.dependencies import (
    build_plan_runner,
    build_runner,
    get_llm_provider,
    get_settings,
    require_dev_endpoints,
)
from app.errors import HANDLED_ERRORS, describe_error, error_message
from app.llm import LLMProvider, LLMProviderError
from app.observability import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    configure_logging,
    current_request_id,
)
from app.runs import RunManager

logger = logging.getLogger(__name__)

DEV_LLM_PING_PROMPT = "Explain what an API is in one sentence."
# Don't ask Ollama to load the model more often than this.
_WARM_UP_INTERVAL_SECONDS = 300.0
_warm_up_lock = threading.Lock()
_last_warm_up = 0.0


def _warm_up_in_background(provider: LLMProvider) -> bool:
    """Start loading the model unless that was asked for recently."""
    global _last_warm_up
    with _warm_up_lock:
        now = time.monotonic()
        if now - _last_warm_up < _WARM_UP_INTERVAL_SECONDS:
            return False
        _last_warm_up = now

    def run() -> None:
        try:
            provider.warm_up()
        except LLMProviderError as exc:
            logger.info("llm_warm_up_skipped reason=%s", exc)

    threading.Thread(target=run, name="llm-warm-up", daemon=True).start()
    return True


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    model: str
    detail: str | None = None


class LLMPingResponse(BaseModel):
    model: str
    prompt: str
    response: str


def _handled_error(_request: Request, exc: Exception) -> JSONResponse:
    status_code, detail = describe_error(exc)
    if status_code >= 500:
        logger.warning("request_failed status=%d error=%s", status_code, exc)
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("request_unhandled_error", exc_info=exc)
    request_id = current_request_id()
    return JSONResponse(
        status_code=500,
        content={"detail": "Unexpected server error.", "request_id": request_id},
        headers={REQUEST_ID_HEADER: request_id},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        manager = RunManager(
            settings.runs_dir,
            build_runner(settings),
            error_message=error_message,
            chunk_max_tokens=settings.chunk_max_tokens,
            plan_runner=build_plan_runner(settings),
            second_look=settings.analysis_second_look,
        )
        manager.start()
        app.state.run_manager = manager
        logger.info(
            "startup model=%s ollama=%s num_ctx=%d runs_dir=%s",
            settings.ollama_model,
            settings.ollama_base_url,
            settings.ollama_num_ctx,
            settings.runs_dir,
        )
        try:
            yield
        finally:
            manager.stop()

    app = FastAPI(title="Planar", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
        )
    for error_type in HANDLED_ERRORS:
        app.add_exception_handler(error_type, _handled_error)
    app.add_exception_handler(Exception, _unhandled_error)

    app.include_router(meetings_router)
    app.include_router(runs_router)
    app.include_router(samples_router)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/health/ready",
        response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse}},
    )
    def ready(
        provider: Annotated[LLMProvider, Depends(get_llm_provider)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> ReadinessResponse | JSONResponse:
        try:
            provider.check_ready()
        except LLMProviderError as exc:
            body = ReadinessResponse(
                status="unavailable", model=settings.ollama_model, detail=str(exc)
            )
            return JSONResponse(status_code=503, content=body.model_dump())
        return ReadinessResponse(status="ok", model=settings.ollama_model)

    @app.post("/api/warmup", status_code=202)
    def warm_up(
        provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    ) -> dict[str, bool]:
        """Load the model while the user is still pasting, so the run starts sooner."""
        return {"started": _warm_up_in_background(provider)}

    @app.get(
        "/dev/llm-ping",
        response_model=LLMPingResponse,
        dependencies=[Depends(require_dev_endpoints)],
    )
    def llm_ping(
        provider: Annotated[LLMProvider, Depends(get_llm_provider)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> LLMPingResponse:
        return LLMPingResponse(
            model=settings.ollama_model,
            prompt=DEV_LLM_PING_PROMPT,
            response=provider.generate(DEV_LLM_PING_PROMPT),
        )

    return app


app = create_app()
