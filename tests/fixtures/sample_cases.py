"""Canonical synthetic cases, shared by the unit and contract suites.

Every party is obviously fictional and every address is an ``.example`` domain or an RFC 5737 /
RFC 3849 literal. One canonical routine event and one canonical consequential event are enough
for the contract suite: parity means the SAME request through every implementation, so the
request has to have one home rather than being retyped per test.

The two instants matter as much as the events. Quiet hours are the one rule that turns on WHEN
a decision is made, so the suite pins an open instant and a quiet one and never relies on the
wall clock: a test that passed before 22:00 and failed after it would be a test nobody trusts.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from proactive_outreach.domain.models import (
    EventType,
    ServiceEvent,
)

#: The verified principal the tests attribute work to (never a client-asserted actor).
ACTOR = "analyst@bank.example"

#: A tenant partition, so the outbound-review assertions are not all on the empty string.
TENANT = "demo-bank"

#: 06:00 UTC is 14:00 in SG, 16:00 in AU and 15:00 in JP: every market is open.
OPEN_INSTANT = datetime(2026, 8, 8, 6, 0, tzinfo=UTC)

#: 15:00 UTC is 23:00 in SG, 01:00 in AU and 00:00 in JP: every market is quiet.
QUIET_INSTANT = datetime(2026, 8, 8, 15, 0, tzinfo=UTC)

#: One hour before :data:`OPEN_INSTANT`: inside every trigger rule's freshness window.
RECENT = "2026-08-08T05:00:00+00:00"

#: An event that MUST be held for a human: a fraud hold is consequential in policy, so it is
#: drafted, routed under rule R8 and delivered by nobody until somebody approves it.
CONSEQUENTIAL_EVENT = ServiceEvent(
    event_id="evt-t-0001",
    event_type=EventType.FRAUD_HOLD,
    tenant=TENANT,
    subject_id="subj-000104",
    occurred_at=RECENT,
    market="SG",
    locale="en-SG",
    detail="Velocity rule placed a hold pending customer verification.",
    source_system="fraud-engine (FICTIONAL)",
    attributes={"hold_ref": "FH-4471", "card_suffix": "3310"},
)

#: An event that must NOT be held: manufacturing a review for a routine notification trains
#: reviewers to rubber-stamp, which is worse than not reviewing at all.
ROUTINE_EVENT = ServiceEvent(
    event_id="evt-t-0002",
    event_type=EventType.DELIVERY_EXCEPTION,
    tenant=TENANT,
    subject_id="subj-000102",
    occurred_at=RECENT,
    market="AU",
    locale="en-AU",
    detail="Courier could not access the building; parcel returned to the depot.",
    source_system="fulfilment-hub (FICTIONAL)",
    attributes={"tracking_ref": "TRK-77120", "next_attempt_on": "2026-08-12"},
)

#: A planted identifier, so a redaction assertion has an independent literal to look for
#: rather than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"

#: A routine event whose free-text detail carries personal data, for the redaction proofs.
PII_EVENT = ServiceEvent(
    event_id="evt-t-0003",
    event_type=EventType.FAILED_PAYMENT,
    tenant=TENANT,
    subject_id="subj-000101",
    occurred_at=RECENT,
    market="SG",
    locale="en-SG",
    detail=(
        f"Issuer declined the authorisation. Branch note from 192.0.2.10 records NRIC "
        f"{PLANTED_NRIC} and ops@bank.example, seen on host 2001:db8::7."
    ),
    source_system="payments-ledger (FICTIONAL)",
    attributes={"card_suffix": "4242", "retry_on": "2026-08-11"},
)

#: A subject the consent fixture set has never heard of: the fail-closed case.
UNKNOWN_SUBJECT_EVENT = ServiceEvent(
    event_id="evt-t-0004",
    event_type=EventType.FAILED_PAYMENT,
    tenant=TENANT,
    subject_id="subj-000702",
    occurred_at=RECENT,
    market="SG",
    locale="en-SG",
    detail="Issuer declined the authorisation.",
    source_system="payments-ledger (FICTIONAL)",
    attributes={"card_suffix": "7330", "retry_on": "2026-08-11"},
)


def as_recent(event: ServiceEvent) -> ServiceEvent:
    """The same event, timestamped five minutes ago. For the SERVING path only.

    A live API decides against the wall clock, which is what a live service does, so an API
    test needs an event that is fresh whenever the suite runs. Every other suite pins ``as_of``
    instead: a decision that depends on when the test happened to run is not a decision anybody
    can reason about, and this helper exists so exactly two files need the exception.

    The assertions the serving tests make are deliberately the ones that hold at any hour: a
    consequential trigger is held whatever the eligibility verdict, and a routine one never
    manufactures a review. Nothing here asserts a DELIVERY, because at 23:00 in Singapore there
    correctly is not one.
    """
    moment = datetime.now(UTC) - timedelta(minutes=5)
    return replace(event, occurred_at=moment.isoformat())
