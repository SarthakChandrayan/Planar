"""Golden expected artifacts for the Payment Platform Redesign transcript.

This is a human answer key, not model output. Items are based only on what
participants locked, required, assigned, worried about, or left unresolved
in PAYMENT_PLATFORM_REDESIGN_TRANSCRIPT.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Category = Literal["decision", "requirement", "task", "risk", "open_question"]


@dataclass(frozen=True)
class ExpectedArtifact:
    key: str
    category: Category
    description: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class ForbiddenConcept:
    """Must not appear as an accepted artifact in the listed categories."""

    key: str
    concept: str
    forbidden_in: tuple[Category, ...]
    keywords: tuple[str, ...]
    notes: str


# --- Decisions: explicitly agreed or restated as locked in the close ---

EXPECTED_DECISIONS: tuple[ExpectedArtifact, ...] = (
    ExpectedArtifact(
        key="DEC_STRIPE_PAYMENT_INTENTS_NOVEMBER",
        category="decision",
        description="Use Stripe PaymentIntents for card payments in the November release.",
        keywords=("stripe", "paymentintents", "november", "card payments"),
    ),
    ExpectedArtifact(
        key="DEC_POSTGRES_IDEMPOTENCY_SOURCE_OF_TRUTH",
        category="decision",
        description="Postgres is the source of truth for payment idempotency.",
        keywords=("postgres", "source of truth", "idempotency", "authoritative"),
    ),
    ExpectedArtifact(
        key="DEC_IDEMPOTENCY_KEY_UNIQUE_PER_MERCHANT_REQUEST",
        category="decision",
        description="The idempotency key must be unique per merchant payment request.",
        keywords=("idempotency key", "unique", "merchant", "payment request"),
    ),
    ExpectedArtifact(
        key="DEC_INTERNAL_STATE_MACHINE_SEPARATE_FROM_STRIPE",
        category="decision",
        description="Use an internal payment state machine and store raw Stripe processor status separately.",
        keywords=("internal", "state machine", "processor status", "stripe status"),
    ),
    ExpectedArtifact(
        key="DEC_WEBHOOKS_AUTHORITATIVE_ASYNC_CONFIRMATION",
        category="decision",
        description="Treat webhooks as the authoritative asynchronous confirmation mechanism.",
        keywords=("webhook", "authoritative", "asynchronous", "confirmation"),
    ),
    ExpectedArtifact(
        key="DEC_WEBHOOKS_SIGNATURE_VERIFIED",
        category="decision",
        description="Webhook events must be signature-verified before processing.",
        keywords=("webhook", "signature", "verify", "stripe signs"),
    ),
    ExpectedArtifact(
        key="DEC_SQS_ASYNC_WEBHOOK_PROCESSING",
        category="decision",
        description="Process webhooks asynchronously using the existing SQS infrastructure.",
        keywords=("sqs", "asynchronously", "existing", "webhook"),
    ),
    ExpectedArtifact(
        key="DEC_NO_KAFKA",
        category="decision",
        description="Do not introduce Kafka for this webhook pipeline.",
        keywords=("not introducing kafka", "no new kafka", "do not need kafka"),
    ),
    ExpectedArtifact(
        key="DEC_NO_SEPARATE_PAYMENT_MICROSERVICE",
        category="decision",
        description="Do not create a separate payment microservice for November.",
        keywords=("no separate", "payment microservice", "november"),
    ),
    ExpectedArtifact(
        key="DEC_PAYMENTS_MODULE_INSIDE_CHECKOUT",
        category="decision",
        description="Implement payments as an isolated module within checkout.",
        keywords=("isolated module", "inside checkout", "checkout service"),
    ),
    ExpectedArtifact(
        key="DEC_FEATURE_FLAG_ONE_PERCENT_ROLLOUT",
        category="decision",
        description="Ship the new checkout flow behind a feature flag starting at 1% rollout.",
        keywords=("feature flag", "1%", "rollout", "fallback"),
    ),
    ExpectedArtifact(
        key="DEC_REFUNDS_AND_PARTIAL_CAPTURES_OUT_OF_SCOPE",
        category="decision",
        description="Refunds and partial captures are out of scope for November.",
        keywords=("refunds", "partial captures", "out of scope", "november"),
    ),
    ExpectedArtifact(
        key="DEC_PIN_STRIPE_API_VERSION",
        category="decision",
        description="Pin the Stripe API version for this release.",
        keywords=("pin", "stripe api version", "this release"),
    ),
)

# --- Requirements: system/product must-do, stated or required by a locked decision ---

EXPECTED_REQUIREMENTS: tuple[ExpectedArtifact, ...] = (
    ExpectedArtifact(
        key="REQ_CARDS_AND_SAVED_CARDS_NOVEMBER",
        category="requirement",
        description="November checkout must support cards and saved cards.",
        keywords=("cards", "saved cards", "november"),
    ),
    ExpectedArtifact(
        key="REQ_PERSIST_IDEMPOTENCY_KEYS",
        category="requirement",
        description="Persist the idempotency key with the payment record.",
        keywords=("persist", "idempotency key", "payment record"),
    ),
    ExpectedArtifact(
        key="REQ_BACKEND_DUPLICATE_PAYMENT_PROTECTION",
        category="requirement",
        description="The backend must recognize duplicate payment creation; frontend button disable is not sufficient.",
        keywords=("backend", "duplicate", "cannot rely on frontend"),
    ),
    ExpectedArtifact(
        key="REQ_IDEMPOTENCY_SAME_KEY_RETURNS_ORIGINAL",
        category="requirement",
        description="Same idempotency key plus same merchant account must return the original result.",
        keywords=("same key", "merchant account", "original result"),
    ),
    ExpectedArtifact(
        key="REQ_IDEMPOTENCY_SAME_KEY_DIFFERENT_BODY_REJECTED",
        category="requirement",
        description="Same idempotency key with a different request body must be rejected.",
        keywords=("same key", "different request body", "rejected"),
    ),
    ExpectedArtifact(
        key="REQ_STABLE_INTERNAL_API_NOT_STRIPE_OBJECT",
        category="requirement",
        description="The API must expose a stable internal response, not the Stripe object passed through to the frontend.",
        keywords=("stable internal", "not passing the stripe object", "frontend"),
    ),
    ExpectedArtifact(
        key="REQ_DO_NOT_LOG_SENSITIVE_PAYMENT_DATA",
        category="requirement",
        description="Do not log card details or client secrets; PaymentIntent ID and internal payment ID are allowed.",
        keywords=("logs", "card details", "client secrets", "paymentintent id"),
    ),
    ExpectedArtifact(
        key="REQ_VERIFY_STRIPE_WEBHOOK_SIGNATURES",
        category="requirement",
        description="Verify the Stripe webhook signature before processing anything.",
        keywords=("verify", "signature", "webhook", "before processing"),
    ),
    ExpectedArtifact(
        key="REQ_PERSIST_WEBHOOK_EVENTS",
        category="requirement",
        description="Persist webhook events for audit trail and replay.",
        keywords=("persist", "webhook events", "audit trail", "replay"),
    ),
    ExpectedArtifact(
        key="REQ_PROCESS_WEBHOOKS_ASYNCHRONOUSLY",
        category="requirement",
        description="Write the webhook event then process it asynchronously.",
        keywords=("process asynchronously", "write the event", "postgres"),
    ),
    ExpectedArtifact(
        key="REQ_GET_PAYMENTS_BY_ID",
        category="requirement",
        description="Expose GET /payments/{id} so the order page can fetch payment status from the backend.",
        keywords=("get /payments/{id}", "payment status", "backend"),
    ),
    ExpectedArtifact(
        key="REQ_PAYMENT_STATUS_HIDES_PROCESSOR_INTERNALS",
        category="requirement",
        description="Do not expose processor internals through the payment-status endpoint.",
        keywords=("don't expose", "processor internals", "endpoint"),
    ),
    ExpectedArtifact(
        key="REQ_SAVED_CARDS_STORE_STRIPE_IDENTIFIERS_NOT_RAW_CARDS",
        category="requirement",
        description="Store Stripe customer and payment-method identifiers; no raw card information in our database.",
        keywords=("stripe customer", "payment method", "no raw card"),
    ),
    ExpectedArtifact(
        key="REQ_AUTHENTICATED_APIS_WITH_OWNERSHIP_CHECKS",
        category="requirement",
        description="Payment APIs require authenticated users and ownership authorization.",
        keywords=("authenticated users", "authorization", "ownership"),
    ),
    ExpectedArtifact(
        key="REQ_TENANT_ISOLATION_IN_SERVICE_LAYER",
        category="requirement",
        description="Tenant isolation is required; enforce authorization in the service layer (no full RLS before November).",
        keywords=("tenant isolation", "service layer", "rls", "multi-tenant"),
    ),
    ExpectedArtifact(
        key="REQ_CROSS_TENANT_ACCESS_TESTS",
        category="requirement",
        description="Add tests specifically for cross-tenant access.",
        keywords=("tests", "cross-tenant", "access"),
    ),
    ExpectedArtifact(
        key="REQ_UNIQUE_STRIPE_WEBHOOK_EVENT_IDS",
        category="requirement",
        description="Webhook event IDs must be unique so retries do not process the same Stripe event twice.",
        keywords=("unique", "event id", "stripe event", "retries"),
    ),
    ExpectedArtifact(
        key="REQ_DAILY_RECONCILIATION_IN_SCOPE",
        category="requirement",
        description="A basic daily reconciliation job against Stripe is in scope.",
        keywords=("daily", "reconciliation", "in scope", "stripe"),
    ),
    ExpectedArtifact(
        key="REQ_NO_FULL_REALTIME_RECONCILIATION",
        category="requirement",
        description="Full real-time reconciliation is not in scope for this release.",
        keywords=("real-time reconciliation", "not", "safety net"),
    ),
    ExpectedArtifact(
        key="REQ_ROLLOUT_MONITORING_METRICS",
        category="requirement",
        description="Watch payment creation success rate, webhook processing latency, and checkout conversion for rollout/rollback.",
        keywords=(
            "payment creation success rate",
            "webhook processing latency",
            "checkout conversion",
        ),
    ),
)

# --- Tasks: concrete work assigned or accepted as work in the meeting ---

EXPECTED_TASKS: tuple[ExpectedArtifact, ...] = (
    ExpectedArtifact(
        key="TSK_ARJUN_DOCUMENT_API_AND_STATE_MACHINE",
        category="task",
        description="Arjun: document the API contract and state machine.",
        keywords=("arjun", "document", "api contract", "state machine"),
    ),
    ExpectedArtifact(
        key="TSK_PRIYA_DOCUMENT_STRIPE_AND_WEBHOOK_MAPPINGS",
        category="task",
        description="Priya: document the Stripe integration and webhook event mappings.",
        keywords=("priya", "document", "stripe integration", "webhook event mappings"),
    ),
    ExpectedArtifact(
        key="TSK_DANIEL_PROPOSE_ROLLOUT_THRESHOLDS_AND_ALERTS",
        category="task",
        description="Daniel: propose the rollout thresholds and monitoring alerts.",
        keywords=("daniel", "propose", "rollout thresholds", "monitoring alerts"),
    ),
    ExpectedArtifact(
        key="TSK_MAYA_COMPLIANCE_WEBHOOK_RETENTION",
        category="task",
        description="Maya: coordinate with compliance on webhook retention.",
        keywords=("maya", "compliance", "webhook retention"),
    ),
    ExpectedArtifact(
        key="TSK_IMPLEMENT_SQS_WEBHOOK_CONSUMER",
        category="task",
        description="Implement the webhook consumer on the existing SQS infrastructure.",
        keywords=("implement the consumer", "sqs", "arjun"),
    ),
    ExpectedArtifact(
        key="TSK_AUDIT_CHECKOUT_STATE_TRANSITIONS",
        category="task",
        description="Audit existing checkout state transitions for asynchronous payment processing.",
        keywords=("audit", "checkout state transitions", "asynchronous"),
    ),
    ExpectedArtifact(
        key="TSK_IMPLEMENT_DAILY_RECONCILIATION_JOB",
        category="task",
        description="Implement the basic daily reconciliation job.",
        keywords=("implement the daily job", "reconciliation"),
    ),
    ExpectedArtifact(
        key="TSK_ADD_GET_PAYMENT_METHODS",
        category="task",
        description="Add GET /payment-methods for saved cards belonging to that customer.",
        keywords=("get /payment-methods", "saved", "arjun"),
    ),
)

# --- Risks: failure modes or concerns discussed, not merely implicit ---

EXPECTED_RISKS: tuple[ExpectedArtifact, ...] = (
    ExpectedArtifact(
        key="RSK_STRIPE_SUCCESS_DB_WRITE_FAILURE",
        category="risk",
        description="Stripe can capture a payment while a local database write fails, leaving our state wrong until webhook reconciliation.",
        keywords=("stripe returns success", "database write fails", "captured"),
    ),
    ExpectedArtifact(
        key="RSK_ASYNC_WEBHOOK_DELAY_PENDING_ORDER",
        category="risk",
        description="Asynchronous webhook delay can leave a customer order stuck in pending.",
        keywords=("eventually", "stuck in pending", "webhook latency"),
    ),
    ExpectedArtifact(
        key="RSK_SENSITIVE_DATA_IN_LOGS",
        category="risk",
        description="Sensitive payment information in logs is a security/compliance risk.",
        keywords=("sensitive payment information", "logs", "client secrets"),
    ),
    ExpectedArtifact(
        key="RSK_UNVERIFIED_WEBHOOKS",
        category="risk",
        description="Unverified webhook requests cannot be trusted and could be malicious.",
        keywords=("can't just trust", "webhook endpoint", "verification"),
    ),
    ExpectedArtifact(
        key="RSK_DUPLICATE_WEBHOOK_PROCESSING",
        category="risk",
        description="Webhook retries can process the same event twice if event IDs are not unique/idempotent.",
        keywords=("retries", "same event twice", "event ids"),
    ),
    ExpectedArtifact(
        key="RSK_CROSS_TENANT_PAYMENT_EXPOSURE",
        category="risk",
        description="Missing ownership/tenant checks could expose another tenant's payment data.",
        keywords=("cross-tenant", "ownership", "tenant isolation"),
    ),
    ExpectedArtifact(
        key="RSK_STRIPE_API_VERSION_BREAKAGE",
        category="risk",
        description="An unexpected Stripe API version change could produce a breaking response.",
        keywords=("api version", "breaking response", "unexpectedly"),
    ),
)

# --- Open questions: explicitly unresolved ---

EXPECTED_OPEN_QUESTIONS: tuple[ExpectedArtifact, ...] = (
    ExpectedArtifact(
        key="OQ_ROLLOUT_THRESHOLDS_NOT_FINAL",
        category="open_question",
        description="Numeric rollout/rollback thresholds are not decided yet.",
        keywords=("actual thresholds", "open item", "not a decision yet"),
    ),
    ExpectedArtifact(
        key="OQ_WEBHOOK_RETENTION_PENDING_COMPLIANCE",
        category="open_question",
        description="Webhook event retention period is open until compliance confirms it.",
        keywords=("retention period", "open question", "compliance"),
    ),
)

# --- Rejected or ruled-out: must not be treated as accepted work ---

FORBIDDEN_CONCEPTS: tuple[ForbiddenConcept, ...] = (
    ForbiddenConcept(
        key="FORBID_KAFKA",
        concept="Kafka as the webhook/event bus for this release",
        forbidden_in=("decision", "requirement", "task"),
        keywords=("kafka",),
        notes="Proposed then rejected; Maya's close confirms we are not introducing Kafka.",
    ),
    ForbiddenConcept(
        key="FORBID_REDIS_IDEMPOTENCY_SOURCE_OF_TRUTH",
        concept="Redis as the source of truth for payment idempotency",
        forbidden_in=("decision", "requirement", "task"),
        keywords=("redis", "source of truth", "idempotency"),
        notes="Arjun suggested Redis; Daniel and Priya rejected it; Postgres was locked instead.",
    ),
    ForbiddenConcept(
        key="FORBID_APPLE_PAY_NOVEMBER_REQUIREMENT",
        concept="Apple Pay as a November requirement or unresolved November scope item",
        forbidden_in=("decision", "requirement", "open_question"),
        keywords=("apple pay", "november"),
        notes="Sofia asked; Maya said Apple Pay is still out of scope for November.",
    ),
)


@dataclass(frozen=True)
class GoldenAnswerKey:
    decisions: tuple[ExpectedArtifact, ...]
    requirements: tuple[ExpectedArtifact, ...]
    tasks: tuple[ExpectedArtifact, ...]
    risks: tuple[ExpectedArtifact, ...]
    open_questions: tuple[ExpectedArtifact, ...]
    forbidden: tuple[ForbiddenConcept, ...]


PAYMENT_PLATFORM_REDESIGN_GOLDEN = GoldenAnswerKey(
    decisions=EXPECTED_DECISIONS,
    requirements=EXPECTED_REQUIREMENTS,
    tasks=EXPECTED_TASKS,
    risks=EXPECTED_RISKS,
    open_questions=EXPECTED_OPEN_QUESTIONS,
    forbidden=FORBIDDEN_CONCEPTS,
)
