from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _clean_ids(value: object) -> object:
    if isinstance(value, list):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    return value


ItemIds = Annotated[list[str], BeforeValidator(_clean_ids)]


class ExtractionModel(BaseModel):
    """LLM content schema. IDs are assigned later in application code."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ExtractedPlanStep(ExtractionModel):
    title: str = Field(min_length=1)
    description: str = ""
    when: str = ""
    decision_ids: ItemIds = Field(default_factory=list)
    requirement_ids: ItemIds = Field(default_factory=list)
    task_ids: ItemIds = Field(default_factory=list)


class ExtractedOutcome(ExtractionModel):
    text: str = ""
    ids: ItemIds = Field(default_factory=list)


class ExtractedImplementationPlan(ExtractionModel):
    title: str = ""
    summary: str = ""
    steps: list[ExtractedPlanStep] = Field(default_factory=list)
    outcomes: list[ExtractedOutcome] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)


_STRING = {"type": "string"}
_IDS = {"type": "array", "items": {"type": "string"}, "maxItems": 8}

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": _STRING,
        "summary": _STRING,
        "steps": {
            "type": "array",
            "maxItems": 15,
            "items": {
                "type": "object",
                "properties": {
                    "title": _STRING,
                    "description": _STRING,
                    "when": _STRING,
                    "decision_ids": _IDS,
                    "requirement_ids": _IDS,
                    "task_ids": _IDS,
                },
                "required": [
                    "title", "description", "when", "decision_ids", "requirement_ids", "task_ids"
                ],
            },
        },
        "outcomes": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {"text": _STRING, "ids": _IDS},
                "required": ["text", "ids"],
            },
        },
    },
    "required": ["title", "summary", "steps", "outcomes"],
}
