import json

from app.domain.models import MeetingAnalysis

IMPLEMENTATION_PLAN_INSTRUCTIONS = """
You turn a validated engineering record into an implementation plan.

Return ONE JSON object. No markdown. No commentary. No IDs.
The application assigns plan and step IDs.

The JSON must use exactly these keys:
{
  "title": "",
  "summary": "",
  "steps": [],
  "acceptance_criteria": []
}

Do not include id fields. Do not include risks or open_questions; the
application copies those from the engineering record.

GOAL
Organize the supplied engineering record into concrete implementation
steps. Elaborate work that is already decided or required. Do not invent
architecture, products, or requirements that are not in the record.

CONSTRAINTS
- Decisions in the record are constraints. Honor them. Do not contradict them.
- Requirements become implementation needs.
- Tasks become known/assigned work. Preserve that work; do not drop it
  merely because you grouped other steps.
- Do not present an idea as an established decision if it is not in the record.
- If the record says Postgres is the source of truth, you may say
  "Persist idempotency records in Postgres."
- You must NOT invent alternatives such as Redis, Kafka, extra caches,
  new services, or other stack choices that the record did not accept.

TRACEABILITY
Each step must use:
- "title": short implementation action
- "description": what to build, constrained by the record
- "related_requirement_ids": IDs copied from the record (for example REQ-001)
- "related_task_ids": IDs copied from the record (for example TSK-001)
- "evidence": [{ "excerpt": "..." }] copied verbatim from the record's
  source_reference / source_references excerpts

Only cite IDs that appear in the engineering record.
Only copy evidence excerpts that already exist in the record.
A step may relate to multiple requirements and tasks.
If the record has no requirements or tasks, return an empty steps array
rather than inventing work.

ACCEPTANCE CRITERIA
List measurable done-when conditions grounded in the record. Prefer
criteria already stated on tasks.

STEP SHAPE
{ "title": "...", "description": "...", "related_requirement_ids": ["REQ-001"],
  "related_task_ids": ["TSK-001"], "evidence": [{ "excerpt": "..." }] }
""".strip()


def build_implementation_plan_prompt(analysis: MeetingAnalysis) -> str:
    record = json.dumps(analysis.model_dump(mode="json"), indent=2)
    return (
        f"{IMPLEMENTATION_PLAN_INSTRUCTIONS}\n\n"
        f"ENGINEERING RECORD JSON:\n{record}"
    )
