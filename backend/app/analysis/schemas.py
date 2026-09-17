from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Priority, Severity
from app.domain.models import NonEmptyString


class ExtractionModel(BaseModel):
    """LLM content schema. IDs are assigned later in application code."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ExtractedSourceReference(ExtractionModel):
    excerpt: NonEmptyString


class ExtractedDecision(ExtractionModel):
    statement: NonEmptyString
    confidence: float = Field(ge=0.0, le=1.0)
    source_reference: ExtractedSourceReference


class ExtractedRequirement(ExtractionModel):
    statement: NonEmptyString
    confidence: float = Field(ge=0.0, le=1.0)
    source_reference: ExtractedSourceReference


class ExtractedTask(ExtractionModel):
    title: NonEmptyString
    description: NonEmptyString
    priority: Priority
    acceptance_criteria: list[NonEmptyString] = Field(default_factory=list)
    source_references: list[ExtractedSourceReference] = Field(min_length=1)


class ExtractedRisk(ExtractionModel):
    description: NonEmptyString
    severity: Severity
    source_reference: ExtractedSourceReference


class ExtractedOpenQuestion(ExtractionModel):
    question: NonEmptyString
    context: NonEmptyString
    source_reference: ExtractedSourceReference


class ExtractedMeetingAnalysis(ExtractionModel):
    decisions: list[ExtractedDecision] = Field(default_factory=list)
    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    tasks: list[ExtractedTask] = Field(default_factory=list)
    risks: list[ExtractedRisk] = Field(default_factory=list)
    open_questions: list[ExtractedOpenQuestion] = Field(default_factory=list)
