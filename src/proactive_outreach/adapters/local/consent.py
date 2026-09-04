"""Local ConsentPort: an offline stand-in for the marketing-compliance-gate consent and preference
store.

It answers from a synthetic record set (:mod:`.fixtures`) using the SAME wire types the real
store serves, so the offline gate exercises the real parsing, the real vocabulary and the real
fail-closed rules rather than a kinder second implementation of them.

Three properties make it a stand-in for the store and not a bypass of it:

* **an unknown subject DENIES.** There is no default row, no ``setdefault`` and no permissive
  fallback in this module. A subject the fixture set has never heard of gets a real, cited
  denial naming ``consent_unknown``, which is exactly what the store does;
* **the decision id is a content hash of the question and the answer**, mirroring the store's
  own rule, so a message sent offline reconciles the same way a message sent against the live
  store does; and
* **recorded sends move the counters.** ``record_send`` appends to an in-process ledger and the
  next decision counts it, so a frequency cap actually binds in the demo and in the eval
  instead of being a number nobody increments.
"""

from __future__ import annotations

import hashlib
from typing import Any

from consent_preference_kit import (
    OUTCOME_ALLOWED,
    OUTCOME_DENIED,
    Citation,
    ConsentDecision,
    ConsentQuery,
    SendRecord,
)

from ...config import Settings
from .fixtures import FIXTURE_CONSENT

#: The reason the store returns for a subject it holds no record for. Named here rather than
#: written inline: the eligibility engine, the eval oracle and the demo all read it.
REASON_UNKNOWN_SUBJECT = "consent_unknown"


def _decision_id(query: ConsentQuery, outcome: str, reasons: tuple[str, ...]) -> str:
    """A content hash of the question AND the answer, so an id identifies a decision."""
    material = "|".join(
        (
            query.tenant,
            query.subject_id,
            query.purpose,
            query.channel,
            query.market,
            query.vertical,
            query.as_of,
            outcome,
            ",".join(reasons),
        )
    )
    return "cd-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _build(
    query: ConsentQuery, outcome: str, record: dict[str, Any], extra_sends: int
) -> ConsentDecision:
    reasons = tuple(str(reason) for reason in record.get("reasons", ()))
    sends = int(record.get("sends_in_window", 0) or 0) + extra_sends
    cap_limit = record.get("cap_limit")
    return ConsentDecision(
        id=_decision_id(query, outcome, reasons),
        tenant=query.tenant,
        subject_id=query.subject_id,
        purpose=query.purpose,
        channel=query.channel,
        outcome=outcome,
        reasons=reasons,
        market=query.market,
        vertical=query.vertical,
        as_of=query.as_of,
        explanation=str(record.get("explanation", "") or ""),
        cap_limit=int(cap_limit) if isinstance(cap_limit, int) else None,
        sends_in_window=sends,
        citations=(
            Citation(
                source_id=f"consent-record:{query.subject_id}",
                title="Consent and preference record (offline fixture)",
                snippet=f"purpose={query.purpose}; channel={query.channel}; outcome={outcome}",
            ),
        ),
    )


class LocalConsentAdapter:
    """Answer consent questions from the synthetic record set, failing closed on the unknown."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        #: (subject_id, purpose, channel) -> sends recorded by THIS process since start-up.
        self._recorded: dict[tuple[str, str, str], int] = {}
        self._ledger: list[SendRecord] = []

    def decide(self, query: ConsentQuery) -> ConsentDecision:
        """The store's answer for one question. Never raises; an unknown subject is a denial."""
        record = FIXTURE_CONSENT.get(query.subject_id)
        extra = self._recorded.get((query.subject_id, query.purpose, query.channel), 0)
        if record is None:
            return _build(
                query,
                OUTCOME_DENIED,
                {"reasons": [REASON_UNKNOWN_SUBJECT], "sends_in_window": 0, "cap_limit": None},
                extra,
            )
        outcome = str(record.get("outcome", "") or "")
        # No default of the allow token anywhere on this path: an absent or unrecognised outcome
        # in the fixture data must arrive as a refusal, exactly as it would off the wire.
        resolved = OUTCOME_ALLOWED if outcome == OUTCOME_ALLOWED else OUTCOME_DENIED
        return _build(query, resolved, dict(record), extra)

    def record_send(self, send: SendRecord) -> str:
        """Count one delivered contact, so the next decision sees a moved cap counter."""
        key = (send.subject_id, send.purpose, send.channel)
        self._recorded[key] = self._recorded.get(key, 0) + 1
        self._ledger.append(send)
        return send.id

    @property
    def ledger(self) -> tuple[SendRecord, ...]:
        """Every send this process recorded, for inspection in tests, the eval and the demo."""
        return tuple(self._ledger)
