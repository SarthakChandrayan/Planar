"""Per-pass extraction schemas.

Each pass has a Pydantic model (to validate) and a JSON schema (sent to
Ollama's ``format`` so decoding is constrained to that shape). The model
never produces IDs, quotes, or links: it cites line numbers, and the
application assigns IDs and infers links between items.
"""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.domain.enums import Priority, Severity

MAX_ITEMS_PER_PASS = 20
MAX_LINES_PER_ITEM = 2
_PRIORITIES = [item.value for item in Priority]
_SEVERITIES = [item.value for item in Severity]


class ExtractionModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


def _clean_lines(value: object) -> object:
    if isinstance(value, list):
        out: list[int] = []
        for item in value:
            if isinstance(item, str):
                item = item.strip().lstrip("Ll")
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if number > 0 and number not in out:
                out.append(number)
        return out[:MAX_LINES_PER_ITEM]
    return value


LineNumbers = Annotated[list[int], BeforeValidator(_clean_lines)]


class CitedItem(ExtractionModel):
    lines: LineNumbers = Field(default_factory=list)


class ExtractedDecision(CitedItem):
    statement: str = Field(min_length=1)


class ExtractedRequirement(CitedItem):
    statement: str = Field(min_length=1)


class ExtractedTask(CitedItem):
    title: str = Field(min_length=1)
    description: str = ""
    owner: str | None = None
    due: str | None = None
    priority: Priority = Priority.MEDIUM
    acceptance_criteria: list[str] = Field(default_factory=list)

    @field_validator("priority", mode="before")
    @classmethod
    def _priority(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() in _PRIORITIES:
            return value.strip().lower()
        return Priority.MEDIUM


class ExtractedRisk(CitedItem):
    description: str = Field(min_length=1)
    severity: Severity = Severity.MEDIUM

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() in _SEVERITIES:
            return value.strip().lower()
        return Severity.MEDIUM


class ExtractedOpenQuestion(CitedItem):
    question: str = Field(min_length=1)
    context: str = ""


class DecisionsPass(ExtractionModel):
    decisions: list[ExtractedDecision] = Field(default_factory=list)


class RequirementsPass(ExtractionModel):
    requirements: list[ExtractedRequirement] = Field(default_factory=list)


class TasksPass(ExtractionModel):
    tasks: list[ExtractedTask] = Field(default_factory=list)


class RisksQuestionsPass(ExtractionModel):
    risks: list[ExtractedRisk] = Field(default_factory=list)
    open_questions: list[ExtractedOpenQuestion] = Field(default_factory=list)


# ---------------------------------------------------------------- JSON schemas

_STRING = {"type": "string"}
_LINES = {
    "type": "array",
    "items": {"type": "integer"},
    "minItems": 1,
    "maxItems": MAX_LINES_PER_ITEM,
}


def _list_of(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": MAX_ITEMS_PER_PASS,
        "items": {"type": "object", "properties": properties, "required": required},
    }


def _object(**lists: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": lists, "required": list(lists)}


DECISIONS_SCHEMA = _object(
    decisions=_list_of({"statement": _STRING, "lines": _LINES}, ["statement", "lines"])
)
REQUIREMENTS_SCHEMA = _object(
    requirements=_list_of(
        {"statement": _STRING, "lines": _LINES},
        ["statement", "lines"],
    )
)
TASKS_SCHEMA = _object(
    tasks=_list_of(
        {
            "title": _STRING,
            "description": _STRING,
            "owner": _STRING,
            "due": _STRING,
            "priority": {"type": "string", "enum": _PRIORITIES},
            "acceptance_criteria": {
                "type": "array",
                "items": _STRING,
                "maxItems": 3,
            },
            "lines": _LINES,
        },
        [
            "title",
            "description",
            "owner",
            "due",
            "priority",
            "acceptance_criteria",
            "lines",
        ],
    )
)
RISKS_QUESTIONS_SCHEMA = _object(
    risks=_list_of(
        {
            "description": _STRING,
            "severity": {"type": "string", "enum": _SEVERITIES},
            "lines": _LINES,
        },
        ["description", "severity", "lines"],
    ),
    open_questions=_list_of(
        {
            "question": _STRING,
            "context": _STRING,
            "lines": _LINES,
        },
        ["question", "context", "lines"],
    ),
)
