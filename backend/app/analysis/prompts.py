MEETING_ANALYSIS_INSTRUCTIONS = """
You extract a structured engineering meeting analysis from a transcript.

Return ONE JSON object. No markdown. No commentary. No IDs.

The JSON must use exactly these keys:
{
  "decisions": [],
  "requirements": [],
  "tasks": [],
  "risks": [],
  "open_questions": []
}

Do not include id fields. The application assigns IDs.

GOAL
Produce a COMPLETE + GROUNDED engineering record, not a short highlights
summary and not maximum output volume. Extract ALL transcript-supported
explicit decisions, product/system requirements, explicitly assigned or
requested engineering tasks, residual failure risks under the accepted
design, and explicitly unresolved open questions. Do not select only the
"most important" items.

Prefer omission over invention, but do not omit an explicit
transcript-supported engineering fact merely because it is less important
than another fact.

REQUIRED FULL-TRANSCRIPT WALK
Scan the entire transcript before producing JSON.
Do not stop after finding the major architectural decisions.
After the full scan, use:
- the facilitator / final recap as a completeness checklist of locked
  decisions,
- closing assignments / action items as a checklist of tasks,
- and also keep important facts from earlier discussion that the recap
  does not repeat.
The recap is a checklist, not a replacement for earlier transcript evidence.
If the facilitator recap explicitly states a locked engineering decision,
extract it unless it is merely an exact restatement of another already-
extracted decision. Do not blindly extract every recap sentence; only extract
statements that are genuinely locked decisions.
Pay particular attention, when the recap or discussion locks them, to:
- webhook events as the authoritative asynchronous confirmation mechanism,
- using existing queue infrastructure (for example SQS) for asynchronous
  webhook processing,
- not introducing a new event bus (for example Kafka) when that is rejected,
- explicit November non-goals such as refunds or partial captures being
  out of scope.

CATEGORIES
Do not unnecessarily duplicate the same sentence across lists.
Do NOT use that rule to erase important engineering facts.
If the transcript contains a locked decision, a distinct requirement that
follows from it, and a separately assigned task, extract all of them when
they represent genuinely different information.
A decision can remain a decision even when it also causes implementation
work. Do not replace an explicit decision with a synthesized implementation
task.

DECISION
Something participants explicitly agreed on or finalized — including both
positive choices and negative / non-goal commitments.
Examples of agreement: "we will", "agreed", "that's locked", "decision is",
"let's make that the decision", "out of scope", "we will not", "no new X",
"keep X inside Y".
Examples of decisions when clearly locked:
- choosing Stripe PaymentIntents
- choosing Postgres
- choosing SQS
- pinning an API version
- keeping payments as a module inside checkout
- NOT creating a separate payment microservice
- NOT introducing Kafka
- keeping refunds / partial captures out of November scope
Pay attention to architecture: service boundaries, module boundaries, where
functionality lives, whether a new service/microservice is introduced or
explicitly rejected, and whether existing infrastructure is reused or rejected.
Pay attention to scope: "out of scope", "not in November", "follow-up",
"deferred", "not included", "no support for X in this release". Extract
explicit scope exclusions when they are locked.
A suggestion is NOT a decision.
"We could use Kafka." is NOT a decision.
"Maybe we should add Redis." is NOT a decision and NOT a requirement.
If it was proposed and then rejected or not accepted, omit it. Do not treat
a rejected alternative as a decision, requirement, task, current risk, or
open question.

REQUIREMENT
Something the system or product must do, explicitly stated or clearly
required by an agreed decision.
A requirement must describe what the current / November design actually
requires. Do not fold future, deferred, "can come later", or follow-up
features into a current requirement merely because they were mentioned.
Example: if cards and saved cards are in scope for November and Apple Pay
is explicitly later / out of November, the November requirement is cards
and saved cards only — do not write "with Apple Pay to be added later"
into that requirement.
Do not turn a maybe/suggestion into a requirement.
Extract concrete product/system behavior, including:
- named HTTP endpoints (method + path), e.g. GET /payments/{id}
- API response contracts and processor-vs-internal API boundaries
- statements about hiding processor internals or requiring a stable internal API
- persistence requirements
- authentication, authorization, ownership checks, tenant isolation,
  and cross-tenant access
- logging restrictions and sensitive-data constraints
- data-storage constraints (e.g. identifiers, not raw card data)
- duplicate / idempotency behavior
- webhook behavior
- saved-card behavior
If the transcript establishes a named endpoint as part of the design, extract
it as a requirement.

When the transcript states these separately, keep them as separate requirements
(do not merge them into one generic item):

Idempotency — extract distinct behaviors when stated:
- same idempotency key + same merchant/request/body → return the original result
- same idempotency key + different body → reject
- backend duplicate protection must not rely only on frontend retry/disabling
- Postgres persistence / unique constraint as the selected source of truth
Do not merge all of these into one generic "implement idempotency" artifact.

Saved cards — extract separately when explicitly stated:
- cards and saved cards are supported for November
- store Stripe customer / payment-method identifiers rather than raw card data
- GET /payment-methods is available
Do not let a general "cards and saved cards" scope statement cause the
storage or API details to be omitted.

API contract — extract separately when stated:
- GET /payments/{id}
- stable internal response (not passing the processor object through)
- do not expose raw Stripe / processor internals

Security — extract separately when stated:
- authorization / ownership checks
- tenant isolation
- cross-tenant access tests
- sensitive payment data must not be logged
Do not assume tenant isolation also captures logging restrictions or
explicit testing requirements.

Reconciliation — extract separately when stated:
- a basic daily reconciliation job is in scope
- full real-time reconciliation is not in scope

TASK
Prefer concrete engineering work that was explicitly assigned, requested,
or acknowledged.
Look for: "I'll implement...", "I'll handle...", "Make that a task.",
"Arjun, ...", "Priya, ...", "Daniel, ...", "Maya will...", and explicit
closing action items.
Preserve the owner when the transcript makes it clear.
Do NOT invent an owner from a nearby requirement.
Do NOT turn a requirement sentence into an implementation task merely
because implementation would obviously be needed.
Do NOT drop an explicit assigned task merely because a related requirement
or decision was already extracted.
Include acceptance_criteria when the meeting states how done is judged.
priority must be one of: low, medium, high, critical.

RISK
A failure mode that remains relevant under the accepted design.
severity must be one of: low, medium, high, critical.
Do not confuse "someone raised a concern about an option" with "the final
design has this risk."
If the team discusses an alternative and explicitly rejects it, do NOT emit
the rejected alternative itself as a current risk.
Once a replacement is locked (for example Postgres as the idempotency source
of truth), do not emit the rejected option as a current risk (for example
Redis-as-source-of-truth or Redis-data-loss). "I don't like Redis..." is not
a residual risk after Redis has been rejected.
Once a security or control mechanism is explicitly accepted (for example
webhook signature verification), do not manufacture a generic risk that
the mechanism might fail. Risks must come from an actual failure mode
participants discussed, not from the hypothetical that an implemented
control could break.
Preserve genuine residual risks of the chosen design, such as:
- Stripe succeeds but the local database write fails
- asynchronous webhook processing leaves a customer order pending
- sensitive data in logs, or missing ownership/tenant checks, when
  participants actually discussed those failure modes
Do not invent "webhook verification could fail, so invalid events might
be processed" when the meeting locked signature verification and did not
discuss that residual failure mode.

OPEN QUESTION
Only when the transcript indicates the item remains unresolved.
Examples: "open item", "open question", "not finalized", "pending compliance",
"we still need to decide...", "thresholds are not finalized".
A rejected proposal is not an open question merely because it was discussed.
Unresolved items in the closing section still count.
The "question" field must name the unresolved decision itself, not only
inputs used to discuss it.
For rollout, prefer the unresolved numeric thresholds (for example
"What numeric rollout/rollback thresholds should be used?") rather than
merely listing evaluation metrics.
For compliance retention, preserve the unresolved retention-period question.

CRITICAL RULES
- Extract ONLY information supported by the transcript.
- Prefer omission over invention, but do not omit an explicit
  transcript-supported engineering fact merely because it is less important
  than another fact.
- Do not upgrade suggestions, ideas, or "we could" into decisions or requirements.
- Rejected alternatives must not become current design facts.
- confidence is your extraction confidence from 0.0 to 1.0, not a fact about the product.
- excerpt must be a short VERBATIM quote copied from the transcript.
  Do not paraphrase. Do not invent quotes.
- If the transcript does not support an item, leave it out.
- Every extracted decision, requirement, task, and risk must have appropriate
  source evidence. Open questions should have source evidence when available.

FIELD NAMES — do not reuse the decision shape on every list.
- decisions and requirements use "statement" and "source_reference".
- tasks use "title", "description", "priority", "acceptance_criteria",
  and "source_references" (plural list). Never use "statement" on a task.
- risks use "description", "severity", and "source_reference".
- open_questions use "question", "context", and "source_reference".
  Never use "statement" on an open question.

ITEM SHAPES

decisions[]:
  { "statement": "...", "confidence": 0.0, "source_reference": { "excerpt": "..." } }

requirements[]:
  { "statement": "...", "confidence": 0.0, "source_reference": { "excerpt": "..." } }

tasks[]:
  {
    "title": "...",
    "description": "...",
    "priority": "high",
    "acceptance_criteria": ["..."],
    "source_references": [{ "excerpt": "..." }]
  }

risks[]:
  { "description": "...", "severity": "high", "source_reference": { "excerpt": "..." } }

open_questions[]:
  { "question": "...", "context": "...", "source_reference": { "excerpt": "..." } }
""".strip()


def build_meeting_analysis_prompt(transcript: str) -> str:
    return (
        f"{MEETING_ANALYSIS_INSTRUCTIONS}\n\n"
        "TRANSCRIPT:\n"
        f"{transcript.strip()}\n"
    )
