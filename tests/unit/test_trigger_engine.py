"""The trigger engine: five ways to refuse, one way to fire, and no clock anywhere.

The refusals get more attention than the success on purpose. "Fires on a well-formed event" is
the easy half; the value of this engine is that it does NOT fire on a stale event, an event
missing the fact the message would have to quote, or an event type nobody wrote a rule for. Each
of those, if it fired, ends with a customer receiving something wrong or something late.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from proactive_outreach.domain import trigger_engine
from proactive_outreach.domain.kernel import Severity
from proactive_outreach.domain.models import EventType, ServiceEvent
from proactive_outreach.domain.policy import DEFAULT_POLICY, OutreachPolicy

from tests.fixtures import sample_cases

_AS_OF = sample_cases.OPEN_INSTANT


def _evaluate(event: ServiceEvent, policy: OutreachPolicy = DEFAULT_POLICY):  # type: ignore[no-untyped-def]
    return trigger_engine.evaluate(event, policy=policy, as_of=_AS_OF)


def test_a_well_formed_event_fires_with_its_configured_rule() -> None:
    trigger = _evaluate(sample_cases.ROUTINE_EVENT)
    assert trigger.fired is True
    assert trigger.template_id == "delivery_exception_reschedule"
    assert trigger.channel == "chat"
    assert trigger.severity is Severity.LOW
    assert trigger.consequential is False
    assert set(trigger.facts) == {"tracking_ref", "next_attempt_on"}


def test_a_consequential_event_is_marked_as_such_by_policy_not_by_severity_alone() -> None:
    trigger = _evaluate(sample_cases.CONSEQUENTIAL_EVENT)
    assert trigger.fired is True
    assert trigger.consequential is True
    assert trigger.channel == "voice"


def test_the_trigger_id_is_a_content_hash_so_the_same_question_has_one_id() -> None:
    first = _evaluate(sample_cases.ROUTINE_EVENT)
    second = _evaluate(sample_cases.ROUTINE_EVENT)
    assert first.trigger_id == second.trigger_id
    other = _evaluate(replace(sample_cases.ROUTINE_EVENT, event_id="evt-t-9999"))
    assert other.trigger_id != first.trigger_id


def test_only_the_required_attributes_survive_into_the_fact_set() -> None:
    """Data minimisation with teeth: an extra attribute cannot become a figure in a body."""
    noisy = replace(
        sample_cases.ROUTINE_EVENT,
        attributes={
            **dict(sample_cases.ROUTINE_EVENT.attributes),
            "internal_score": "0.83",
            "operator_note": "called twice",
        },
    )
    trigger = _evaluate(noisy)
    assert set(trigger.facts) == {"tracking_ref", "next_attempt_on"}


def test_a_missing_required_attribute_does_not_fire_and_names_the_attribute() -> None:
    incomplete = replace(sample_cases.ROUTINE_EVENT, attributes={"next_attempt_on": "2026-08-12"})
    trigger = _evaluate(incomplete)
    assert trigger.fired is False
    assert trigger.reasons == (trigger_engine.REASON_ATTRIBUTE_PREFIX + "tracking_ref",)


def test_a_stale_event_does_not_fire() -> None:
    """A late notification is its own harm: yesterday's outage is not news."""
    stale = replace(
        sample_cases.ROUTINE_EVENT,
        occurred_at=(_AS_OF - timedelta(hours=200)).isoformat(),
    )
    assert _evaluate(stale).reasons == (trigger_engine.REASON_STALE,)


def test_an_event_in_the_future_does_not_fire() -> None:
    ahead = replace(
        sample_cases.ROUTINE_EVENT, occurred_at=(_AS_OF + timedelta(hours=2)).isoformat()
    )
    assert _evaluate(ahead).reasons == (trigger_engine.REASON_FUTURE,)


def test_a_naive_timestamp_is_refused_rather_than_assumed_to_be_utc() -> None:
    """A timestamp with no zone is an instant plus an assumption about where the writer sat."""
    naive = replace(sample_cases.ROUTINE_EVENT, occurred_at="2026-08-08T05:00:00")
    assert _evaluate(naive).reasons == (trigger_engine.REASON_BAD_TIMESTAMP,)
    unparseable = replace(sample_cases.ROUTINE_EVENT, occurred_at="last Tuesday")
    assert _evaluate(unparseable).reasons == (trigger_engine.REASON_BAD_TIMESTAMP,)


def test_an_event_type_with_no_configured_rule_does_not_fire() -> None:
    empty = OutreachPolicy(
        triggers={},
        frequency_caps=dict(DEFAULT_POLICY.frequency_caps),
        quiet_hours=dict(DEFAULT_POLICY.quiet_hours),
        templates=dict(DEFAULT_POLICY.templates),
        suppressed_subjects=DEFAULT_POLICY.suppressed_subjects,
        banned_phrases=DEFAULT_POLICY.banned_phrases,
        max_body_chars=DEFAULT_POLICY.max_body_chars,
    )
    trigger = _evaluate(sample_cases.ROUTINE_EVENT, empty)
    assert trigger.fired is False
    assert trigger.reasons == (trigger_engine.REASON_NO_RULE,)


def test_every_configured_event_type_has_a_rule_and_a_template() -> None:
    """The five the catalog row promises, each with somewhere for its body to come from."""
    for member in EventType:
        rule = DEFAULT_POLICY.trigger_for(member)
        assert rule is not None, f"{member.value} has no configured trigger rule"
        assert DEFAULT_POLICY.template_for(rule.template_id), (
            f"{member.value} names template {rule.template_id!r}, which is not configured"
        )


def test_a_fired_trigger_cites_both_the_event_and_the_rule() -> None:
    sources = {citation.source_id for citation in _evaluate(sample_cases.ROUTINE_EVENT).citations}
    assert f"event:{sample_cases.ROUTINE_EVENT.event_id}" in sources
    assert "policy:trigger:delivery_exception" in sources
