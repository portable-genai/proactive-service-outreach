"""API surface: verified-principal identity, fail-closed S2S, security headers.

The client comes from the shared ``api_client`` fixture, which pins a loopback peer: the
app-object exposure guard refuses the unauthenticated local posture to any other peer, and
TestClient's default peer is the literal host "testclient".

The serving path decides against the WALL CLOCK, because that is what a live service does, so
the events here are timestamped a few minutes ago and the assertions are the ones that hold at
any hour. Nothing here asserts a delivery: at 23:00 in Singapore there correctly is not one,
and a test that demanded one would be demanding the quiet-hours rule be broken.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from proactive_outreach.domain.models import ServiceEvent

from tests.fixtures import sample_cases

_TOKEN_ENV = "OUTREACH_S2S_TOKEN"


def _body(event: ServiceEvent) -> dict[str, object]:
    fresh = sample_cases.as_recent(event)
    return {
        "event_id": fresh.event_id,
        "event_type": fresh.event_type.value,
        "subject_id": fresh.subject_id,
        "occurred_at": fresh.occurred_at,
        "market": fresh.market,
        "locale": fresh.locale,
        "detail": fresh.detail,
        "attributes": dict(fresh.attributes),
    }


def test_a_consequential_event_is_held_and_attributed_to_the_verified_principal(
    api_client: TestClient,
) -> None:
    resp = api_client.post(
        "/v1/outreach/evaluate",
        json=_body(sample_cases.CONSEQUENTIAL_EVENT),
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["severity"] == "critical"
    assert body["requires_human_review"] is True
    assert body["delivered"] is False
    # Rule R8: the escalation was routed, not merely flagged (see test_review_routing.py).
    assert body["review_ref"]


def test_the_response_explains_the_whole_decision_not_just_the_outcome(
    api_client: TestClient,
) -> None:
    """ "Why did this person get this?" must be answerable from the response alone."""
    body = api_client.post(
        "/v1/outreach/evaluate",
        json=_body(sample_cases.ROUTINE_EVENT),
        headers={"X-Dev-Persona": "auditor"},
    ).json()
    assert body["trigger"]["fired"] is True
    assert body["eligibility"]["reasons"], "an eligibility verdict with no reasons explains nothing"
    assert body["citations"], "an uncited result is not shippable"


def test_an_unknown_consent_subject_is_refused_on_the_serving_path(
    api_client: TestClient,
) -> None:
    body = api_client.post(
        "/v1/outreach/evaluate",
        json=_body(sample_cases.UNKNOWN_SUBJECT_EVENT),
        headers={"X-Dev-Persona": "auditor"},
    ).json()
    assert body["eligibility"]["eligible"] is False
    assert body["delivered"] is False
    assert "consent_unknown" in body["eligibility"]["reasons"]


def test_an_event_type_this_service_does_not_watch_for_is_refused(
    api_client: TestClient,
) -> None:
    payload = _body(sample_cases.ROUTINE_EVENT) | {"event_type": "share_price_moved"}
    resp = api_client.post(
        "/v1/outreach/evaluate", json=payload, headers={"X-Dev-Persona": "auditor"}
    )
    assert resp.status_code == 422


def test_the_event_listing_never_returns_the_free_text_detail(api_client: TestClient) -> None:
    """``detail`` is the only field that can carry personal data, so a listing does not."""
    resp = api_client.post(
        "/v1/outreach/events", json={"limit": 5}, headers={"X-Dev-Persona": "auditor"}
    )
    assert resp.status_code == 200
    listed = resp.json()
    assert listed, "the fixture source returned nothing"
    for row in listed:
        assert "detail" not in row


def test_a_sweep_evaluates_and_routes_every_detected_event(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/outreach/sweep",
        json={"limit": 50},
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 200
    results = resp.json()
    assert results
    for row in results:
        if row["requires_human_review"]:
            assert row["review_ref"], f"{row['event_id']} was held but never routed"
            assert row["delivered"] is False


def test_unknown_persona_is_401(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/outreach/evaluate",
        json=_body(sample_cases.ROUTINE_EVENT),
        headers={"X-Dev-Persona": "ghost"},
    )
    assert resp.status_code == 401


def test_healthz_reports_profile_and_region(api_client: TestClient) -> None:
    body = api_client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["profile"] == "local"
    assert body["region"] == "asia-southeast1"


def test_security_headers_present(api_client: TestClient) -> None:
    headers = api_client.get("/healthz").headers
    assert headers["Content-Security-Policy"] == "frame-ancestors 'self'"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.fixture()
def token_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv(_TOKEN_ENV, "s3cret-service-token")
    yield "s3cret-service-token"


def test_s2s_endpoint_open_when_secret_unset(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_TOKEN_ENV, raising=False)
    assert api_client.post("/v1/audit/ping").status_code == 200


def test_s2s_endpoint_rejects_missing_token_when_enforced(
    api_client: TestClient, token_env: str
) -> None:
    assert api_client.post("/v1/audit/ping").status_code == 401


def test_s2s_endpoint_accepts_correct_token(api_client: TestClient, token_env: str) -> None:
    resp = api_client.post("/v1/audit/ping", headers={"Authorization": f"Bearer {token_env}"})
    assert resp.status_code == 200
