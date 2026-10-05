from pydantic import BaseModel, Field, field_validator

from app.domain import MeetingAnalysis


def _strip_required(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("transcript must not be empty")
    return stripped


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class AnalyzeMeetingRequest(BaseModel):
    transcript: str = Field(..., min_length=1)

    @field_validator("transcript")
    @classmethod
    def transcript_must_not_be_blank(cls, value: str) -> str:
        return _strip_required(value)


class CreateRunRequest(BaseModel):
    transcript: str = Field(..., min_length=1)
    title: str | None = Field(default=None, max_length=200)
    include_plan: bool = True

    @field_validator("transcript")
    @classmethod
    def transcript_must_not_be_blank(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class CreateImplementationPlanRequest(BaseModel):
    analysis: MeetingAnalysis
    title: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        return _strip_optional(value)
