from app.analysis.excerpts import excerpt_supported_by_transcript, excerpt_supports_claim

_POSTGRES_CLAIM = "Postgres is the source of truth for payment idempotency."
_POSTGRES_EXCERPT = "Postgres is the source of truth for payment idempotency..."
_STRIPE_DB_CLAIM = "Stripe succeeds but the local database write fails."
_IDEMPOTENCY_BODY_EXCERPT = (
    "One concern is that requests with the same key but different bodies "
    "could cause inconsistent behavior."
)
_STRIPE_DB_EXCERPT = (
    "If Stripe succeeds but the local database write fails, the customer "
    "sees success and we have no local record."
)
_POSTGRES_PARAPHRASE_CLAIM = "Postgres is the source of truth for idempotency."
_POSTGRES_PARAPHRASE_EXCERPT = (
    "We'll keep PostgreSQL as the authoritative database for idempotency."
)
_WEBHOOK_PENDING_CLAIM = (
    "Asynchronous webhook processing may leave a customer order pending."
)
_WEBHOOK_PENDING_EXCERPT = (
    "Eventually isn't good enough if the customer sees an order stuck in pending."
)


def test_excerpt_supported_by_transcript_allows_case_and_whitespace() -> None:
    transcript = "We will freeze the public checkout API at /v1 until October."

    assert excerpt_supported_by_transcript(
        "We will freeze the public checkout API at /v1 until October.",
        transcript,
    )
    assert excerpt_supported_by_transcript(
        "we will freeze  the public checkout API at /v1 until October.",
        transcript,
    )
    assert not excerpt_supported_by_transcript(
        "We unanimously voted to adopt Kafka today.",
        transcript,
    )


def test_matching_excerpt_supports_claim() -> None:
    assert excerpt_supports_claim(_POSTGRES_CLAIM, _POSTGRES_EXCERPT)


def test_verbatim_but_unrelated_excerpt_does_not_support_claim() -> None:
    assert not excerpt_supports_claim(_STRIPE_DB_CLAIM, _IDEMPOTENCY_BODY_EXCERPT)


def test_webhook_risk_does_not_use_idempotency_excerpt() -> None:
    assert not excerpt_supports_claim(_WEBHOOK_PENDING_CLAIM, _IDEMPOTENCY_BODY_EXCERPT)


def test_generic_excerpt_words_do_not_support_specific_risk() -> None:
    padded_claim = (
        "Stripe succeeds but the local database write fails, "
        "which could cause inconsistent behavior."
    )
    assert not excerpt_supports_claim(padded_claim, _IDEMPOTENCY_BODY_EXCERPT)


def test_matching_stripe_db_excerpt_supports_claim() -> None:
    assert excerpt_supports_claim(_STRIPE_DB_CLAIM, _STRIPE_DB_EXCERPT)


def test_matching_webhook_excerpt_supports_claim() -> None:
    assert excerpt_supports_claim(_WEBHOOK_PENDING_CLAIM, _WEBHOOK_PENDING_EXCERPT)


def test_alias_and_paraphrase_excerpt_supports_claim() -> None:
    assert excerpt_supports_claim(_POSTGRES_PARAPHRASE_CLAIM, _POSTGRES_PARAPHRASE_EXCERPT)


def test_generic_claim_is_kept_when_overlap_cannot_be_judged() -> None:
    assert excerpt_supports_claim("Proceed.", _IDEMPOTENCY_BODY_EXCERPT)
    assert excerpt_supports_claim("Ship it.", _STRIPE_DB_EXCERPT)
