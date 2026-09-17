from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import NonEmptyString


class ExtractionModel(BaseModel):
    """LLM content schema. IDs are assigned later in application code."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ExtractedPlanEvidence(ExtractionModel):
    excerpt: NonEmptyString


class ExtractedPlanStep(ExtractionModel):
    title: NonEmptyString
    description: NonEmptyString
    related_requirement_ids: list[str] = Field(default_factory=list)
    related_task_ids: list[str] = Field(default_factory=list)
    evidence: list[ExtractedPlanEvidence] = Field(default_factory=list)


class ExtractedImplementationPlan(ExtractionModel):
    title: NonEmptyString
    summary: NonEmptyString
    steps: list[ExtractedPlanStep] = Field(default_factory=list)
    acceptance_criteria: list[NonEmptyString] = Field(default_factory=list)
