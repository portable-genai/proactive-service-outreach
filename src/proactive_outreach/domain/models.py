"""Vertical artifact models: the events, triggers, decisions and messages this service produces.

The artifacts THIS vertical produces, as opposed to the vertical-neutral machinery in
``kernel.py``. The service's own name is deliberately not substituted into this docstring: a
rendered line whose length depends on ``friendly_name`` fails the repo's own format check for
no reason but the length of its name.

Nothing here decides anything. These are the value objects the pure engines in
``trigger_engine.py``, ``eligibility.py`` and ``drafting.py`` consume and return, and every one
of them is frozen, so a decision cannot be edited after the fact by the surface that received
it. Personal data is carried as a ``subject_id`` (a pseudonymous key), never as a name: the
free-text ``detail`` a source system supplies is the one field that may carry an identifier,
and it is redacted before it reaches a model, an audit record or the wire.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from hex_service_kit.enums import LenientStrEnum

from .kernel import Citation, Decision, Severity


class EventType(LenientStrEnum):
    """The operational events this service watches for. Nothing else triggers outreach."""

    FAILED_PAYMENT = "failed_payment"
    DELIVERY_EXCEPTION = "delivery_exception"
    EXPIRING_CARD = "expiring_card"
    FRAUD_HOLD = "fraud_hold"
    OUTAGE = "outage"


#: The channels a notification may go out on. ``chat`` rides the messaging adapter; ``voice``
#: rides the text-to-speech port from ``speech-lexicon-kit``. A channel outside this set is not
#: a channel this service knows how to deliver on, so the trigger engine refuses it.
DELIVERABLE_CHANNELS: frozenset[str] = frozenset({"chat", "voice"})


@dataclass(frozen=True, slots=True)
class ServiceEvent:
    """One operational event detected upstream, as the detection port hands it over.

    ``attributes`` carries the deterministic facts a message may quote (a masked card suffix,
    a retry date, an outage region). They are the ONLY values a drafted body may contain, which
    is what makes groundedness checkable rather than aspirational.
    """

    event_id: str
    event_type: EventType
    tenant: str
    subject_id: str
    occurred_at: str
    market: str
    locale: str
    detail: str = ""
    source_system: str = ""
    attributes: Mapping[str, str] = field(default_factory=dict)

    def attribute(self, name: str) -> str:
        """One attribute, or the empty string. Absence is never an error here; it is a fact."""
        return str(self.attributes.get(name, ""))


@dataclass(frozen=True, slots=True)
class EventQuery:
    """What the detection port is asked for: one tenant's events, at one explicit instant.

    ``as_of`` is carried on the QUERY as well as on the evaluation because a fixture or a
    warehouse view may describe an event relative to the moment being asked about ("declined 45
    minutes ago"). Passing the instant in keeps that resolution deterministic: the same query
    at the same ``as_of`` yields byte-identical events, which is what makes a sweep replayable.
    """

    tenant: str
    since: str = ""
    as_of: str = ""
    event_types: tuple[str, ...] = ()
    limit: int = 50


@dataclass(frozen=True, slots=True)
class OutreachTrigger:
    """The trigger engine's verdict about one event: fire, or do not, and exactly why.

    ``fired`` False is a normal outcome, not an error. A stale event, a rule nobody configured
    and a missing required attribute all land here, each with its own reason, and none of them
    reaches the model or the consent store.
    """

    trigger_id: str
    event_id: str
    event_type: EventType
    tenant: str
    subject_id: str
    market: str
    locale: str
    fired: bool
    template_id: str = ""
    purpose: str = ""
    channel: str = ""
    resolution_path: str = ""
    severity: Severity = Severity.LOW
    consequential: bool = False
    reasons: tuple[str, ...] = ()
    facts: Mapping[str, str] = field(default_factory=dict)
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """Whether this contact may be made, at one explicit instant, and on what evidence.

    ``consent_decision_id`` is the content hash the consent store returned. It travels onto the
    send envelope and into the audit record, so a message can be reconciled months later against
    a replay of the store rather than against this service's own memory of what it was told.
    """

    eligible: bool
    as_of: str
    reasons: tuple[str, ...] = ()
    consent_decision_id: str = ""
    consent_outcome: str = ""
    cap_limit: int = 0
    sends_in_window: int = 0
    cap_remaining: int = 0
    quiet_hours_window: str = ""
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class DraftRequest:
    """What a drafter is allowed to work from: the facts, and nothing else.

    There is no free-text prompt field on purpose. A drafter receives a template id, a locale,
    a channel and a closed set of already-redacted facts; anything it writes that is not in
    ``facts`` is ungrounded by construction and ``drafting.validate_draft`` rejects it.
    """

    template_id: str
    locale: str
    channel: str
    facts: Mapping[str, str]
    max_chars: int
    required_facts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OutreachMessage:
    """The message body that may go out, with where it came from written on it."""

    template_id: str
    channel: str
    locale: str
    body: str
    source: str = "template"
    facts_used: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class DeliveryEnvelope:
    """The provenance every send carries, whatever channel it goes out on.

    The consent decision id and the cap counters are on the ENVELOPE rather than looked up by
    the delivery adapter, so what authorised the contact travels with the contact and lands in
    the audit trail as one record instead of two that have to be joined by timestamp.
    """

    event_id: str
    tenant: str
    subject_id: str
    channel: str
    purpose: str
    consent_decision_id: str
    cap_limit: int
    sends_in_window: int
    cap_remaining: int
    as_of: str


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """What a delivery adapter returns: where it went, and what it cost to say so."""

    channel: str
    reference: str
    delivered_at: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class OutreachResult:
    """The whole decision about one event, from detection to delivery or refusal.

    ``case_ref`` is the human-readable handle a reviewer sees; it names the EVENT, never the
    person. ``requires_human_review`` is set by the deterministic engine and is honoured by
    every surface: a result carrying it is never delivered in the same breath.
    """

    case_ref: str
    event_id: str
    event_type: EventType
    tenant: str
    subject_id: str
    severity: Severity
    decision: Decision
    summary: str
    requires_human_review: bool
    delivered: bool = False
    delivery_ref: str = ""
    trigger: OutreachTrigger | None = None
    eligibility: EligibilityDecision | None = None
    message: OutreachMessage | None = None
    draft_discarded: bool = False
    citations: tuple[Citation, ...] = ()
