"""ONE canonical request per port, shared by the structural and behavioural contract suites.

Parity means the same request through every implementation, so the request needs a single home.
Retyping it per suite is how two "parity" tests end up asserting different things.

Each :class:`PortCase` answers three questions about one port:

* ``invoke``   : what a single canonical call to this port looks like;
* ``answered`` : what it means for the OFFLINE family to have actually answered (a port that
  returns ``None`` and records nothing has not answered, it has merely not raised);
* ``managed_refusal`` : what the MANAGED family must do when called with no cloud reachable.
  Never a silent success: either it refuses because it is unconfigured, or its lazy SDK import
  fails. Both are honest; returning as if the work happened is not.

Adding a port means adding a case here. ``test_port_parity.py`` fails the build if this table
and the port map ever disagree, so the touch list in ``CONTRIBUTING.md`` is enforced rather than
merely written down.

The ``answered`` predicates are deliberately specific to what each offline adapter is FOR. The
consent one, for instance, requires a decision id and the exact question echoed back, because a
consent adapter that returned an empty allow would satisfy any looser check while being the
single most dangerous thing in this repo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_eval_kit import EvalReport
from consent_preference_kit import ConsentDecision, ConsentQuery, SendRecord
from hex_service_kit.identity import IdentityError, Principal, RequestContext
from hex_service_kit.observability import TokenUsage
from speech_lexicon_kit import SpeechSynthesisRequest, SynthesisResult

from proactive_outreach.domain.kernel import (
    AuditEvent,
    Citation,
    Decision,
    Severity,
)
from proactive_outreach.domain.models import (
    DeliveryEnvelope,
    EventQuery,
    OutreachMessage,
    OutreachResult,
)
from proactive_outreach.ports.consent import ConsentUnavailableError
from proactive_outreach.ports.delivery import DeliveryRefusedError
from proactive_outreach.ports.drafting import DraftingUnavailableError
from proactive_outreach.ports.events import EventSourceUnavailableError

from tests.fixtures import sample_cases

#: The audit record every audit-port implementation is handed. Already redacted, as the port
#: requires: a raw identifier must never reach a WORM record.
CANONICAL_EVENT = AuditEvent(
    action="outreach_evaluate",
    actor=sample_cases.ACTOR,
    decision=Decision.ESCALATED,
    severity=Severity.CRITICAL,
    redacted_summary="outreach:fraud_hold:evt-t-0001 :: held for human review",
    citations=(Citation(source_id="event:evt-t-0001", title="fraud_hold", snippet="hold_ref"),),
)

#: The message every delivery implementation is handed, and the envelope that authorised it.
CANONICAL_MESSAGE = OutreachMessage(
    template_id="delivery_exception_reschedule",
    channel="chat",
    locale="en-AU",
    body="Delivery TRK-77120 could not be completed. The next attempt is 2026-08-12.",
    source="template",
    facts_used=("next_attempt_on", "tracking_ref"),
)

CANONICAL_ENVELOPE = DeliveryEnvelope(
    event_id=sample_cases.ROUTINE_EVENT.event_id,
    tenant=sample_cases.TENANT,
    subject_id=sample_cases.ROUTINE_EVENT.subject_id,
    channel="chat",
    purpose="service",
    consent_decision_id="cd-canonical-0001",
    cap_limit=3,
    sends_in_window=1,
    cap_remaining=2,
    as_of=sample_cases.OPEN_INSTANT.isoformat(),
)

#: The escalated result every review-router implementation is handed (rule R8's payload).
CANONICAL_RESULT = OutreachResult(
    case_ref="outreach:fraud_hold:evt-t-0001",
    event_id=sample_cases.CONSEQUENTIAL_EVENT.event_id,
    event_type=sample_cases.CONSEQUENTIAL_EVENT.event_type,
    tenant=sample_cases.TENANT,
    subject_id=sample_cases.CONSEQUENTIAL_EVENT.subject_id,
    severity=Severity.CRITICAL,
    decision=Decision.ESCALATED,
    summary="held for human review: consequential event",
    requires_human_review=True,
    message=OutreachMessage(
        template_id="fraud_hold_verify",
        channel="voice",
        locale="en-SG",
        body="A hold was placed on the card ending 3310 (reference FH-4471).",
    ),
    citations=(Citation(source_id="event:evt-t-0001", title="fraud_hold", snippet="hold_ref"),),
)

#: The inbound transport context every identity implementation is handed.
CANONICAL_CONTEXT = RequestContext(headers={"x-dev-persona": "auditor"})

#: The consent question every consent implementation is handed.
CANONICAL_CONSENT_QUERY = ConsentQuery(
    tenant=sample_cases.TENANT,
    subject_id=sample_cases.ROUTINE_EVENT.subject_id,
    purpose="service",
    channel="chat",
    market="AU",
    vertical="banking",
    as_of=sample_cases.OPEN_INSTANT.isoformat(),
)

#: The event query every detection implementation is handed.
CANONICAL_EVENT_QUERY = EventQuery(
    tenant=sample_cases.TENANT,
    as_of=sample_cases.OPEN_INSTANT.isoformat(),
    limit=50,
)

#: The synthesis request every text-to-speech implementation is handed.
CANONICAL_SYNTHESIS = SpeechSynthesisRequest(
    request_id="trg-canonical-0001",
    text="A hold was placed on the card ending 3310. Please verify in the app.",
    locale="en-SG",
)

#: The drafting brief every drafter is handed: a closed fact set and nothing else.
CANONICAL_DRAFT_REQUEST_FACTS = {"tracking_ref": "TRK-77120", "next_attempt_on": "2026-08-12"}


@dataclass(frozen=True, slots=True)
class PortCase:
    """One port's canonical call plus the two verdicts the parity suites need."""

    invoke: Callable[[Any], Any]
    answered: Callable[[Any, Any], bool]
    managed_refusal: tuple[type[BaseException], ...]
    detail: str


