"""Managed ConsentPort: ask the real consent and preference store, over ``consent-preference-kit``.

The store lives inside Mkt6. This adapter is a thin binding onto the pinned client kit, which
carries the wire types, the https-only guard, the three-state credential resolution and the
S2S headers. No cloud SDK is involved: the kit is pure stdlib ``urllib``, so this module imports
cleanly with no GCP SDK present and is bound in the managed profile because it makes a real
network call to a sibling service.

Two fail-closed choices worth naming:

* an unset ``consent_url`` REFUSES rather than defaulting to a loopback store. A consent
  question answered by a store nobody configured is worse than no answer, because it looks like
  an answer; and
* the client is constructed per call, so a credential rotated or cleared after start-up is seen
  on the next question rather than by a long-lived client that quietly kept the old one.
"""

from __future__ import annotations

from consent_preference_kit import (
    ConsentClient,
    ConsentClientError,
    ConsentDecision,
    ConsentQuery,
    SendRecord,
)

from ...config import Settings
from ...ports.consent import ConsentUnavailableError

#: The actor this service asserts to the store. It names the SERVICE, never a person.
_SERVICE_ACTOR = "proactive-service-outreach"


class RemoteConsentAdapter:
    """Ask the Mkt6 consent and preference store whether this contact is permitted."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client(self) -> ConsentClient:
        base_url = self._settings.consent_url.strip()
        if not base_url:
            raise ConsentUnavailableError(
                "consent_url is not configured, so no consent decision can be obtained. Set "
                "MKT_CONSENT_STORE_URL (config/settings.yaml consent_url) to the consent and "
                "preference store. There is no local fallback: this service does not hold a "
                "second copy of anybody's consent."
            )
        return ConsentClient(base_url)

    def decide(self, query: ConsentQuery) -> ConsentDecision:
        client = self._client()
        try:
            return client.decide(query, actor=_SERVICE_ACTOR)
        except ConsentClientError as exc:  # pragma: no cover - needs a live store
            raise ConsentUnavailableError(f"the consent store could not answer: {exc}") from exc

    def record_send(self, send: SendRecord) -> str:
        client = self._client()
        try:
            return client.record_send(send, actor=_SERVICE_ACTOR)
        except ConsentClientError as exc:  # pragma: no cover - needs a live store
            raise ConsentUnavailableError(f"the send could not be recorded: {exc}") from exc
