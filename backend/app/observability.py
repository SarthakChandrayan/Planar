"""Logging setup and per-request context (request ID, access log)."""

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Literal

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
_MAX_INCOMING_REQUEST_ID_CHARS = 128

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_HANDLER_MARKER = "_planar_handler"

access_logger = logging.getLogger("app.access")


def current_request_id() -> str:
    return _request_id.get()


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str, fmt: Literal["text", "json"]) -> None:
    """Attach one handler to the ``app`` logger tree. Safe to call repeatedly."""
    logger = logging.getLogger("app")
    logger.setLevel(level)

    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)

    handler = logging.StreamHandler()
    setattr(handler, _HANDLER_MARKER, True)
    handler.addFilter(_RequestIdFilter())
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
            )
        )
    logger.addHandler(handler)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request ID, echo it in the response, and log one access line."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = (
            incoming[:_MAX_INCOMING_REQUEST_ID_CHARS] if incoming else uuid.uuid4().hex
        )
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            access_logger.info(
                "request_completed method=%s path=%s status=%d duration_ms=%.0f",
                request.method,
                request.url.path,
                status_code,
                (time.perf_counter() - started) * 1000,
            )
            _request_id.reset(token)