def _audit_invoke(adapter: Any) -> Any:
    return adapter.record(CANONICAL_EVENT)


def _audit_answered(adapter: Any, _result: Any) -> bool:
    stored = adapter.log.read_all()
    return bool(stored) and stored[-1]["actor"] == sample_cases.ACTOR and adapter.verify().ok


def _identity_invoke(adapter: Any) -> Any:
    return adapter.resolve(CANONICAL_CONTEXT)


def _identity_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, Principal) and bool(result.actor)


def _review_invoke(adapter: Any) -> Any:
    return adapter.route(CANONICAL_RESULT, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT)


def _review_answered(adapter: Any, result: Any) -> bool:
    return bool(result) and len(adapter.outbox.pending()) == 1


def _events_invoke(adapter: Any) -> Any:
    return adapter.detect(CANONICAL_EVENT_QUERY)


def _events_answered(_adapter: Any, result: Any) -> bool:
    """Detected events, in a STABLE order, actually typed. An empty tuple is not an answer."""
    if not isinstance(result, tuple) or not result:
        return False
    keys = [(event.occurred_at, event.event_id) for event in result]
    return keys == sorted(keys) and all(event.tenant == sample_cases.TENANT for event in result)


def _consent_invoke(adapter: Any) -> Any:
    return adapter.decide(CANONICAL_CONSENT_QUERY)


def _consent_answered(adapter: Any, result: Any) -> bool:
    """A real decision about THIS question, plus a send that moves the cap counter.

    Both halves matter. A consent adapter that answered but never counted a recorded send would
    let a frequency cap pass forever, which is a cap that exists only in the documentation.
    """
    if not isinstance(result, ConsentDecision) or not result.id:
        return False
    if (result.subject_id, result.purpose, result.channel) != (
        CANONICAL_CONSENT_QUERY.subject_id,
        CANONICAL_CONSENT_QUERY.purpose,
        CANONICAL_CONSENT_QUERY.channel,
    ):
        return False
    before = result.sends_in_window
    adapter.record_send(
        SendRecord(
            id="se-canonical-0001",
            tenant=CANONICAL_CONSENT_QUERY.tenant,
            subject_id=CANONICAL_CONSENT_QUERY.subject_id,
            channel=CANONICAL_CONSENT_QUERY.channel,
            purpose=CANONICAL_CONSENT_QUERY.purpose,
            decision_id=result.id,
            sent_at=CANONICAL_CONSENT_QUERY.as_of,
        )
    )
    return adapter.decide(CANONICAL_CONSENT_QUERY).sends_in_window == before + 1


