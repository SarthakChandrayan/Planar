from pydantic import BaseModel, Field, field_validator

from app.domain import MeetingAnalysis


class AnalyzeMeetingRequest(BaseModel):
    transcript: str = Field(..., min_length=1)

    @field_validator("transcript")
    @classmethod
    def transcript_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("transcript must not be empty")
        return stripped


class CreateImplementationPlanRequest(BaseModel):
    analysis: MeetingAnalysis
    title: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
