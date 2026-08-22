"""The offline fixture data: synthetic service events and synthetic consent records.

ONE home for each, deliberately. A shipped JSON copy beside a Python copy is two homes for the
same facts and they drift the week after they are written, so the module constants below are
the source and ``event_fixture_path`` in the settings file points at a DIFFERENT file when a
deployment wants different events. There is no shipped duplicate to fall out of step with.

Every party, subject, reference and address here is obviously fictional: ``.example`` domains,
RFC 5737 / RFC 3849 documentation literals, invented reference numbers and a synthetic national
id that exists only so a redaction assertion has an independent literal to look for.

The set is chosen to exercise the whole decision surface, not to look tidy:

* one event per trigger type (failed payment, delivery exception, expiring card, fraud hold,
  outage), two of them consequential;
* a subject on the suppression list, so a policy refusal is visible;
* an event missing a required attribute, so the trigger engine's fail-closed branch fires;
* an event far past its window, so staleness is visible;
* a withdrawn consent, an UNKNOWN subject, a subject at the cap, and a decision carrying a
  reason token this deployment's client does not recognise. Those four are the fail-closed
  consent cases, and they are the reason the whole thing exists.
"""

from __future__ import annotations

from typing import Any

#: The planted identifier. It is in one event's free-text detail and nowhere else, so a test
#: that looks for it in an audit record, a draft or an outbound payload is asking an
#: independent question rather than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"

#: Events, as the fixture file format: ``occurred_minutes_ago`` is resolved against the query's
#: ``as_of`` so the set is always live AND always replayable, and ``occurred_at`` is the
#: absolute form for the one event that is meant to be stale whenever it is read.
FIXTURE_EVENTS: tuple[dict[str, Any], ...] = (
    {
        "event_id": "evt-4101",
        "event_type": "failed_payment",
        "subject_id": "subj-000101",
        "market": "SG",
        "locale": "en-SG",
        "source_system": "payments-ledger",
        "occurred_minutes_ago": 45,
        "detail": (
            "Card authorisation declined by the issuer. Branch note taken from 192.0.2.10 "
            f"records NRIC {PLANTED_NRIC} and ops@bank.example as the contact."
        ),
        "attributes": {"card_suffix": "4242", "retry_on": "2026-08-11"},
    },
    {
        "event_id": "evt-4102",
        "event_type": "delivery_exception",
        "subject_id": "subj-000102",
        "market": "AU",
        "locale": "en-AU",
        "source_system": "fulfilment-hub",
        "occurred_minutes_ago": 120,
        "detail": "Courier could not access the building; parcel returned to the depot.",
        "attributes": {"tracking_ref": "TRK-77120", "next_attempt_on": "2026-08-12"},
    },
    {
        "event_id": "evt-4103",
        "event_type": "expiring_card",
        "subject_id": "subj-000103",
        "market": "JP",
        "locale": "ja-JP",
        "source_system": "card-lifecycle",
        "occurred_minutes_ago": 600,
        "detail": "Scheduled reissue window opened for a card nearing expiry.",
        "attributes": {"card_suffix": "8871", "expires_on": "2026-09-30"},
    },
    {
        "event_id": "evt-4104",
        "event_type": "fraud_hold",
        "subject_id": "subj-000104",
        "market": "SG",
        "locale": "en-SG",
        "source_system": "fraud-engine",
        "occurred_minutes_ago": 20,
        "detail": "Velocity rule placed a hold pending customer verification.",
        "attributes": {"hold_ref": "FH-4471", "card_suffix": "3310"},
    },
    {
        "event_id": "evt-4105",
        "event_type": "outage",
        "subject_id": "subj-000105",
        "market": "AU",
        "locale": "en-AU",
        "source_system": "service-health",
        "occurred_minutes_ago": 30,
        "detail": "Partial degradation reported by the payments platform.",
        "attributes": {"outage_ref": "OUT-3312", "affected_service": "Card payments"},
    },
    {
        "event_id": "evt-4106",
        "event_type": "failed_payment",
        "subject_id": "subj-000900",
        "market": "SG",
        "locale": "en-SG",
        "source_system": "payments-ledger",
        "occurred_minutes_ago": 60,
        "detail": "Card authorisation declined by the issuer.",
        "attributes": {"card_suffix": "5150", "retry_on": "2026-08-11"},
    },
    {
        "event_id": "evt-4107",
        "event_type": "delivery_exception",
        "subject_id": "subj-000106",
        "market": "AU",
        "locale": "en-AU",
        "source_system": "fulfilment-hub",
        "occurred_minutes_ago": 90,
        "detail": "Exception raised with no tracking reference attached.",
        "attributes": {"next_attempt_on": "2026-08-12"},
    },
    {
        "event_id": "evt-4108",
        "event_type": "outage",
        "subject_id": "subj-000107",
        "market": "AU",
        "locale": "en-AU",
        "source_system": "service-health",
        "occurred_at": "2020-01-01T00:00:00+00:00",
        "detail": "Historic incident replayed from an archive load.",
        "attributes": {"outage_ref": "OUT-0001", "affected_service": "Statements"},
    },
    {
        "event_id": "evt-4109",
        "event_type": "failed_payment",
        "subject_id": "subj-000701",
        "market": "SG",
        "locale": "en-SG",
        "source_system": "payments-ledger",
        "occurred_minutes_ago": 35,
        "detail": "Card authorisation declined by the issuer.",
        "attributes": {"card_suffix": "6120", "retry_on": "2026-08-11"},
    },
    {
        "event_id": "evt-4110",
        "event_type": "failed_payment",
        "subject_id": "subj-000702",
        "market": "SG",
        "locale": "en-SG",
        "source_system": "payments-ledger",
        "occurred_minutes_ago": 25,
        "detail": "Card authorisation declined by the issuer.",
        "attributes": {"card_suffix": "7330", "retry_on": "2026-08-11"},
    },
    {
        "event_id": "evt-4111",
        "event_type": "delivery_exception",
        "subject_id": "subj-000703",
        "market": "AU",
        "locale": "en-AU",
        "source_system": "fulfilment-hub",
        "occurred_minutes_ago": 55,
        "detail": "Second failed delivery attempt for the same consignment.",
        "attributes": {"tracking_ref": "TRK-77121", "next_attempt_on": "2026-08-13"},
    },
    {
        "event_id": "evt-4112",
        "event_type": "delivery_exception",
        "subject_id": "subj-000704",
        "market": "AU",
        "locale": "en-AU",
        "source_system": "fulfilment-hub",
        "occurred_minutes_ago": 50,
        "detail": "Courier could not access the building; parcel returned to the depot.",
        "attributes": {"tracking_ref": "TRK-77122", "next_attempt_on": "2026-08-13"},
    },
)


