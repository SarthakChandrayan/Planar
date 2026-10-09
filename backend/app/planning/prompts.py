from app.domain.models import MeetingAnalysis

IMPLEMENTATION_PLAN_INSTRUCTIONS = """
TASK: Turn the engineering record above into an implementation plan.

- "title": short name for the plan.
- "summary": 2-3 sentences on what will be built and the key constraints.
- "steps": implementation steps in the order they happen. Each step has a
  short "title", a one-sentence "description" of what to do, "when" it happens, the
  "decision_ids" it applies (DEC-...), and the "requirement_ids" (REQ-...)
  and "task_ids" (TSK-...) it delivers. Put each ID in the matching list.
  Every step must cite at least one ID.
- "when": the timeframe, using only dates and timeframes written in the
  record ("before October 28", "launch week", "first 30 days after launch"),
  or "" if the record gives none.

RULES
- Decisions are constraints: honor them, never contradict them.
- Only cite IDs that appear in the record.
- Do not invent technologies, services, requirements, targets or dates the
  record does not mention.
- Keep qualifiers as written: "approximately 50" stays "approximately 50".
- Return compact JSON on a single line, with no indentation.
""".strip()


def render_record(analysis: MeetingAnalysis) -> str:
    """Compact text form of the record: far fewer tokens than a JSON dump."""
    sections: list[str] = ["ENGINEERING RECORD"]

    def add(heading: str, rows: list[str]) -> None:
        if rows:
            sections.append(f"{heading}:\n" + "\n".join(rows))

    add(
        "DECISIONS (constraints)",
        [f"{d.id}: {d.statement}" for d in analysis.decisions],
    )
    add(
        "REQUIREMENTS",
        [f"{r.id}: {r.statement}" for r in analysis.requirements],
    )
    task_rows = []
    for t in analysis.tasks:
        extras = [f"priority {t.priority.value}"]
        if t.owner:
            extras.append(f"owner {t.owner}")
        if t.due:
            extras.append(f"due {t.due}")
        if t.related_requirement_ids:
            extras.append("for " + ", ".join(t.related_requirement_ids))
        task_rows.append(f"{t.id}: {t.title} — {t.description} ({'; '.join(extras)})")
    add("TASKS", task_rows)
    # Risks and open questions are copied into the plan by the application and
    # never cited by steps; leaving them out shortens the prompt on slow CPUs.
    return "\n\n".join(sections)


def build_implementation_plan_prompt(analysis: MeetingAnalysis) -> str:
    return f"{render_record(analysis)}\n\n{IMPLEMENTATION_PLAN_INSTRUCTIONS}"
