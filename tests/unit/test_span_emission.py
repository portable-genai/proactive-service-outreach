"""The outreach path opens spans, and no span carries content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit store.
So the value of tracing this path depends entirely on the spans carrying structural attributes
only: which action, whose, which tenant, which trigger kind, which market. A source system's
free-text ``detail``, a subject identifier or a drafted message body reaching a span has left
the boundary the service's ``redact`` call exists to hold, and it has left it silently.

Two shapes are pinned here rather than one. ``evaluate`` opens a leaf span, and ``sweep`` opens
a PARENT with one child per event: a sweep is a fan-out, not an alias, so the nesting is honest
and the depths are asserted rather than assumed. The content case drives the event whose detail
carries a planted NRIC, so the check runs against input that would actually leak.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from proactive_outreach.config import build_container
from proactive_outreach.domain.models import EventQuery, OutreachResult, ServiceEvent
from proactive_outreach.domain.outreach_service import OutreachService

from tests.conftest import local_settings
from tests.fixtures import sample_cases

_AS_OF = sample_cases.OPEN_INSTANT

#: Every attribute key either span is allowed to carry. A verdict that started explaining itself
#: on the span (a refusal reason, a finding, a subject id) would widen this set, which is the
#: point of asserting on the set rather than on the individual keys.
_EVALUATE_KEYS = {"action", "actor", "tenant", "event_type", "market"}
_SWEEP_KEYS = {"action", "actor", "tenant", "limit"}


class _RecordingTracer:
    """Captures every span name, attribute and nesting depth so the test can inspect them."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []
        self.depths: list[int] = []
        self._open = 0

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        self.depths.append(self._open)
        self._open += 1
        try:
            yield
        finally:
            self._open -= 1

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _service(tracer: _RecordingTracer) -> OutreachService:
    """The REAL local adapters, exactly as ``tests/conftest.build_service`` wires them."""
    container = build_container(local_settings())
    return OutreachService(
        audit=container.audit,
        consent=container.consent,
        drafting=container.drafting,
        delivery=container.delivery,
        speech=container.speech,
        tracer=tracer,  # type: ignore[arg-type]
        events=container.events,
        policy=container.settings.policy,
    )


def _evaluate(event: ServiceEvent) -> tuple[_RecordingTracer, OutreachResult]:
    tracer = _RecordingTracer()
    result = _service(tracer).evaluate(event, actor=sample_cases.ACTOR, as_of=_AS_OF)
    return tracer, result


def _emitted(tracer: _RecordingTracer) -> str:
    """Every attribute VALUE that was emitted, and every KEY, as one searchable blob."""
    parts: list[str] = []
    for name, attributes in tracer.spans:
        parts.append(name)
        parts.extend(attributes)
        parts.extend(attributes.values())
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# The spans exist at all
# --------------------------------------------------------------------------- #
def test_evaluating_one_event_opens_exactly_one_named_span() -> None:
    tracer, _ = _evaluate(sample_cases.ROUTINE_EVENT)
    assert [name for name, _ in tracer.spans] == ["outreach.evaluate"]
    assert tracer.depths == [0]


def test_a_sweep_opens_a_parent_span_with_one_child_per_evaluated_event() -> None:
    """The fan-out shape. A parent that timed a single child would be double counting."""
    tracer = _RecordingTracer()
    query = EventQuery(tenant=sample_cases.TENANT, as_of=_AS_OF.isoformat(), limit=50)
    results = _service(tracer).sweep(query, actor=sample_cases.ACTOR, as_of=_AS_OF)

    assert len(results) > 1, "the fixture feed stopped returning a fan-out worth a parent span"
    names = [name for name, _ in tracer.spans]
    assert names[0] == "outreach.sweep"
    assert names[1:] == ["outreach.evaluate"] * len(results)
    assert tracer.depths[0] == 0, "the sweep span is the parent"
    assert set(tracer.depths[1:]) == {1}, "every event span is a child of the sweep, not a sibling"


# --------------------------------------------------------------------------- #
# What the spans carry
# --------------------------------------------------------------------------- #
def test_the_evaluate_span_carries_the_structural_attributes_an_operator_needs() -> None:
    """Enough to answer "whose outreach is slow, on which trigger kind, in which market"."""
    tracer, _ = _evaluate(sample_cases.ROUTINE_EVENT)
    _, attributes = tracer.spans[0]
    assert attributes["action"] == "evaluate"
    assert attributes["actor"] == sample_cases.ACTOR
    assert attributes["tenant"] == sample_cases.TENANT
    assert attributes["event_type"] == sample_cases.ROUTINE_EVENT.event_type.value
    assert attributes["market"] == sample_cases.ROUTINE_EVENT.market