#: Consent records as the offline store answers them. ``outcome`` and ``reasons`` are the store's
#: own vocabulary (see ``consent-preference-kit``); ``sends_in_window`` and ``cap_limit`` are the
#: counters a frequency cap is computed from. A subject ABSENT from this table is unknown, and an
#: unknown subject is a denial: there is no default row and no permissive fallback.
FIXTURE_CONSENT: dict[str, dict[str, Any]] = {
    "subj-000101": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "within_frequency_cap"],
        "sends_in_window": 0,
        "cap_limit": 5,
    },
    "subj-000102": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "within_frequency_cap"],
        "sends_in_window": 1,
        "cap_limit": 5,
    },
    "subj-000103": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "no_frequency_cap_configured"],
        "sends_in_window": 0,
        "cap_limit": None,
    },
    "subj-000104": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "within_frequency_cap"],
        "sends_in_window": 0,
        "cap_limit": 2,
    },
    "subj-000105": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "within_frequency_cap"],
        "sends_in_window": 0,
        "cap_limit": 5,
    },
    "subj-000106": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "within_frequency_cap"],
        "sends_in_window": 0,
        "cap_limit": 5,
    },
    "subj-000107": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "within_frequency_cap"],
        "sends_in_window": 0,
        "cap_limit": 5,
    },
    "subj-000900": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "within_frequency_cap"],
        "sends_in_window": 0,
        "cap_limit": 5,
    },
    # Withdrawn: the store answers, and the answer is no.
    "subj-000701": {
        "outcome": "denied",
        "reasons": ["consent_withdrawn"],
        "sends_in_window": 0,
        "cap_limit": 5,
    },
    # subj-000702 is deliberately ABSENT: an unknown subject must deny, not default.
    # At this deployment's cap even though the store's own (looser) cap would allow it. The
    # engine takes the smaller of the two limits, so neither authority is widened by the other.
    "subj-000703": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "within_frequency_cap"],
        "sends_in_window": 3,
        "cap_limit": 5,
    },
    # An allow carrying a reason token this pinned client has never heard of. It is treated as a
    # refusal: a store newer than its client is far likelier to have added a refusal than a
    # pleasantry, and guessing which is which is not a thing to do with somebody's consent.
    "subj-000704": {
        "outcome": "allowed",
        "reasons": ["consent_granted", "channel_opted_in", "seasonal_preference_pending"],
        "sends_in_window": 0,
        "cap_limit": 5,
    },
}
