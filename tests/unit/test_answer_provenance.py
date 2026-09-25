"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the drafting adapters NOTED
as they called. Before a request is answered the pill shows ``generator_model`` from
``/healthz``, so that value must be the model the bound adapter calls, never one a configuration
flag names while the adapter calls another.

The drafter is reached only for a contact that may be made, and quiet hours turn on the wall
clock the serving path decides against. So the route tests below pin the service's clock to an
instant every market is open, rather than passing before 22:00 and failing after it.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance

from proactive_outreach import config
from proactive_outreach.adapters.gcp.drafting import VertexDraftingAdapter
from proactive_outreach.api import app as app_module
from proactive_outreach.domain import outreach_service as outreach_module
from proactive_outreach.domain.models import DraftRequest
from proactive_outreach.domain.outreach_service import OutreachService
from proactive_outreach.domain.policy import DEFAULT_POLICY
from proactive_outreach.ports.drafting import DraftingPort

from tests import REPO_ROOT
from tests.conftest import local_settings
from tests.fixtures import sample_cases

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"


def _open_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decide against an instant every market is open, so the drafter is always reached."""

    def _open() -> datetime:
        return sample_cases.OPEN_INSTANT

    monkeypatch.setattr(outreach_module, "utcnow", _open)


def _evaluate(api_client: TestClient, **overrides: Any) -> tuple[dict[str, Any], dict[str, str]]:
    event = replace(sample_cases.CONSEQUENTIAL_EVENT, **overrides)
    response = api_client.post(
        "/v1/outreach/evaluate",
        json={
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "subject_id": event.subject_id,
            "occurred_at": event.occurred_at,
            "market": event.market,
            "locale": event.locale,
            "detail": event.detail,
            "attributes": dict(event.attributes),
        },
        headers={"X-Dev-Persona": "auditor"},
    )
    assert response.status_code == 200, response.text
    return response.json(), dict(response.headers)


def test_a_drafted_answer_names_the_offline_stub_and_no_search(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under ``local`` the template drafter answered, and the pill says exactly that."""
    _open_clock(monkeypatch)
    body, headers = _evaluate(api_client)
    assert body["eligibility"]["eligible"] is True, "the drafter was never reached"
    assert headers[ANSWERED_BY] == config.OFFLINE_STUB_MODEL
    assert SEARCH_USED not in headers


def test_a_contact_that_may_not_be_made_names_no_model(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing drafted, nothing noted, nothing sent: the pill never invents a model."""
    _open_clock(monkeypatch)
    body, headers = _evaluate(api_client, subject_id=sample_cases.UNKNOWN_SUBJECT_EVENT.subject_id)
    assert body["eligibility"]["eligible"] is False
    assert ANSWERED_BY not in headers
    assert SEARCH_USED not in headers


class _SearchingDrafter:
    """The real drafter, plus what a drafter that attached a search tool would note."""

    def __init__(self, inner: DraftingPort) -> None:
        self._inner = inner

    def draft(self, request: DraftRequest) -> str:
        raw = self._inner.draft(request)
        provenance.note_search()
        return raw


class _SearchingService(OutreachService):
    def __init__(self, *, drafting: DraftingPort, **ports: Any) -> None:
        super().__init__(drafting=_SearchingDrafter(drafting), **ports)


def test_the_route_says_when_the_answer_searched_and_forgets_it_after(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _open_clock(monkeypatch)
    monkeypatch.setattr(app_module, "OutreachService", _SearchingService)
    _, headers = _evaluate(api_client)
    assert headers[ANSWERED_BY] == config.OFFLINE_STUB_MODEL
    assert headers[SEARCH_USED] == "true"
    # The next request is a fresh record: an answer never leaks into a later response.
    monkeypatch.setattr(app_module, "OutreachService", OutreachService)
    _, headers = _evaluate(api_client, subject_id=sample_cases.UNKNOWN_SUBJECT_EVENT.subject_id)
    assert ANSWERED_BY not in headers
    assert SEARCH_USED not in headers


def _fake_genai(monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]) -> None:
    """Stand a recording ``google.genai`` in for the SDK, so no network and no SDK is needed."""

    class _Models:
        def generate_content(self, **kwargs: Any) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(text='{"body": "drafted"}')

    class _Client:
        def __init__(self, **_: Any) -> None:
            self.models = _Models()

    genai = ModuleType("google.genai")
    genai.Client = _Client  # type: ignore[attr-defined]
    google = ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)


def test_the_managed_drafter_notes_the_model_it_called_and_sends_no_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drafting is left free: no temperature, no generation config at all, and no search noted.

    Some models reject ``temperature`` outright, so "free" means absent, never ``1.0``.
    """
    calls: list[dict[str, Any]] = []
    _fake_genai(monkeypatch, calls)
    adapter = VertexDraftingAdapter(local_settings(drafting_model="managed-drafting-model"))
    request = DraftRequest(
        template_id="failed_payment_retry",
        locale="en-SG",
        channel="chat",
        facts={"card_suffix": "4242"},
        max_chars=DEFAULT_POLICY.max_body_chars,
    )
    with provenance.scope() as record:
        assert adapter.draft(request) == '{"body": "drafted"}'
    assert len(calls) == 1
    assert calls[0]["model"] == "managed-drafting-model"
    assert "config" not in calls[0] and "temperature" not in calls[0]
    assert record.models == ["managed-drafting-model"]
    assert record.search_used is False


def test_generator_model_is_the_setting_the_adapter_reads_and_no_flag_swaps_it() -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered.

    A resolver once named ``models.hard_reasoning`` when ``models.use_hard_reasoning`` was set,
    while the managed adapter never read the flag. The pill would then name a model that never
    answered. The flag is gone; a stray one in a settings object must change nothing.
    """
    models = SimpleNamespace(
        reasoning="the-model-the-adapter-calls",
        hard_reasoning="a-model-nobody-calls",
        use_hard_reasoning=True,
    )
    named = config._model_from_settings(SimpleNamespace(models=models), "models.reasoning")
    assert named == "the-model-the-adapter-calls"


def test_the_managed_pill_names_the_model_the_drafter_calls() -> None:
    settings = replace(local_settings(drafting_model="managed-drafting-model"), profile="gcp")
    assert settings.generator_model == "managed-drafting-model"


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    settings_file = (REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "use_hard_reasoning" not in settings_file
    for source in sorted((REPO_ROOT / "src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