def test_the_sweep_span_carries_the_structural_attributes_an_operator_needs() -> None:
    tracer = _RecordingTracer()
    query = EventQuery(tenant=sample_cases.TENANT, as_of=_AS_OF.isoformat(), limit=50)
    _service(tracer).sweep(query, actor=sample_cases.ACTOR, as_of=_AS_OF)
    _, attributes = tracer.spans[0]
    assert attributes["action"] == "sweep"
    assert attributes["actor"] == sample_cases.ACTOR
    assert attributes["tenant"] == sample_cases.TENANT
    assert attributes["limit"] == "50"


@pytest.mark.parametrize(
    "event",
    [
        sample_cases.ROUTINE_EVENT,
        sample_cases.CONSEQUENTIAL_EVENT,
        sample_cases.UNKNOWN_SUBJECT_EVENT,
        sample_cases.PII_EVENT,
    ],
    ids=["delivered", "held", "refused", "pii"],
)
def test_the_evaluate_attribute_set_is_a_fixed_allowlist_whatever_the_outcome(
    event: ServiceEvent,
) -> None:
    """A refusal must not start attaching its reasons, or its subject, to the span."""
    tracer, _ = _evaluate(event)
    for _, attributes in tracer.spans:
        assert set(attributes) == _EVALUATE_KEYS


def test_the_sweep_attribute_sets_are_a_fixed_allowlist_for_parent_and_children() -> None:
    tracer = _RecordingTracer()
    query = EventQuery(tenant=sample_cases.TENANT, as_of=_AS_OF.isoformat(), limit=50)
    _service(tracer).sweep(query, actor=sample_cases.ACTOR, as_of=_AS_OF)
    assert set(tracer.spans[0][1]) == _SWEEP_KEYS
    for _, attributes in tracer.spans[1:]:
        assert set(attributes) == _EVALUATE_KEYS


# --------------------------------------------------------------------------- #
# What the spans must never carry
# --------------------------------------------------------------------------- #
def test_no_span_attribute_carries_event_content_or_the_planted_identifier() -> None:
    """The event used here has an NRIC planted in its free-text detail, so a leak would show."""
    tracer, result = _evaluate(sample_cases.PII_EVENT)
    emitted = _emitted(tracer)

    forbidden: list[str] = [
        sample_cases.PLANTED_NRIC,
        sample_cases.PII_EVENT.detail,
        "Issuer declined the authorisation",
        "ops@bank.example",
        "192.0.2.10",
        sample_cases.PII_EVENT.subject_id,
        sample_cases.PII_EVENT.event_id,
        *sample_cases.PII_EVENT.attributes.values(),
    ]
    if result.message is not None:
        # A drafted body is the other content-shaped value in reach of this call site.
        forbidden.append(result.message.body)

    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal not in emitted, f"a span attribute carried {literal!r}"
        assert literal.lower() not in emitted.lower(), f"a span attribute carried {literal!r}"


def test_no_sweep_span_attribute_carries_content_from_any_event_in_the_feed() -> None:
    """The whole feed, so a leak from one event nobody wrote a case for still fails."""
    tracer = _RecordingTracer()
    query = EventQuery(tenant=sample_cases.TENANT, as_of=_AS_OF.isoformat(), limit=50)
    results = _service(tracer).sweep(query, actor=sample_cases.ACTOR, as_of=_AS_OF)
    emitted = _emitted(tracer).lower()

    for result in results:
        for literal in (result.subject_id, result.event_id, result.summary, result.case_ref):
            assert literal, "an empty needle would pass this test for the wrong reason"
            assert literal.lower() not in emitted, f"a span attribute carried {literal!r}"
        if result.message is not None:
            assert result.message.body.lower() not in emitted


def test_every_emitted_attribute_value_is_a_string_the_port_declares() -> None:
    """``span(name, **attributes: str)``: a non-string would serialise however the SDK felt."""
    tracer = _RecordingTracer()
    query = EventQuery(tenant=sample_cases.TENANT, as_of=_AS_OF.isoformat(), limit=50)
    _service(tracer).sweep(query, actor=sample_cases.ACTOR, as_of=_AS_OF)
    values: list[Any] = [v for _, attributes in tracer.spans for v in attributes.values()]
    assert values
    assert all(isinstance(value, str) for value in values)
