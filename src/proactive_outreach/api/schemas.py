"""API request/response schemas (Pydantic) mapped to/from the pure-domain models.

The response is deliberately verbose. A caller receives not only whether a customer was
contacted but the whole chain that decided it: which trigger fired, which consent decision id
authorised it, what the cap counters were, which quiet-hours window applied and every reason
that refused. A proactive-outreach service whose API answered only ``sent: true`` would make
every later question ("why did this person get three of these?") a log-archaeology exercise.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..domain.models import (
    EligibilityDecision,
    OutreachMessage,
    OutreachResult,
    OutreachTrigger,
    ServiceEvent,
)


class EventRequest(BaseModel):
    """One operational event, as a caller submits it for evaluation."""

    event_id: str
    event_type: str
    subject_id: str
    occurred_at: str
    market: str
    locale: str = "en-SG"
    detail: str = ""
    source_system: str = ""
    attributes: dict[str, str] = {}


class SweepRequest(BaseModel):
    """Ask the detection port for a tenant's events and evaluate every one of them.

    There is deliberately NO ``as_of`` field. See ``api/app.py``: the instant a decision is
    made against is the service's, never the caller's, because quiet hours turn on it.
    """

    since: str = ""
    event_types: list[str] = []
    limit: int = 50


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class TriggerModel(BaseModel):
    trigger_id: str
    fired: bool
    template_id: str = ""
    purpose: str = ""
    channel: str = ""
    resolution_path: str = ""
    severity: str = ""
    consequential: bool = False
    reasons: list[str] = []

    @classmethod
    def from_domain(cls, trigger: OutreachTrigger) -> TriggerModel:
        return cls(
            trigger_id=trigger.trigger_id,
            fired=trigger.fired,
            template_id=trigger.template_id,
            purpose=trigger.purpose,
            channel=trigger.channel,
            resolution_path=trigger.resolution_path,
            severity=trigger.severity.value,
            consequential=trigger.consequential,
            reasons=list(trigger.reasons),
        )


class EligibilityModel(BaseModel):
    eligible: bool
    as_of: str
    reasons: list[str] = []
    #: The content hash the consent store returned. Quote it on any question about this send.
    consent_decision_id: str = ""
    consent_outcome: str = ""
    cap_limit: int = 0
    sends_in_window: int = 0
    cap_remaining: int = 0
    quiet_hours_window: str = ""

    @classmethod
    def from_domain(cls, verdict: EligibilityDecision) -> EligibilityModel:
        return cls(
            eligible=verdict.eligible,
            as_of=verdict.as_of,
            reasons=list(verdict.reasons),
            consent_decision_id=verdict.consent_decision_id,
            consent_outcome=verdict.consent_outcome,
            cap_limit=verdict.cap_limit,
            sends_in_window=verdict.sends_in_window,
            cap_remaining=verdict.cap_remaining,
            quiet_hours_window=verdict.quiet_hours_window,
        )


class MessageModel(BaseModel):
    template_id: str
    channel: str
    locale: str
    body: str
    #: ``template`` or ``model``. A reviewer needs to know which wrote the words.
    source: str

    @classmethod
    def from_domain(cls, message: OutreachMessage) -> MessageModel:
        return cls(
            template_id=message.template_id,
            channel=message.channel,
            locale=message.locale,
            body=message.body,
            source=message.source,
        )


class EventModel(BaseModel):
    """A detected event, as the listing endpoint reports it. ``detail`` is deliberately absent."""

    event_id: str
    event_type: str
    subject_id: str
    occurred_at: str
    market: str
    locale: str
    source_system: str = ""

    @classmethod
    def from_domain(cls, event: ServiceEvent) -> EventModel:
        return cls(
            event_id=event.event_id,
            event_type=event.event_type.value,
            subject_id=event.subject_id,
            occurred_at=event.occurred_at,
            market=event.market,
            locale=event.locale,
            source_system=event.source_system,
        )


class OutreachResponse(BaseModel):
    case_ref: str
    event_id: str
    event_type: str
    severity: str
    decision: str
    summary: str
    requires_human_review: bool
    delivered: bool = False
    delivery_ref: str = ""
    draft_discarded: bool = False
    #: Where the escalation WENT (rule R8): the Hrz7 review id, or the local queue reference.
    #: Empty only when the result did not escalate. A caller can tell a routed escalation from
    #: a flag that stopped here, which is the whole point of the rule.
    review_ref: str = ""
    trigger: TriggerModel | None = None
    eligibility: EligibilityModel | None = None
    message: MessageModel | None = None
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(cls, result: OutreachResult, *, review_ref: str = "") -> OutreachResponse:
        return cls(
            case_ref=result.case_ref,
            event_id=result.event_id,
            event_type=result.event_type.value,
            severity=result.severity.value,
            decision=result.decision.value,
            summary=result.summary,
            requires_human_review=result.requires_human_review,
            delivered=result.delivered,
            delivery_ref=result.delivery_ref,
            draft_discarded=result.draft_discarded,
            review_ref=review_ref,
            trigger=TriggerModel.from_domain(result.trigger) if result.trigger else None,
            eligibility=(
                EligibilityModel.from_domain(result.eligibility) if result.eligibility else None
            ),
            message=MessageModel.from_domain(result.message) if result.message else None,
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in result.citations
            ],
        )


class HealthResponse(BaseModel):
    status: str
    profile: str
    region: str
    #: Provenance the UI banner states on every page: where the runtime sits and which model
    #: answers. Both are read off the service because the browser cannot know either.
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"
