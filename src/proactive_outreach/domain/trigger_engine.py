"""The trigger engine: does this operational event justify contacting a customer at all?

Pure stdlib, frozen inputs, frozen output, and an EXPLICIT ``as_of``. There is no clock in this
module and no I/O: the same event and the same instant produce the same verdict on any machine,
which is what makes a decision about contacting a person replayable months later.

The model has no part in this. It is not consulted, it is not passed the event, and it cannot
cause a trigger to fire or to be suppressed. What fires is decided here, by rules that are
configuration (see :mod:`.policy`), and the model is only asked to phrase a message once
eligibility has also passed.

Fail closed, in five distinct ways, because "did not fire" is a safe outcome and "fired on an
event we did not understand" is not:

* an event type with no configured rule does not fire (``trigger_rule_unconfigured``);
* an event whose timestamp will not parse, or is in the future, does not fire;
* an event older than its rule's window does not fire (``event_stale``): yesterday's outage is
  not news, and a late notification is its own kind of harm;
* an event missing an attribute the message has to quote does not fire
  (``event_attribute_missing:<name>``), because the alternative is a drafter inventing it; and
* a rule naming a channel this service cannot deliver on does not fire.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from .kernel import Citation, Severity
from .models import DELIVERABLE_CHANNELS, EventType, OutreachTrigger, ServiceEvent
from .policy import OutreachPolicy, TriggerRule

#: Reason tokens this engine emits. Named constants rather than inline strings: they are read
#: by the eligibility engine, the eval oracle and the demo, and a typo in one of those places
#: would look like a rule that never fires.
REASON_NO_RULE = "trigger_rule_unconfigured"
REASON_BAD_TIMESTAMP = "event_timestamp_invalid"
REASON_FUTURE = "event_in_the_future"
REASON_STALE = "event_stale"
REASON_CHANNEL = "channel_not_deliverable"
REASON_FIRED = "trigger_fired"
#: Prefixed with the attribute that was missing, so the reason names the fix.
REASON_ATTRIBUTE_PREFIX = "event_attribute_missing:"


def _trigger_id(event: ServiceEvent, as_of: datetime) -> str:
    """A content hash of the question, so the same event at the same instant has one id."""
    material = "|".join(
        (
            event.event_id,
            event.event_type.value,
            event.tenant,
            event.subject_id,
            event.occurred_at,
            as_of.isoformat(),
        )
    )
    return "trg-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _parse(moment: str) -> datetime | None:
    """Parse an ISO-8601 instant, refusing anything without a timezone.

    A naive timestamp is not an instant: it is an instant plus an assumption about where the
    writer was sitting. Quiet hours and staleness both turn on the answer, so the assumption is
    refused rather than made.
    """
    try:
        parsed = datetime.fromisoformat(moment.strip())
    except (ValueError, AttributeError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _facts(event: ServiceEvent, rule: TriggerRule) -> tuple[dict[str, str], list[str]]:
    """The closed fact set a message may quote, plus the names that were missing.

    ONLY the attributes the rule requires are carried forward. Everything else the source
    system happened to attach is dropped here, which is data minimisation (P-04) and is also
    what keeps the groundedness check tight: a body may contain a figure only if it is in this
    dictionary.
    """
    facts: dict[str, str] = {}
    missing: list[str] = []
    for name in rule.required_attributes:
        value = event.attribute(name).strip()
        if not value:
            missing.append(name)
            continue
        facts[name] = value
    return facts, missing


def _refused(
    event: ServiceEvent,
    as_of: datetime,
    reasons: tuple[str, ...],
    citations: tuple[Citation, ...] = (),
) -> OutreachTrigger:
    return OutreachTrigger(
        trigger_id=_trigger_id(event, as_of),
        event_id=event.event_id,
        event_type=event.event_type,
        tenant=event.tenant,
        subject_id=event.subject_id,
        market=event.market,
        locale=event.locale,
        fired=False,
        severity=Severity.LOW,
        reasons=reasons,
        citations=citations,
    )


def _rule_citation(rule: TriggerRule) -> Citation:
    return Citation(
        source_id=f"policy:trigger:{rule.event_type.value}",
        title="Configured trigger rule",
        snippet=(
            f"template {rule.template_id}, channel {rule.channel}, "
            f"severity {rule.severity.value}, window {rule.max_age_hours}h"
        ),
    )


def _event_citation(event: ServiceEvent, facts: dict[str, str]) -> Citation:
    return Citation(
        source_id=f"event:{event.event_id}",
        title=f"{event.event_type.value} from {event.source_system or 'unnamed source'}",
        snippet="; ".join(f"{name}={value}" for name, value in sorted(facts.items())),
    )


def evaluate(event: ServiceEvent, *, policy: OutreachPolicy, as_of: datetime) -> OutreachTrigger:
    """Decide whether ``event`` becomes an outreach, at the instant ``as_of``.

    Returns a verdict either way. A refusal is a first-class result carrying its reasons, not
    an exception and not a ``None``: the audit trail records why a customer was NOT contacted
    with the same fidelity as why they were.
    """
    rule = policy.trigger_for(event.event_type)
    if rule is None:
        return _refused(event, as_of, (REASON_NO_RULE,))
    rule_citation = _rule_citation(rule)
    if rule.channel not in DELIVERABLE_CHANNELS:  # pragma: no cover - refused at policy load
        return _refused(event, as_of, (REASON_CHANNEL,), (rule_citation,))

    occurred = _parse(event.occurred_at)
    if occurred is None:
        return _refused(event, as_of, (REASON_BAD_TIMESTAMP,), (rule_citation,))
    age_hours = (as_of - occurred).total_seconds() / 3600.0
    if age_hours < 0:
        return _refused(event, as_of, (REASON_FUTURE,), (rule_citation,))
    if age_hours > rule.max_age_hours:
        return _refused(event, as_of, (REASON_STALE,), (rule_citation,))

    facts, missing = _facts(event, rule)
    if missing:
        reasons = tuple(REASON_ATTRIBUTE_PREFIX + name for name in missing)
        return _refused(event, as_of, reasons, (rule_citation,))

    return OutreachTrigger(
        trigger_id=_trigger_id(event, as_of),
        event_id=event.event_id,
        event_type=event.event_type,
        tenant=event.tenant,
        subject_id=event.subject_id,
        market=event.market,
        locale=event.locale,
        fired=True,
        template_id=rule.template_id,
        purpose=rule.purpose,
        channel=rule.channel,
        resolution_path=rule.resolution_path,
        severity=rule.severity,
        consequential=rule.consequential,
        reasons=(REASON_FIRED,),
        facts=facts,
        citations=(_event_citation(event, facts), rule_citation),
    )


__all__ = [
    "REASON_ATTRIBUTE_PREFIX",
    "REASON_BAD_TIMESTAMP",
    "REASON_CHANNEL",
    "REASON_FIRED",
    "REASON_FUTURE",
    "REASON_NO_RULE",
    "REASON_STALE",
    "EventType",
    "evaluate",
]
