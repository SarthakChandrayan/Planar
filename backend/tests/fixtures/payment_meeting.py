PAYMENT_MEETING_TRANSCRIPT = """
Payments platform weekly — 2026-09-04

Priya: We need to lock the card-not-present path today.
Omar: Agreed. We will route all new card-not-present charges through Stripe PaymentIntents.
Priya: Confirmed. That is the decision.

Omar: Settlement cut-off stays at 22:00 UTC. We are not moving it this quarter.
Priya: Yes. Locked.

Priya: POST /v1/charges must honor an Idempotency-Key header. Checkout already retries.
Omar: Failed captures must return a machine-readable decline_code so support is not guessing.

Priya: Concrete work: add idempotency middleware to POST /v1/charges.
Omar: Done means a repeated request with the same key and body returns the original charge.
Priya: And a repeated request with the same key and a different body returns HTTP 409.
Omar: Keys expire after 24 hours.

Omar: Also document capture decline codes for client teams.

Priya: Risk: if the webhook handler and the nightly capture worker both settle the same PaymentIntent, we will double-charge customers.
Omar: That is a real failure mode. We still have two writers on capture.

Omar: Should Apple Pay go out with this PaymentIntents rollout, or is that a follow-up?
Priya: Unresolved. Mobile still uses Braintree for wallets. We do not have a decision.

Omar: We could use Kafka for the settlement event bus.
Priya: Let's not decide that today. Park it.

Omar: Maybe we should add Redis for storing idempotency keys.
Priya: No. Use the existing Postgres unique constraint. Redis is not accepted.
""".strip()

DECISION_MEETING_TRANSCRIPT = """
Lin: We will freeze the public checkout API at /v1 until October.
Sam: Agreed. That is locked. No breaking changes on /v1 this month.
""".strip()

REQUIREMENT_MEETING_TRANSCRIPT = """
Lin: The refund endpoint must reject amounts greater than the original capture.
Sam: Yes. That is a hard product requirement, not optional.
""".strip()

TASK_MEETING_TRANSCRIPT = """
Lin: Please add a dead-letter queue for failed capture jobs this sprint.
Sam: Work item is implement the DLQ consumer. Done when a failed capture is retried three times then parked.
""".strip()

RISK_MEETING_TRANSCRIPT = """
Lin: I am worried that logging raw PANs on declined auths will expand our PCI scope.
Sam: That concern is valid. Staging already had a declined PAN in the logs last week.
""".strip()

OPEN_QUESTION_MEETING_TRANSCRIPT = """
Lin: Do we still need Braintree after the Stripe cutover, or can we drop it next quarter?
Sam: Unknown. Legal has not answered the contract question. No decision today.
""".strip()

SUGGESTION_MEETING_TRANSCRIPT = """
Lin: We could use Kafka for the settlement event bus.
Sam: Maybe we should add Redis for storing idempotency keys.
Priya: We are not deciding infrastructure today. Those are just ideas. The only locked item is that settlement cut-off stays at 22:00 UTC.
Sam: Agreed. Settlement cut-off stays at 22:00 UTC.
""".strip()
