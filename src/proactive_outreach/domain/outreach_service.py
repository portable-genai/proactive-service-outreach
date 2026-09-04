"""The outreach service: the fixed order in which one event becomes a message, or does not.

Every consequential step is a pure engine (:mod:`.trigger_engine`, :mod:`.eligibility`,
:mod:`.drafting`); this module owns only the ORDER, the ports and the audit write. The order is
the control, so it is written once, here, and every surface (API, CLI, agent tools, demo) goes
through it rather than reassembling the steps in its own sequence.

    redact -> trigger -> consent -> eligibility -> [draft] -> [validate] -> [deliver] -> audit

The square brackets are the point. Nothing inside them happens unless the step before it
answered yes:

1. **Redact first.** The source system's free-text ``detail`` is masked with the shared pattern pack
   before it is used for anything at all, so no raw identifier can reach a model, a citation, the
   wire or the immutable audit record. Redacting after a write would be too late, because the record
   is immutable by then. 2. **The model is not consulted until eligibility passes.** A contact that
   may not be made costs no tokens, sends no facts to a model and leaves no draft lying around. The
   drafting port is unreachable from the eligibility engine, and this method calls it only inside
   the ``eligible`` branch, which ``tests/unit/test_outreach_service.py`` proves with a spy that
   fails the build if it is ever called on a refused contact. 3. **Whatever the model writes is
   validated and discarded on failure.** A discarded draft is not repaired and not quietly replaced
   with a sent template: the deterministic body is prepared for a HUMAN, ``requires_human_review``
   is set, and nothing goes out. 4. **Consequential outreach never auto-executes** (rule R8). A
   fraud hold and an outage are marked consequential in policy: they are routed to the
   human-review-console and delivered by nobody until a human approves. The flag is set here; the
   routing is done by the caller in the same request, because a flag nobody reads is auto-execution
   with extra steps. 5. **The send is recorded back to the consent store.** A frequency cap counts
   recorded sends and nothing else, so a consumer that decides but never records passes every cap
   forever.
"""

from __future__ import annotations

from datetime import datetime

from pii_kit import redact

from ..ports.audit import AuditSinkPort
from ..ports.consent import (
    ConsentDecision,
    ConsentPort,
    ConsentQuery,
    ConsentUnavailableError,
    SendRecord,
)
from ..ports.delivery import MessageDeliveryPort
from ..ports.drafting import DraftingPort, DraftingUnavailableError
from ..ports.events import EventDetectionPort
from ..ports.observability import ObservabilityTracerPort
from ..ports.speech import SpeechSynthesisRequest, SpeechUnavailableError, TextToSpeechPort
from . import drafting as drafting_rules
from . import eligibility as eligibility_rules
from . import trigger_engine
from .kernel import AuditEvent, Citation, Decision, Severity, utcnow
from .models import (
    DeliveryEnvelope,
    EligibilityDecision,
    EventQuery,
    OutreachMessage,
    OutreachResult,
    OutreachTrigger,
    ServiceEvent,
)
from .pii import PII_PATTERNS
from .policy import DEFAULT_POLICY, OutreachPolicy

#: The vertical this service asks the consent store about. It is a SERVICE purpose, not a
#: marketing one, and the distinction is load-bearing: a subject who opted out of marketing has
#: not thereby opted out of being told their card was declined, and the store models the two
#: separately. Asking under the wrong purpose would be the wrong question, politely answered.
CONSENT_VERTICAL = "banking"

#: The channel used to bill the consent question when a trigger names the voice channel. The
#: store's vocabulary calls it ``voice``; this service's delivery layer calls it the same, so
#: the two need no translation table. Kept as a constant so the day they diverge there is one
#: place to map them.
_CHANNEL_VOICE = "voice"

#: One span per tenant sweep. Structural attributes only: see :meth:`OutreachService.evaluate`.
_SWEEP_SPAN = "outreach.sweep"

#: One span per evaluated event, nested inside the sweep's span when a sweep produced it.
_EVALUATE_SPAN = "outreach.evaluate"