def _drafting_invoke(adapter: Any) -> Any:
    from proactive_outreach.domain.models import DraftRequest

    return adapter.draft(
        DraftRequest(
            template_id="delivery_exception_reschedule",
            locale="en-AU",
            channel="chat",
            facts=dict(CANONICAL_DRAFT_REQUEST_FACTS),
            max_chars=320,
            required_facts=tuple(sorted(CANONICAL_DRAFT_REQUEST_FACTS)),
        )
    )


def _drafting_answered(_adapter: Any, result: Any) -> bool:
    """Raw text carrying every grounding fact. A drafter that returned "" has not drafted."""
    return isinstance(result, str) and all(
        value in result for value in CANONICAL_DRAFT_REQUEST_FACTS.values()
    )


def _delivery_invoke(adapter: Any) -> Any:
    return adapter.send(CANONICAL_MESSAGE, CANONICAL_ENVELOPE)


def _delivery_answered(adapter: Any, result: Any) -> bool:
    return bool(getattr(result, "reference", "")) and len(adapter.sent) == 1


def _speech_invoke(adapter: Any) -> Any:
    return adapter.synthesize(CANONICAL_SYNTHESIS)


def _speech_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, SynthesisResult) and bool(result.audio.uri)


def _tracer_invoke(adapter: Any) -> Any:
    with adapter.span("canonical.unit", action="canonical"):
        adapter.record_token_usage(TokenUsage(input_tokens=7, output_tokens=2), "canonical-model")
    return True


def _tracer_answered(adapter: Any, result: Any) -> bool:
    return bool(result)


def _evaluation_invoke(adapter: Any) -> Any:
    return adapter.evaluate("eval/datasets/canonical.jsonl")


def _evaluation_answered(adapter: Any, result: Any) -> bool:
    return isinstance(result, EvalReport) and result.dataset.endswith("canonical.jsonl")


CANONICAL_CALLS: dict[str, PortCase] = {
    "audit": PortCase(
        invoke=_audit_invoke,
        answered=_audit_answered,
        # The lazy `google.cloud` import is the first thing the managed sink does.
        managed_refusal=(ImportError,),
        detail="write one already-redacted WORM record",
    ),
    "consent": PortCase(
        invoke=_consent_invoke,
        answered=_consent_answered,
        # With no store configured the managed adapter must refuse. There is no local cache of
        # anybody's consent to fall back on, and inventing one is the whole point of not having
        # a second store.
        managed_refusal=(ConsentUnavailableError,),
        detail="answer one consent question and count a recorded send",
    ),
    "delivery": PortCase(
        invoke=_delivery_invoke,
        answered=_delivery_answered,
        managed_refusal=(DeliveryRefusedError,),
        detail="deliver one message carrying its consent decision id",
    ),
    "drafting": PortCase(
        invoke=_drafting_invoke,
        answered=_drafting_answered,
        managed_refusal=(DraftingUnavailableError,),
        detail="return a grounded candidate body",
    ),
    "events": PortCase(
        invoke=_events_invoke,
        answered=_events_answered,
        managed_refusal=(EventSourceUnavailableError,),
        detail="detect typed events in a stable order",
    ),
    "identity": PortCase(
        invoke=_identity_invoke,
        answered=_identity_answered,
        # No IAP assertion header offline, so the managed adapter refuses before importing.
        managed_refusal=(IdentityError,),
        detail="resolve a verified principal from transport context",
    ),
    "review_router": PortCase(
        invoke=_review_invoke,
        answered=_review_answered,
        # Rule R8: with no console configured the managed router must refuse, not swallow.
        managed_refusal=(RuntimeError,),
        detail="route one escalated result to human review",
    ),
    "speech": PortCase(
        invoke=_speech_invoke,
        answered=_speech_answered,
        managed_refusal=(RuntimeError,),
        detail="synthesise one notification into an audio reference",
    ),
    "tracer": PortCase(
        invoke=_tracer_invoke,
        answered=_tracer_answered,
        # NOTHING. Tracing is not essential to correctness, so the managed adapter must not refuse
        # offline either: with no SDK installed it degrades to a no-op and the traced body still
        # runs. An adapter that raised here would take a request down over a diagnostic.
        managed_refusal=(),
        detail="open one span and report the cost of a model call",
    ),
    "evaluation": PortCase(
        invoke=_evaluation_invoke,
        answered=_evaluation_answered,
        # The managed gate reaches Hrz4 over HTTP, which is unreachable offline.
        managed_refusal=(Exception,),
        detail="score one golden dataset through the promotion authority",
    ),
}
