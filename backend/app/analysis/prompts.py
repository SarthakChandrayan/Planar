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
- Keep qualifiers and modal verbs exactly as said: "approximately 50" stays
  "approximately 50"; "should" stays "should", "could" stays "could". Never
  turn an estimate, suggestion, option or concern into a "must".
- A question is not a statement: "asked whether X" does not mean X is true or
  false. Never claim something is or is not in place unless someone said so.
- If there are none, return an empty list.
- Output compact JSON on ONE line, exactly like the example. No line breaks,
  no indentation.
""".strip()

DECISIONS_TASK = """
TASK: List the DECISIONS made in this meeting.
A decision is something participants explicitly agreed, chose, locked, rejected,
or put out of scope ("we'll go with X", "let's not do Y", "Z is out of scope
for this release", "agreed").
Include negative decisions (a rejected option, a non-goal): start them with
"Do not" and name exactly what was rejected, in the meeting's own words.
NOT decisions: proposals nobody accepted, one person's preference that others
pushed back on, ideas, "we could", open debates, and anything the meeting said
it is not deciding yet.
EXAMPLE: {"decisions":[{"statement":"Use SQLite for local drafts.","lines":[12]}]}
""".strip()

CHOICES_TASK = """
TASK: List the CHOICES this meeting discussed: every question of what to do,
which option to take, or whether to approve, sign, hire, buy, cut, change or
build something.
For each choice:
- "choice": the question itself, starting with "Whether" or "Which".
- "status": how the meeting LEFT it, judged from the LAST thing said about it:
  "decided"  the group agreed to do something;
  "rejected" the group agreed not to do it;
  "deferred" the group agreed to hold off for now and decide later
             ("not yet", "not today", "we'll decide after the review");
  "open"     nobody settled it: a proposal others pushed back on, a debate
             left hanging, or something said to be undecided or still open.
  One person proposing or preferring something is not a decision.
- "outcome": for decided, rejected or deferred, what holds now, as one short
  statement ("Hold the offsite in March.", "Do not book the venue yet.");
  for open, "".
- "lines": the 1 or 2 lines where it was settled or left open.
EXAMPLE: {"choices":[{"choice":"Whether to hold the offsite in March","status":"decided","outcome":"Hold the offsite in March.","lines":[12]},{"choice":"Which caterer to book","status":"open","outcome":"","lines":[30]}]}
""".strip()

REQUIREMENTS_TASK = """
TASK: List the REQUIREMENTS stated in this meeting.
A requirement is a condition the result MUST satisfy.
- Software: required behaviour, data handling, error handling, performance,
  security, compliance, monitoring, compatibility.
- Product, launch or business: rules, limits, eligibility, approvals, targets
  and things that must be in place ("the discount is only for existing
  customers", "targets must be set before launch").
Look through the WHOLE discussion, not just a final decisions list or recap:
requirements usually come up where people discuss conditions, limits,
eligibility, approvals and what has to exist.
Capture the detail a decision leaves out: who it applies to, limits, conditions.
State what must be true AFTER the work. Problems, current behaviour and
proposals that were not agreed are not requirements.
Rules that gate or limit the work ARE requirements: "no X until Y", "X
requires approval from Z", "must be defined before implementation", "X should
not be retried".
NOT requirements: a decision restated (choosing an option, price, vendor, date
or scope is a decision) and work assignments (those are tasks).
EXAMPLE: {"requirements":[{"statement":"The sync API must accept per-field timestamps.","lines":[30]}]}
""".strip()

TASKS_TASK = """
TASK: List the TASKS (action items) from this meeting.
A task is concrete work someone was asked to do or volunteered for
("Arjun will...", "can you...", "action item:", "I'll take that").
- "owner": the person's name exactly as written in the transcript, or "" if
  nobody was named.
- "title": the action, in a few words.
- "description": the FULL action as assigned. If it has several parts
  ("finalize X and coordinate Y"), keep every part. Never drop part of a task.
- "due": the deadline as said ("Friday", "end of sprint"), or the date the
  work is tied to ("for the October 28 review"), or "".
- "priority": "high" only if the meeting tied the task to an urgent deadline
  or a launch gate, or called it critical; "low" if optional; else "medium".
- "acceptance_criteria": 1 or 2 specific, checkable results of the work, using
  names, numbers and dates from the meeting. Do not restate the title.
EXAMPLE: {"tasks":[{"title":"Prototype the draft store","description":"Prototype the SQLite draft store with crash-safe writes and share the results with Chen","owner":"Ben","due":"Friday","priority":"high","acceptance_criteria":["Drafts survive the app being killed mid-save"],"lines":[41]}]}
""".strip()

RISKS_QUESTIONS_TASK = """
TASK: List the RISKS and OPEN QUESTIONS from this meeting.
A risk is something participants said could go wrong: failure modes, missed
deadlines, dependencies, capacity limits, customer or market reactions, cost,
security or compliance exposure. Look for warnings and concerns: "could",
"might", "risk", "concern", "warned", "problematic", "not enough capacity",
"hard to reverse", "if ... then ...". Include risks the meeting decided to
accept or mitigate, and say what could happen.
"severity": low, medium, high or critical, from how seriously it was treated.
Only consequences someone actually mentioned; do not add your own ("could lead
to data loss"). Something still to be decided is an OPEN QUESTION, not a risk.
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
    second_look: Sequence[str] = (),
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
    if second_look:
        # Same prefix as the first look (transcript, task, rules), so Ollama
        # reuses its cache and only reads this list.
        listing = "\n".join(f"- {text}" for text in second_look)
        sections.append(
            "SECOND LOOK. You already listed these from this transcript:\n"
            f"{listing}\n"
            "Read the WHOLE transcript again, beginning to end, including the middle "
            "of the discussion. List ONLY items that are MISSING from the list above. "
            "Do not repeat or reword items already listed. Return an empty list if "
            "nothing is missing."
        )
    if retry_note:
        sections.append(retry_note)
    sections.append("JSON:")
    return "\n\n".join(sections)
