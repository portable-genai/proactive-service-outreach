"""On-prem ConsentPort: fail-fast portability placeholder (the sovereign-exit proof, P-12).

The client runs its own preference centre on premises, so this binding refuses at call time. The
refusal is the only correct failure: a consent adapter that returned anything at all without
asking a store would be inventing a legal position about a person.
"""

from __future__ import annotations

from consent_preference_kit import ConsentDecision, ConsentQuery, SendRecord

from ...config import Settings


class OnPremConsentAdapter:
    """Satisfies ConsentPort but refuses: bind the client's own preference centre."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def decide(self, query: ConsentQuery) -> ConsentDecision:
        raise NotImplementedError(
            "on-prem consent lookup is a portability placeholder: bind the client's own "
            "preference centre (see docs/onprem-migration.md). Nothing here may invent a "
            "consent decision, because a decision nobody made is not consent."
        )

    def record_send(self, send: SendRecord) -> str:
        raise NotImplementedError(
            "on-prem send recording is a portability placeholder: bind the client's own "
            "preference centre (see docs/onprem-migration.md). A cap counts recorded sends, so "
            "silently dropping this would make every frequency cap unenforceable."
        )
