"""Coverage families for the Payment Platform Redesign golden key.

Families group overlapping golden artifacts into coherent engineering
concepts from PAYMENT_PLATFORM_REDESIGN_TRANSCRIPT. Artifact definitions
stay in payment_platform_redesign_expected.py.

A core_group is satisfied when ANY key in that group is matched. That is
how a decision, a requirement, and a task that restate the same lock can
count once. Distinct behaviors stay in separate core groups.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoverageFamily:
    key: str
    description: str
    artifact_keys: tuple[str, ...]
    core_groups: tuple[tuple[str, ...], ...]
    notes: str = ""


PROCESSOR_SELECTION = CoverageFamily(
    key="PROCESSOR_SELECTION",
    description="Stripe PaymentIntents is the November card processor.",
    artifact_keys=("DEC_STRIPE_PAYMENT_INTENTS_NOVEMBER",),
    core_groups=(("DEC_STRIPE_PAYMENT_INTENTS_NOVEMBER",),),
    notes="Maya locked Stripe for November; Adyen and a generic provider interface were deferred.",
)

IDEMPOTENCY = CoverageFamily(
    key="IDEMPOTENCY",
    description="Payment idempotency is mandatory, with Postgres as the store and defined duplicate-key behavior.",
    artifact_keys=(
        "DEC_POSTGRES_IDEMPOTENCY_SOURCE_OF_TRUTH",
        "DEC_IDEMPOTENCY_KEY_UNIQUE_PER_MERCHANT_REQUEST",
        "REQ_PERSIST_IDEMPOTENCY_KEYS",
        "REQ_BACKEND_DUPLICATE_PAYMENT_PROTECTION",
        "REQ_IDEMPOTENCY_SAME_KEY_RETURNS_ORIGINAL",
        "REQ_IDEMPOTENCY_SAME_KEY_DIFFERENT_BODY_REJECTED",
    ),
    core_groups=(
        (
            "DEC_POSTGRES_IDEMPOTENCY_SOURCE_OF_TRUTH",
            "DEC_IDEMPOTENCY_KEY_UNIQUE_PER_MERCHANT_REQUEST",
            "REQ_PERSIST_IDEMPOTENCY_KEYS",
        ),
        ("REQ_BACKEND_DUPLICATE_PAYMENT_PROTECTION",),
        ("REQ_IDEMPOTENCY_SAME_KEY_RETURNS_ORIGINAL",),
        ("REQ_IDEMPOTENCY_SAME_KEY_DIFFERENT_BODY_REJECTED",),
    ),
    notes=(
        "Postgres SoT, unique-per-merchant, and persist-the-key are one lock. "
        "Backend duplicate protection and the two same-key API behaviors are distinct."
    ),
)

PAYMENT_STATE_MODEL = CoverageFamily(
    key="PAYMENT_STATE_MODEL",
    description="Internal payment states are modeled separately from raw Stripe status, and existing checkout assumptions are audited.",
    artifact_keys=(
        "DEC_INTERNAL_STATE_MACHINE_SEPARATE_FROM_STRIPE",
        "TSK_ARJUN_DOCUMENT_API_AND_STATE_MACHINE",
        "TSK_AUDIT_CHECKOUT_STATE_TRANSITIONS",
    ),
    core_groups=(
        ("DEC_INTERNAL_STATE_MACHINE_SEPARATE_FROM_STRIPE",),
        ("TSK_AUDIT_CHECKOUT_STATE_TRANSITIONS",),
    ),
    notes=(
        "The locked model is the internal state machine. Auditing existing checkout "
        "transitions is separate work. Documenting the API/state machine is supporting."
    ),
)

WEBHOOK_PROCESSING = CoverageFamily(
    key="WEBHOOK_PROCESSING",
    description="Webhooks are the verified, persisted, asynchronously processed confirmation path on existing SQS.",
    artifact_keys=(
        "DEC_WEBHOOKS_AUTHORITATIVE_ASYNC_CONFIRMATION",
        "DEC_WEBHOOKS_SIGNATURE_VERIFIED",
        "DEC_SQS_ASYNC_WEBHOOK_PROCESSING",
        "DEC_NO_KAFKA",
        "REQ_VERIFY_STRIPE_WEBHOOK_SIGNATURES",
        "REQ_PERSIST_WEBHOOK_EVENTS",
        "REQ_PROCESS_WEBHOOKS_ASYNCHRONOUSLY",
        "REQ_UNIQUE_STRIPE_WEBHOOK_EVENT_IDS",
        "TSK_IMPLEMENT_SQS_WEBHOOK_CONSUMER",
        "TSK_PRIYA_DOCUMENT_STRIPE_AND_WEBHOOK_MAPPINGS",
        "RSK_UNVERIFIED_WEBHOOKS",
        "RSK_DUPLICATE_WEBHOOK_PROCESSING",
        "RSK_ASYNC_WEBHOOK_DELAY_PENDING_ORDER",
    ),
    core_groups=(
        ("DEC_WEBHOOKS_AUTHORITATIVE_ASYNC_CONFIRMATION",),
        (
            "DEC_WEBHOOKS_SIGNATURE_VERIFIED",
            "REQ_VERIFY_STRIPE_WEBHOOK_SIGNATURES",
            "RSK_UNVERIFIED_WEBHOOKS",
        ),
        (
            "DEC_SQS_ASYNC_WEBHOOK_PROCESSING",
            "REQ_PROCESS_WEBHOOKS_ASYNCHRONOUSLY",
            "TSK_IMPLEMENT_SQS_WEBHOOK_CONSUMER",
            "DEC_NO_KAFKA",
        ),
        ("REQ_PERSIST_WEBHOOK_EVENTS",),
        (
            "REQ_UNIQUE_STRIPE_WEBHOOK_EVENT_IDS",
            "RSK_DUPLICATE_WEBHOOK_PROCESSING",
        ),
    ),
    notes=(
        "Signature verify, SQS/async (including no Kafka), persist, and unique event IDs "
        "are distinct. Decision/requirement/task restatements of the same lock share a group. "
        "Pending-order latency is supporting, not required for family match."
    ),
)

API_CONTRACT = CoverageFamily(
    key="API_CONTRACT",
    description="Checkout talks to a stable internal payment API, including GET payment status without processor internals.",
    artifact_keys=(
        "REQ_STABLE_INTERNAL_API_NOT_STRIPE_OBJECT",
        "REQ_GET_PAYMENTS_BY_ID",
        "REQ_PAYMENT_STATUS_HIDES_PROCESSOR_INTERNALS",
    ),
    core_groups=(
        ("REQ_STABLE_INTERNAL_API_NOT_STRIPE_OBJECT",),
        ("REQ_GET_PAYMENTS_BY_ID",),
        ("REQ_PAYMENT_STATUS_HIDES_PROCESSOR_INTERNALS",),
    ),
    notes="Stable response shape, GET /payments/{id}, and hiding Stripe internals are three API rules.",
)

SECURITY_AND_AUTHORIZATION = CoverageFamily(
    key="SECURITY_AND_AUTHORIZATION",
    description="Payment APIs are authenticated with ownership/tenant checks, and sensitive payment data stays out of logs.",
    artifact_keys=(
        "REQ_DO_NOT_LOG_SENSITIVE_PAYMENT_DATA",
        "RSK_SENSITIVE_DATA_IN_LOGS",
        "REQ_AUTHENTICATED_APIS_WITH_OWNERSHIP_CHECKS",
        "REQ_TENANT_ISOLATION_IN_SERVICE_LAYER",
        "REQ_CROSS_TENANT_ACCESS_TESTS",
        "RSK_CROSS_TENANT_PAYMENT_EXPOSURE",
    ),
    core_groups=(
        ("REQ_DO_NOT_LOG_SENSITIVE_PAYMENT_DATA", "RSK_SENSITIVE_DATA_IN_LOGS"),
        ("REQ_AUTHENTICATED_APIS_WITH_OWNERSHIP_CHECKS",),
        (
            "REQ_TENANT_ISOLATION_IN_SERVICE_LAYER",
            "REQ_CROSS_TENANT_ACCESS_TESTS",
            "RSK_CROSS_TENANT_PAYMENT_EXPOSURE",
        ),
    ),
    notes="Logging, end-user ownership authz, and multi-tenant isolation are distinct security concerns.",
)

SAVED_CARDS = CoverageFamily(
    key="SAVED_CARDS",
    description="November supports saved cards via Stripe identifiers, not raw card data.",
    artifact_keys=(
        "REQ_CARDS_AND_SAVED_CARDS_NOVEMBER",
        "REQ_SAVED_CARDS_STORE_STRIPE_IDENTIFIERS_NOT_RAW_CARDS",
        "TSK_ADD_GET_PAYMENT_METHODS",
    ),
    core_groups=(
        ("REQ_CARDS_AND_SAVED_CARDS_NOVEMBER",),
        ("REQ_SAVED_CARDS_STORE_STRIPE_IDENTIFIERS_NOT_RAW_CARDS",),
        ("TSK_ADD_GET_PAYMENT_METHODS",),
    ),
    notes="In-scope methods, storage rules, and GET /payment-methods are related but distinct.",
)

CHECKOUT_ARCHITECTURE = CoverageFamily(
    key="CHECKOUT_ARCHITECTURE",
    description="Payments ship as an isolated module inside checkout, not a new microservice.",
    artifact_keys=(
        "DEC_NO_SEPARATE_PAYMENT_MICROSERVICE",
        "DEC_PAYMENTS_MODULE_INSIDE_CHECKOUT",
    ),
    core_groups=(
        (
            "DEC_NO_SEPARATE_PAYMENT_MICROSERVICE",
            "DEC_PAYMENTS_MODULE_INSIDE_CHECKOUT",
        ),
    ),
    notes="Maya locked both clauses in one decision. Either artifact covers the family.",
)

ROLLOUT = CoverageFamily(
    key="ROLLOUT",
    description="New checkout starts at 1% behind a feature flag; numeric rollback thresholds remain open.",
    artifact_keys=(
        "DEC_FEATURE_FLAG_ONE_PERCENT_ROLLOUT",
        "REQ_ROLLOUT_MONITORING_METRICS",
        "OQ_ROLLOUT_THRESHOLDS_NOT_FINAL",
        "TSK_DANIEL_PROPOSE_ROLLOUT_THRESHOLDS_AND_ALERTS",
    ),
    core_groups=(
        ("DEC_FEATURE_FLAG_ONE_PERCENT_ROLLOUT",),
        ("OQ_ROLLOUT_THRESHOLDS_NOT_FINAL",),
        (
            "REQ_ROLLOUT_MONITORING_METRICS",
            "TSK_DANIEL_PROPOSE_ROLLOUT_THRESHOLDS_AND_ALERTS",
        ),
    ),
    notes=(
        "1% start is decided. Actual numeric thresholds are explicitly not decided. "
        "Named metrics and Daniel's follow-up task are one monitoring cluster."
    ),
)

RECONCILIATION = CoverageFamily(
    key="RECONCILIATION",
    description="A basic daily Stripe reconciliation job is in scope; full real-time reconciliation is not.",
    artifact_keys=(
        "REQ_DAILY_RECONCILIATION_IN_SCOPE",
        "REQ_NO_FULL_REALTIME_RECONCILIATION",
        "TSK_IMPLEMENT_DAILY_RECONCILIATION_JOB",
        "RSK_STRIPE_SUCCESS_DB_WRITE_FAILURE",
    ),
    core_groups=(
        (
            "REQ_DAILY_RECONCILIATION_IN_SCOPE",
            "REQ_NO_FULL_REALTIME_RECONCILIATION",
            "TSK_IMPLEMENT_DAILY_RECONCILIATION_JOB",
        ),
        ("RSK_STRIPE_SUCCESS_DB_WRITE_FAILURE",),
    ),
    notes=(
        "In-scope daily job, not-real-time, and implement-the-job are one lock. "
        "Stripe-success/DB-write-failure is the distinct failure mode that motivates it."
    ),
)

SCOPE = CoverageFamily(
    key="SCOPE",
    description="Refunds and partial captures are out of scope for November.",
    artifact_keys=("DEC_REFUNDS_AND_PARTIAL_CAPTURES_OUT_OF_SCOPE",),
    core_groups=(("DEC_REFUNDS_AND_PARTIAL_CAPTURES_OUT_OF_SCOPE",),),
    notes="Apple Pay is a forbidden promotion, not an expected artifact. Cards/saved cards live in SAVED_CARDS.",
)

API_VERSION = CoverageFamily(
    key="API_VERSION",
    description="Pin the Stripe API version so an unexpected change cannot break the release.",
    artifact_keys=(
        "DEC_PIN_STRIPE_API_VERSION",
        "RSK_STRIPE_API_VERSION_BREAKAGE",
    ),
    core_groups=(
        ("DEC_PIN_STRIPE_API_VERSION", "RSK_STRIPE_API_VERSION_BREAKAGE"),
    ),
    notes="The concern and the pin are one mitigation. Either artifact covers the family.",
)

COMPLIANCE_RETENTION = CoverageFamily(
    key="COMPLIANCE_RETENTION",
    description="Webhook retention period is open until compliance confirms it.",
    artifact_keys=(
        "OQ_WEBHOOK_RETENTION_PENDING_COMPLIANCE",
        "TSK_MAYA_COMPLIANCE_WEBHOOK_RETENTION",
    ),
    core_groups=(
        (
            "OQ_WEBHOOK_RETENTION_PENDING_COMPLIANCE",
            "TSK_MAYA_COMPLIANCE_WEBHOOK_RETENTION",
        ),
    ),
    notes="Storing events is WEBHOOK_PROCESSING. How long to keep them is this family.",
)

PAYMENT_PLATFORM_REDESIGN_FAMILIES: tuple[CoverageFamily, ...] = (
    PROCESSOR_SELECTION,
    IDEMPOTENCY,
    PAYMENT_STATE_MODEL,
    WEBHOOK_PROCESSING,
    API_CONTRACT,
    SECURITY_AND_AUTHORIZATION,
    SAVED_CARDS,
    CHECKOUT_ARCHITECTURE,
    ROLLOUT,
    RECONCILIATION,
    SCOPE,
    API_VERSION,
    COMPLIANCE_RETENTION,
)
