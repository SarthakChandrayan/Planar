"""Prompts for the multi-pass meeting analysis.

Every pass prompt starts with the identical transcript block, so Ollama can
reuse the cached prompt prefix and only process the short pass instructions
on passes 2..n. Keep anything that varies per pass AFTER the transcript.

Passes never see the text of items found by other passes: a small model
tends to copy whatever list it is shown. Links between items are inferred
by the application afterwards.
"""

from collections.abc import Sequence

from app.analysis.transcript import TranscriptChunk

_RULES = """
RULES
- Use only what the transcript says. Never invent facts, names, or dates.
- If you are unsure an item qualifies, leave it out.
- "lines": the 1 or 2 L-numbers of the lines that state the item.
- Write each item as one short, specific sentence (under 20 words). Name the
  component directly ("The webhook handler must ..."), not "The system must ...".
- Options the meeting rejected appear only as "do not ..." decisions. Never
  mention them in requirements, tasks, or risks.
- If there are none, return an empty list.
- Output compact JSON on ONE line, exactly like the example. No line breaks,
  no indentation.
""".strip()

DECISIONS_TASK = """
TASK: List the DECISIONS made in this meeting.
A decision is something participants explicitly agreed, chose, locked, rejected,
or put out of scope ("we'll go with X", "let's not do Y", "Z is out of scope
for this release", "agreed").
Include negative decisions (a rejected option, a non-goal) phrased as such,
for example "Do not build a separate service for X."
NOT decisions: proposals nobody accepted, ideas, "we could", open debates.
EXAMPLE: {"decisions":[{"statement":"Use SQLite for local drafts.","lines":[12]}]}
""".strip()

REQUIREMENTS_TASK = """
TASK: List the REQUIREMENTS stated in this meeting.
A requirement is something the built system MUST do or satisfy: required
behaviour, data handling, error handling, performance, security, compliance,
monitoring, or compatibility.
NOT requirements: choices of technology, vendor, architecture or scope (those
are decisions), and work assignments (those are tasks).
EXAMPLE: {"requirements":[{"statement":"The sync API must accept per-field timestamps.","lines":[30]}]}
""".strip()

TASKS_TASK = """
TASK: List the TASKS (action items) from this meeting.
A task is concrete work someone was asked to do or volunteered for
("Arjun will...", "can you...", "action item:", "I'll take that").
- "owner": the person's name exactly as written in the transcript, or "" if
  nobody was named.
- "due": the deadline as said ("Friday", "end of sprint"), or "".
- "priority": low, medium, high or critical, from the urgency in the meeting.
- "description": one short sentence, or "" if the title says it all.
- "acceptance_criteria": up to 2 short, checkable "done when" conditions,
  based on what was said.
EXAMPLE: {"tasks":[{"title":"Prototype the draft store","description":"","owner":"Ben","due":"Friday","priority":"high","acceptance_criteria":["Drafts survive an app crash"],"lines":[41]}]}
""".strip()

RISKS_QUESTIONS_TASK = """
TASK: List the RISKS and OPEN QUESTIONS from this meeting.
A risk is something participants said could go wrong: failure modes,
deadline or dependency risks, security or compliance exposure.
"severity": low, medium, high or critical, from how seriously it was treated.
An open question is something explicitly left unresolved: to be decided later,
or to be answered by someone not present. Questions answered during the
meeting are NOT open questions.
"context": one short sentence on why the question matters.
EXAMPLE: {"risks":[{"description":"Wrong device clocks could overwrite newer edits.","severity":"high","lines":[33]}],"open_questions":[{"question":"Does the web app need offline mode?","context":"Sales keeps asking.","lines":[52]}]}
""".strip()


def transcript_block(chunk: TranscriptChunk, total_chunks: int) -> str:
    part = f" (part {chunk.index + 1} of {total_chunks})" if total_chunks > 1 else ""
    return (
        f"MEETING TRANSCRIPT{part}. Each line starts with its line number.\n"
        f"{chunk.render()}\n"
        "END OF TRANSCRIPT\n\n"
    )


def build_pass_prompt(
    chunk: TranscriptChunk,
    total_chunks: int,
    task: str,
    *,
    already_found: Sequence[str] = (),
    retry_note: str | None = None,
) -> str:
    """Assemble a pass prompt: transcript first, pass-specific text last.

    ``already_found`` lists items from earlier transcript parts to not repeat.
    """
    sections = [transcript_block(chunk, total_chunks), task, _RULES]
    if already_found:
        listing = "\n".join(f"- {text}" for text in already_found)
        sections.append(
            "ALREADY FOUND in earlier parts of the transcript (do not repeat):\n"
            f"{listing}"
        )
    if retry_note:
        sections.append(retry_note)
    sections.append("JSON:")
    return "\n\n".join(sections)
