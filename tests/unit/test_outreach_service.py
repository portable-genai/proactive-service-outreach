"""The pipeline's ORDER, which is the control this service actually sells.

Three claims are made here that no single engine can make on its own, because each is about what
happens BETWEEN two steps:

1. the model is not reachable until eligibility passes, proved with a spy that fails the build
   if the drafting port is touched on a refused contact;
2. personal data is redacted before it is written, before it is cited and before it is drafted
   from, proved with an identifier planted in the one field that can carry one; and
3. a consequential result is never delivered, however clean its consent was.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from proactive_outreach.config import Container, build_container
from proactive_outreach.domain.models import DraftRequest, EventQuery
from proactive_outreach.domain.outreach_service import OutreachService
from proactive_outreach.ports.drafting import DraftingUnavailableError

from tests.conftest import build_service, local_settings
from tests.fixtures import sample_cases

_AS_OF = sample_cases.OPEN_INSTANT


class SpyDrafter:
    """Records every call. The offline drafter it wraps is the real one."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.calls: list[DraftRequest] = []

    def draft(self, request: DraftRequest) -> str:
        self.calls.append(request)
        return str(self._inner.draft(request))  # type: ignore[attr-defined]


class BadDrafter:
    """A drafter that returns something the validator must reject."""

    def draft(self, request: DraftRequest) -> str:
        return '{"body": "Your card was declined for 4,995 dollars. Call us."}'


class BrokenDrafter:
    """A drafter that is simply not there."""

    def draft(self, request: DraftRequest) -> str:
        raise DraftingUnavailableError("no drafter is configured")


def _service(container: Container, **ports: object) -> OutreachService:
    return OutreachService(
        audit=ports.get("audit", container.audit),  # type: ignore[arg-type]
        consent=ports.get("consent", container.consent),  # type: ignore[arg-type]
        drafting=ports.get("drafting", container.drafting),  # type: ignore[arg-type]
        delivery=ports.get("delivery", container.delivery),  # type: ignore[arg-type]
        speech=ports.get("speech", container.speech),  # type: ignore[arg-type]
        tracer=container.tracer,
        events=container.events,
        policy=container.settings.policy,
    )


