from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.domain.enums import Priority, Severity
from app.domain.ids import (
    DEC_PREFIX,
    OQ_PREFIX,
    PLAN_PREFIX,
    REQ_PREFIX,
    RSK_PREFIX,
    STEP_PREFIX,
    TSK_PREFIX,
    id_pattern,
)

DecisionId = Annotated[str, StringConstraints(pattern=id_pattern(DEC_PREFIX))]
RequirementId = Annotated[str, StringConstraints(pattern=id_pattern(REQ_PREFIX))]
TaskId = Annotated[str, StringConstraints(pattern=id_pattern(TSK_PREFIX))]
RiskId = Annotated[str, StringConstraints(pattern=id_pattern(RSK_PREFIX))]
OpenQuestionId = Annotated[str, StringConstraints(pattern=id_pattern(OQ_PREFIX))]
PlanId = Annotated[str, StringConstraints(pattern=id_pattern(PLAN_PREFIX))]
StepId = Annotated[str, StringConstraints(pattern=id_pattern(STEP_PREFIX))]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _unique_relationship_ids(ids: list[str], *, field: str) -> list[str]:
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate {field}: {', '.join(duplicates)}")
    return ids


def _known_relationship_ids(ids: list[str], allowed: set[str], *, field: str) -> None:
    unknown = sorted({item_id for item_id in ids if item_id not in allowed})
    if unknown:
        raise ValueError(f"Unknown {field}: {', '.join(unknown)}")


class SourceReference(DomainModel):
    excerpt: NonEmptyString


class Decision(DomainModel):
    id: DecisionId
    statement: NonEmptyString
    confidence: Confidence
    source_reference: SourceReference


class Requirement(DomainModel):
    id: RequirementId
    statement: NonEmptyString
    confidence: Confidence
    source_reference: SourceReference
    related_decision_ids: list[DecisionId] = Field(default_factory=list)
    related_risk_ids: list[RiskId] = Field(default_factory=list)

    @field_validator("related_decision_ids", "related_risk_ids")
    @classmethod
    def relationship_ids_must_be_unique(
        cls, value: list[str], info: ValidationInfo
    ) -> list[str]:
        return _unique_relationship_ids(value, field=str(info.field_name))


class Task(DomainModel):
    id: TaskId
    title: NonEmptyString
    description: NonEmptyString
    priority: Priority
    acceptance_criteria: list[NonEmptyString] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)
    related_requirement_ids: list[RequirementId] = Field(default_factory=list)

    @field_validator("related_requirement_ids")
    @classmethod
    def relationship_ids_must_be_unique(
        cls, value: list[str], info: ValidationInfo
    ) -> list[str]:
        return _unique_relationship_ids(value, field=str(info.field_name))


class Risk(DomainModel):
    id: RiskId
    description: NonEmptyString
    severity: Severity
    source_reference: SourceReference
    related_requirement_ids: list[RequirementId] = Field(default_factory=list)

    @field_validator("related_requirement_ids")
    @classmethod
    def relationship_ids_must_be_unique(
        cls, value: list[str], info: ValidationInfo
    ) -> list[str]:
        return _unique_relationship_ids(value, field=str(info.field_name))


class OpenQuestion(DomainModel):
    id: OpenQuestionId
    question: NonEmptyString
    context: NonEmptyString
    source_reference: SourceReference
    related_requirement_ids: list[RequirementId] = Field(default_factory=list)

    @field_validator("related_requirement_ids")
    @classmethod
    def relationship_ids_must_be_unique(
        cls, value: list[str], info: ValidationInfo
    ) -> list[str]:
        return _unique_relationship_ids(value, field=str(info.field_name))


class MeetingAnalysis(DomainModel):
    decisions: list[Decision] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_must_be_unique(self) -> "MeetingAnalysis":
        ids = [
            item.id
            for collection in (
                self.decisions,
                self.requirements,
                self.tasks,
                self.risks,
                self.open_questions,
            )
            for item in collection
        ]
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate item IDs: {', '.join(duplicates)}")
        return self

    @model_validator(mode="after")
    def relationships_must_point_at_existing_ids(self) -> "MeetingAnalysis":
        decision_ids = {item.id for item in self.decisions}
        requirement_ids = {item.id for item in self.requirements}
        risk_ids = {item.id for item in self.risks}
        for item in self.requirements:
            _known_relationship_ids(
                item.related_decision_ids,
                decision_ids,
                field="related_decision_ids",
            )
            _known_relationship_ids(
                item.related_risk_ids,
                risk_ids,
                field="related_risk_ids",
            )
        for item in self.tasks:
            _known_relationship_ids(
                item.related_requirement_ids,
                requirement_ids,
                field="related_requirement_ids",
            )
        for item in self.risks:
            _known_relationship_ids(
                item.related_requirement_ids,
                requirement_ids,
                field="related_requirement_ids",
            )
        for item in self.open_questions:
            _known_relationship_ids(
                item.related_requirement_ids,
                requirement_ids,
                field="related_requirement_ids",
            )
        return self


class ImplementationPlanStep(DomainModel):
    id: StepId
    title: NonEmptyString
    description: NonEmptyString
    related_requirement_ids: list[RequirementId] = Field(default_factory=list)
    related_task_ids: list[TaskId] = Field(default_factory=list)
    evidence: list[SourceReference] = Field(min_length=1)

    @field_validator("related_requirement_ids", "related_task_ids")
    @classmethod
    def relationship_ids_must_be_unique(
        cls, value: list[str], info: ValidationInfo
    ) -> list[str]:
        return _unique_relationship_ids(value, field=str(info.field_name))


class ImplementationPlan(DomainModel):
    id: PlanId
    title: NonEmptyString
    summary: NonEmptyString
    steps: list[ImplementationPlanStep] = Field(default_factory=list)
    acceptance_criteria: list[NonEmptyString] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_must_be_unique(self) -> "ImplementationPlan":
        step_ids = [step.id for step in self.steps]
        duplicates = sorted({item_id for item_id in step_ids if step_ids.count(item_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate step IDs: {', '.join(duplicates)}")
        return self
