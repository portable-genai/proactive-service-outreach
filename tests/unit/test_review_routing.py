"""Rule R8: a consequential outreach is ROUTED to Hrz7, not left in a per-repo boolean.

This is the standing gate for the failure the rule exists to prevent. A repo can set
``requires_human_review = True``, pass every other test, and still auto-execute in practice
because nothing ever reads the flag. So the assertions here are about the ROUTING, not the flag:
a consequential event produces an outbound review AND no delivery, a routine one produces
neither, the payload leaves redacted, and the on-prem placeholder refuses rather than swallowing
the escalation.

The delivery assertion is this vertical's addition to the standard R8 suite. On a document
service an unrouted escalation means an unreviewed decision; here it means a customer was
telephoned about a fraud hold on nobody's authority, so "held" has to mean "not sent" and not
merely "flagged".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from proactive_outreach.adapters.gcp.review_router import (
    CloudReviewRouter,
)
from proactive_outreach.adapters.local.review_router import (
    LocalReviewRouter,
)
from proactive_outreach.adapters.onprem.review_router import (
    OnPremReviewRouter,
)
from proactive_outreach.api.app import (
    app,
)
from proactive_outreach.config import (
    Settings,
    build_container,
)
from proactive_outreach.domain.kernel import (
    Severity,
)
from proactive_outreach.domain.models import (
    OutreachResult,
    ServiceEvent,
)

from tests.conftest import build_service, local_settings
from tests.fixtures import sample_cases


def _settings(profile: str = "local") -> Settings:
    return local_settings(profile=profile)


def _result(event: ServiceEvent) -> OutreachResult:
    container = build_container(_settings())
    return build_service(container).evaluate(
        event, actor=sample_cases.ACTOR, as_of=sample_cases.OPEN_INSTANT
    )


def test_a_consequential_result_produces_an_outbound_review() -> None:
    router = LocalReviewRouter(_settings())
    result = _result(sample_cases.CONSEQUENTIAL_EVENT)
    ref = router.route(result, maker=sample_cases.ACTOR)
    assert ref, "routing must return a reference, so the caller can record where it went"
    pending = router.outbox.pending()
    assert len(pending) == 1
    review = pending[0].review
    assert review.maker == sample_cases.ACTOR
    assert review.tenant == sample_cases.TENANT
    assert review.severity == Severity.CRITICAL.value
    assert review.source_key, "a durable outbox needs an idempotency key"


def test_the_reviewer_receives_the_words_they_are_being_asked_to_approve() -> None:
    """A reviewer who cannot see the proposed message cannot meaningfully approve it."""
    router = LocalReviewRouter(_settings())
    result = _result(sample_cases.CONSEQUENTIAL_EVENT)
    router.route(result, maker=sample_cases.ACTOR)
    assert result.message is not None
    assert "hold was placed" in router.outbox.pending()[0].review.summary


def test_a_critical_result_demands_dual_control() -> None:
    router = LocalReviewRouter(_settings())
    router.route(_result(sample_cases.CONSEQUENTIAL_EVENT), maker=sample_cases.ACTOR)
    assert router.outbox.pending()[0].review.required_approvals == 2


def test_the_payload_is_redacted_before_it_leaves_the_process() -> None:
    """Hrz7 is a shared sink; a raw identifier must never reach the wire."""
    router = LocalReviewRouter(_settings())
    router.route(_result(sample_cases.PII_EVENT), maker=sample_cases.ACTOR)
    wire = repr(router.outbox.pending()[0].review.to_payload())
    assert sample_cases.PLANTED_NRIC not in wire


def test_the_managed_router_refuses_when_no_console_is_configured() -> None:
    """An escalation with nowhere to go must fail loudly, not return as if it were reviewed."""
    router = CloudReviewRouter(local_settings(profile="gcp", review_url=""))
    with pytest.raises(RuntimeError, match="R8"):
        router.route(_result(sample_cases.CONSEQUENTIAL_EVENT), maker=sample_cases.ACTOR)


def test_the_onprem_placeholder_refuses_rather_than_dropping_the_escalation() -> None:
    router = OnPremReviewRouter(_settings("onprem"))
    with pytest.raises(NotImplementedError, match="R8"):
        router.route(_result(sample_cases.CONSEQUENTIAL_EVENT), maker=sample_cases.ACTOR)


def _post(client: TestClient, event: ServiceEvent) -> dict[str, object]:
    """POST one event to the serving path, timestamped now so it is never stale.

    The API decides against the wall clock. The two assertions below hold at any hour: a
    consequential trigger is held whatever eligibility says, and a routine one never
    manufactures a review.
    """
    fresh = sample_cases.as_recent(event)
    return dict(
        client.post(
            "/v1/outreach/evaluate",
            json={
                "event_id": fresh.event_id,
                "event_type": fresh.event_type.value,
                "subject_id": fresh.subject_id,
                "occurred_at": fresh.occurred_at,
                "market": fresh.market,
                "locale": fresh.locale,
                "detail": fresh.detail,
                "attributes": dict(fresh.attributes),
            },
            headers={"X-Dev-Persona": "auditor"},
        ).json()
    )


def test_the_api_routes_the_escalation_in_the_same_request() -> None:
    """The serving path, not just the adapter: an escalation must not depend on a later job."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    held = _post(client, sample_cases.CONSEQUENTIAL_EVENT)
    assert held["requires_human_review"] is True
    assert held["review_ref"], "an escalation with no routing reference went nowhere"
    assert held["delivered"] is False, "a consequential outreach was delivered anyway"

    routine = _post(client, sample_cases.ROUTINE_EVENT)
    assert routine["requires_human_review"] is False
    assert routine["review_ref"] == "", "a non-escalation must not manufacture a review"
