"""The A2A discovery card: what this agent can be asked to do, in one machine-readable place.

Served at ``/.well-known/agent-card.json`` and registrable with agent-registry (rule R4). The card
is built from the SAME tool table the runtime binds, so an agent cannot advertise a skill it does
not implement or implement one it never advertises; ``tests/unit/test_agent_surface.py`` fails the
build when the two disagree.

Pure: domain types and stdlib only, no ADK and no cloud SDK, so the card can be generated and
inspected offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hex_service_kit.serialization import to_jsonable

from ..config import Settings

_CARD_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class AgentSkill:
    """One advertised capability. ``id`` is the tool function's name, never a prose label."""

    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AgentCard:
    """The minimal A2A discovery document a peer agent or the registry reads."""

    name: str
    description: str
    url: str
    version: str = _CARD_VERSION
    provider: str = "proactive-service-outreach"
    skills: tuple[AgentSkill, ...] = field(default_factory=tuple)


SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="evaluate_service_event",
        name="Service-event outreach decision",
        description=(
            "Decide one operational event (failed payment, delivery exception, expiring card, "
            "fraud hold, outage): deterministic trigger rules, the consent question, then the "
            "eligibility engine over consent, suppression, frequency caps and quiet hours. A "
            "body is drafted ONLY after eligibility passes and is discarded unless every "
            "figure in it came from the event. Consequential outreach is never delivered from "
            "here: it is held and routed to human review (rule R8)."
        ),
    ),
    AgentSkill(
        id="sweep_service_events",
        name="Tenant outreach sweep",
        description=(
            "Run the same decision over every event the detection port reports for one "
            "tenant, at one explicit instant, and report per event what was delivered, what "
            "was refused and why, and what was held for a human."
        ),
    ),
    AgentSkill(
        id="verify_audit_trail",
        name="Audit-trail verification",
        description=(
            "Re-derive the hash chain over the stored audit trail and cross-check the external "
            "head anchor, returning an honest verdict: intact, or the first record that broke "
            "the chain, or the anchor disagreement that exposes a truncated tail."
        ),
    ),
)

#: Joined from short pieces, each carrying at most one template variable, so a longer
#: ``friendly_name`` cannot push a line past the formatter's limit in the rendered repo while
#: the template itself still looks fine. The vertical's own prose belongs in ``README.md``;
#: the card says what the agent IS and what it guarantees.
_DESCRIPTION = " ".join(
    (
        "Proactive Service Outreach",
        "(E5).",
        "Consent-gated, frequency-capped service notifications from deterministic",
        "operational triggers. Every number comes from a pure engine, the model only",
        "phrases an already-approved message, and every consequential result is routed",
        "to a human reviewer rather than delivered.",
    )
)


def build_agent_card(settings: Settings | None = None) -> AgentCard:
    """Construct the A2A card for this agent in the configured deployment."""
    resolved = settings or Settings.load()
    return AgentCard(
        name="proactive-service-outreach",
        description=_DESCRIPTION,
        url=_resolve_url(resolved),
        skills=SKILLS,
    )


def agent_card_document(settings: Settings | None = None) -> dict[str, Any]:
    """The JSON-safe body served at ``/.well-known/agent-card.json``."""
    document = to_jsonable(build_agent_card(settings))
    if not isinstance(document, dict):  # pragma: no cover - dataclasses serialise to objects
        raise TypeError("an agent card must serialise to a JSON object")
    return document


def _resolve_url(settings: Settings) -> str:
    """Best-effort public URL for the card, region-qualified so residency is visible on it."""
    return f"https://proactive-service-outreach.{settings.region}.internal.example/a2a"