# --------------------------------------------------------------------------- #
# The order
# --------------------------------------------------------------------------- #
def test_the_model_is_never_called_for_a_contact_that_may_not_be_made() -> None:
    """The claim the whole ordering exists for. A refused contact costs no tokens and leaks
    no facts to a model."""
    container = build_container(local_settings())
    spy = SpyDrafter(container.drafting)
    result = _service(container, drafting=spy).evaluate(
        sample_cases.UNKNOWN_SUBJECT_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    assert result.eligibility is not None and result.eligibility.eligible is False
    assert spy.calls == [], "the drafting port was called for a contact that was refused"
    assert result.message is None
    assert result.delivered is False


def test_the_model_is_called_once_eligibility_passes() -> None:
    container = build_container(local_settings())
    spy = SpyDrafter(container.drafting)
    result = _service(container, drafting=spy).evaluate(
        sample_cases.ROUTINE_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    assert len(spy.calls) == 1
    assert result.delivered is True
    # The brief carries the closed fact set and NOT the event's free text.
    assert set(spy.calls[0].facts) == {"tracking_ref", "next_attempt_on"}


def test_a_delivered_message_carries_the_consent_decision_id_and_the_cap_counters() -> None:
    container = build_container(local_settings())
    result = build_service(container).evaluate(
        sample_cases.ROUTINE_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    assert result.delivered is True
    ((message, envelope),) = container.delivery.sent
    assert envelope.consent_decision_id == result.eligibility.consent_decision_id  # type: ignore[union-attr]
    assert envelope.cap_limit == 3
    assert envelope.cap_remaining == 2
    assert message.body


def test_a_delivered_message_is_recorded_back_so_the_cap_actually_binds() -> None:
    """A consumer that decides but never records passes every cap forever."""
    container = build_container(local_settings())
    service = build_service(container)
    service.evaluate(sample_cases.ROUTINE_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF)
    assert len(container.consent.ledger) == 1
    second = service.evaluate(
        replace(sample_cases.ROUTINE_EVENT, event_id="evt-t-0002b"),
        actor=sample_cases.ACTOR,
        as_of=_AS_OF,
    )
    assert second.eligibility is not None
    assert second.eligibility.sends_in_window == 2, "the recorded send did not move the counter"


def test_a_consequential_event_is_held_and_delivered_by_nobody() -> None:
    container = build_container(local_settings())
    result = build_service(container).evaluate(
        sample_cases.CONSEQUENTIAL_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    assert result.requires_human_review is True
    assert result.delivered is False
    assert result.message is not None, "a reviewer needs the proposed words to approve them"
    assert container.consent.ledger == (), "a held outreach was counted against the cap"


def test_a_rejected_draft_is_discarded_and_the_notification_waits_for_a_human() -> None:
    container = build_container(local_settings())
    result = _service(container, drafting=BadDrafter()).evaluate(
        sample_cases.ROUTINE_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    assert result.draft_discarded is True
    assert result.requires_human_review is True
    assert result.delivered is False
    # The deterministic body is prepared FOR THE HUMAN, not sent instead.
    assert result.message is not None and result.message.source == "template"


def test_an_absent_drafter_holds_the_notification_rather_than_sending_a_template() -> None:
    container = build_container(local_settings())
    result = _service(container, drafting=BrokenDrafter()).evaluate(
        sample_cases.ROUTINE_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    assert result.draft_discarded is True
    assert result.delivered is False


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #
def test_personal_data_is_masked_before_the_audit_write() -> None:
    container = build_container(local_settings())
    build_service(container).evaluate(
        sample_cases.PII_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    records = container.audit.log.read_all()
    assert records, "an audit event should have been recorded"
    summary = str(records[-1]["redacted_summary"])
    assert sample_cases.PLANTED_NRIC not in summary
    assert "REDACTED" in summary
    assert records[-1]["actor"] == sample_cases.ACTOR


def test_personal_data_never_reaches_a_citation_or_a_message() -> None:
    container = build_container(local_settings())
    result = build_service(container).evaluate(
        sample_cases.PII_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    rendered = repr(result)
    assert sample_cases.PLANTED_NRIC not in rendered
    assert "ops@bank.example" not in rendered


# --------------------------------------------------------------------------- #
# Every decision is recorded, including the refusals
# --------------------------------------------------------------------------- #
def test_a_refusal_is_audited_as_fully_as_a_send() -> None:
    """ "Why was this person NOT contacted" is a question somebody asks after an incident."""
    container = build_container(local_settings())
    build_service(container).evaluate(
        sample_cases.UNKNOWN_SUBJECT_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    records = container.audit.log.read_all()
    assert len(records) == 1
    assert "consent_unknown" in str(records[-1]["redacted_summary"])


def test_every_result_carries_at_least_one_citation() -> None:
    container = build_container(local_settings())
    service = build_service(container)
    for event in (
        sample_cases.ROUTINE_EVENT,
        sample_cases.CONSEQUENTIAL_EVENT,
        sample_cases.UNKNOWN_SUBJECT_EVENT,
    ):
        result = service.evaluate(event, actor=sample_cases.ACTOR, as_of=_AS_OF)
        assert result.citations, f"{event.event_id} produced an uncited result"


def test_the_same_event_at_the_same_instant_decides_the_same_way_twice() -> None:
    """Replayability: two fresh containers, one instant, byte-identical verdicts."""
    first = build_service(build_container(local_settings())).evaluate(
        sample_cases.CONSEQUENTIAL_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    second = build_service(build_container(local_settings())).evaluate(
        sample_cases.CONSEQUENTIAL_EVENT, actor=sample_cases.ACTOR, as_of=_AS_OF
    )
    assert first.summary == second.summary
    assert first.trigger is not None and second.trigger is not None
    assert first.trigger.trigger_id == second.trigger.trigger_id
    assert first.eligibility is not None and second.eligibility is not None
    assert first.eligibility.consent_decision_id == second.eligibility.consent_decision_id


# --------------------------------------------------------------------------- #
# The sweep
# --------------------------------------------------------------------------- #
def test_a_sweep_evaluates_every_detected_event_and_refuses_most_of_them() -> None:
    """The fixture feed is chosen so a sweep exercises the whole decision surface."""
    container = build_container(local_settings())
    query = EventQuery(tenant=sample_cases.TENANT, as_of=_AS_OF.isoformat(), limit=50)
    results = build_service(container).sweep(query, actor=sample_cases.ACTOR, as_of=_AS_OF)
    assert len(results) >= 10
    delivered = [r for r in results if r.delivered]
    held = [r for r in results if r.requires_human_review]
    refused = [r for r in results if not r.delivered and not r.requires_human_review]
    assert delivered and held and refused, "the fixture feed stopped covering all three outcomes"
    assert all(r.delivered is False for r in held), "a held result was delivered"


def test_a_sweep_needs_an_event_port_and_says_so_rather_than_returning_nothing() -> None:
    container = build_container(local_settings())
    service = OutreachService(
        audit=container.audit,
        consent=container.consent,
        drafting=container.drafting,
        delivery=container.delivery,
        speech=container.speech,
        tracer=container.tracer,
        policy=container.settings.policy,
    )
    with pytest.raises(RuntimeError):
        service.sweep(EventQuery(tenant=sample_cases.TENANT), actor=sample_cases.ACTOR)