class OutreachService:
    """Turn one detected event into a delivered message, a refusal, or a review."""

    def __init__(
        self,
        *,
        audit: AuditSinkPort,
        consent: ConsentPort,
        drafting: DraftingPort,
        delivery: MessageDeliveryPort,
        speech: TextToSpeechPort,
        tracer: ObservabilityTracerPort,
        events: EventDetectionPort | None = None,
        policy: OutreachPolicy | None = None,
    ) -> None:
        self._audit = audit
        self._consent = consent
        self._drafting = drafting
        self._delivery = delivery
        self._speech = speech
        # REQUIRED, and deliberately not an optional with a no-op default. A default would let a
        # new surface construct a service that emits nothing, and the deployment would look
        # traced because the exporter was bound. A surface that forgets the tracer fails to
        # construct instead, which is a failure somebody sees.
        self._tracer = tracer
        self._events = events
        self.policy = policy or DEFAULT_POLICY

    # ------------------------------------------------------------------ sweep
    def sweep(
        self, query: EventQuery, *, actor: str, as_of: datetime | None = None
    ) -> tuple[OutreachResult, ...]:
        """Evaluate every detected event for one tenant, in the order the port returned them.

        The sweep opens its own span and each event opens a child inside it. That nesting is
        DELIBERATE, and it is honest because a sweep is a FAN-OUT rather than an alias: the
        parent times the detection call plus N decisions, each child times exactly one, and the
        pair answers "was that sweep slow because of the feed or because of one event". The
        shape worth avoiding is a 1:1 wrapper, where a parent and its single child would time
        the same work twice and every trace would show two units of work where there was one.

        The attributes are structural only, for the reason set out on :meth:`evaluate`.
        """
        with self._tracer.span(
            _SWEEP_SPAN,
            action="sweep",
            actor=actor,
            tenant=query.tenant,
            limit=str(query.limit),
        ):
            if self._events is None:  # pragma: no cover - the container always binds the port
                raise RuntimeError("no event detection port is bound, so a sweep cannot run")
            moment = as_of or utcnow()
            return tuple(
                self.evaluate(event, actor=actor, as_of=moment)
                for event in self._events.detect(query)
            )

    # --------------------------------------------------------------- evaluate
    def evaluate(
        self, event: ServiceEvent, *, actor: str, as_of: datetime | None = None
    ) -> OutreachResult:
        """The whole decision for one event, at one explicit instant.

        The whole path runs inside one span, and its attributes are STRUCTURAL only: the action,
        the actor, the tenant, the trigger's event kind and the market. Never the subject id,
        never the source system's free-text ``detail``, never a drafted body and never a contact
        address. A trace backend is NOT the WORM audit trail: it has no redaction stage, no
        retention rule written against a regulator's requirement, and a far wider read audience
        than the audit store, so anything content-shaped that reaches a span has left the
        boundary the ``redact`` call below exists to hold, and it has left it silently. The
        collector strips a list of content keys it already knows, which is defence in depth for
        spans this catalog does not own and not a licence to emit content here.
        """
        with self._tracer.span(
            _EVALUATE_SPAN,
            action="evaluate",
            actor=actor,
            tenant=event.tenant,
            event_type=event.event_type.value,
            market=event.market,
        ):
            moment = as_of or utcnow()
            as_of_iso = moment.isoformat()
            redacted_detail = redact(event.detail, PII_PATTERNS)

            trigger = trigger_engine.evaluate(event, policy=self.policy, as_of=moment)
            consent = self._consent_decision(trigger, as_of_iso) if trigger.fired else None
            verdict = eligibility_rules.assess(
                trigger,
                consent=consent,
                policy=self.policy,
                as_of_iso=as_of_iso,
            )

            message: OutreachMessage | None = None
            draft_discarded = False
            draft_reasons: tuple[str, ...] = ()
            if verdict.eligible:
                message, draft_discarded, draft_reasons = self._draft(trigger)

            requires_review = (trigger.fired and trigger.consequential) or draft_discarded
            delivered = False
            delivery_ref = ""
            if verdict.eligible and message is not None and not requires_review:
                delivered, delivery_ref = self._deliver(trigger, verdict, message, as_of_iso)

            severity = trigger.severity if trigger.fired else Severity.LOW
            decision = Decision.ESCALATED if requires_review else Decision.ALLOWED
            case_ref = f"outreach:{event.event_type.value}:{event.event_id}"
            summary = self._summary(trigger, verdict, delivered, requires_review, draft_reasons)
            citations = self._citations(trigger, verdict, message, event, redacted_detail)

            self._audit.record(
                AuditEvent(
                    action="outreach_evaluate",
                    actor=actor,
                    decision=decision,
                    severity=severity,
                    redacted_summary=redact(
                        f"{case_ref} :: {summary} :: "
                        f"consent={verdict.consent_decision_id or 'none'} "
                        f"cap={verdict.sends_in_window}/{verdict.cap_limit} :: {redacted_detail}",
                        PII_PATTERNS,
                    ),
                    citations=citations,
                    timestamp=moment,
                )
            )

            return OutreachResult(
                case_ref=case_ref,
                event_id=event.event_id,
                event_type=event.event_type,
                tenant=event.tenant,
                subject_id=event.subject_id,
                severity=severity,
                decision=decision,
                summary=summary,
                requires_human_review=requires_review,
                delivered=delivered,
                delivery_ref=delivery_ref,
                trigger=trigger,
                eligibility=verdict,
                message=message,
                draft_discarded=draft_discarded,
                citations=citations,
            )

    # ------------------------------------------------------------------ steps
    def _consent_decision(self, trigger: OutreachTrigger, as_of_iso: str) -> ConsentDecision | None:
        """Ask the store, and turn ANY failure to obtain an answer into ``None``.

        ``None`` is read by the eligibility engine as ``consent_unknown``, which denies. There
        is deliberately no branch here that manufactures a permissive decision when the store
        is unreachable, and no default argument anywhere in this method that could become one.
        """
        query = ConsentQuery(
            tenant=trigger.tenant,
            subject_id=trigger.subject_id,
            purpose=trigger.purpose,
            channel=trigger.channel,
            market=trigger.market,
            vertical=CONSENT_VERTICAL,
            as_of=as_of_iso,
        )
        try:
            return self._consent.decide(query)
        except ConsentUnavailableError:
            return None

    def _draft(
        self, trigger: OutreachTrigger
    ) -> tuple[OutreachMessage | None, bool, tuple[str, ...]]:
        """Ask the drafter, validate, and fall back to the deterministic body on any failure.

        Returns ``(message, discarded, reasons)``. ``discarded`` True means a human must look at
        it before anything is sent, whatever the fallback body says.
        """
        request = drafting_rules.draft_request_for(trigger, policy=self.policy)
        deterministic = drafting_rules.render_template(request, policy=self.policy)
        try:
            raw = self._drafting.draft(request)
        except DraftingUnavailableError as exc:
            return deterministic, True, (f"drafter_unavailable:{exc}",)
        verdict = drafting_rules.validate_draft(raw, request, policy=self.policy)
        if verdict.message is None:
            return deterministic, True, verdict.reasons
        return verdict.message, False, verdict.reasons

    def _deliver(
        self,
        trigger: OutreachTrigger,
        verdict: EligibilityDecision,
        message: OutreachMessage,
        as_of_iso: str,
    ) -> tuple[bool, str]:
        """Send on the trigger's channel, then record the send so the cap counts it."""
        envelope = DeliveryEnvelope(
            event_id=trigger.event_id,
            tenant=trigger.tenant,
            subject_id=trigger.subject_id,
            channel=trigger.channel,
            purpose=trigger.purpose,
            consent_decision_id=verdict.consent_decision_id,
            cap_limit=verdict.cap_limit,
            sends_in_window=verdict.sends_in_window,
            cap_remaining=verdict.cap_remaining,
            as_of=as_of_iso,
        )
        if trigger.channel == _CHANNEL_VOICE:
            try:
                synthesis = self._speech.synthesize(
                    SpeechSynthesisRequest(
                        request_id=trigger.trigger_id,
                        text=message.body,
                        locale=trigger.locale,
                    )
                )
            except SpeechUnavailableError:
                return False, ""
            reference = synthesis.audio.uri
        else:
            reference = self._delivery.send(message, envelope).reference

        self._consent.record_send(
            SendRecord(
                id=f"se-{trigger.trigger_id}",
                tenant=trigger.tenant,
                subject_id=trigger.subject_id,
                channel=trigger.channel,
                purpose=trigger.purpose,
                decision_id=verdict.consent_decision_id,
                sent_at=as_of_iso,
            )
        )
        return True, reference

    # ---------------------------------------------------------------- summary
    @staticmethod
    def _summary(
        trigger: OutreachTrigger,
        verdict: EligibilityDecision,
        delivered: bool,
        requires_review: bool,
        draft_reasons: tuple[str, ...],
    ) -> str:
        if not trigger.fired:
            return f"no outreach: {', '.join(trigger.reasons)}"
        if not verdict.eligible:
            return f"not eligible: {', '.join(verdict.reasons)}"
        if requires_review:
            why = "consequential event" if trigger.consequential else "draft discarded"
            detail = f" ({', '.join(draft_reasons)})" if not trigger.consequential else ""
            return f"held for human review: {why}{detail}"
        if delivered:
            return f"delivered on {trigger.channel}: {trigger.resolution_path}"
        return "eligible but not delivered: the channel refused"

    @staticmethod
    def _citations(
        trigger: OutreachTrigger,
        verdict: EligibilityDecision,
        message: OutreachMessage | None,
        event: ServiceEvent,
        redacted_detail: str,
    ) -> tuple[Citation, ...]:
        """Every claim's source, de-duplicated by source id and in a stable order."""
        collected: list[Citation] = [
            Citation(
                source_id=f"event-detail:{event.event_id}",
                title="Source system detail (redacted)",
                snippet=redacted_detail[:160],
            ),
            *trigger.citations,
            *verdict.citations,
        ]
        if message is not None:
            collected.extend(message.citations)
        seen: set[str] = set()
        unique: list[Citation] = []
        for citation in collected:
            if citation.source_id in seen:
                continue
            seen.add(citation.source_id)
            unique.append(citation)
        return tuple(unique)
