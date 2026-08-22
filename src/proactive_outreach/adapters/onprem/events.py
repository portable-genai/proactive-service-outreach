"""On-prem EventDetectionPort: fail-fast portability placeholder (the sovereign-exit proof).

The client's own operational systems are the event source on premises, and this binding refuses
rather than returning an empty tuple. An empty tuple is the dangerous placeholder here: a sweep
that reports no events looks exactly like a quiet morning, and nobody investigates a quiet
morning.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import EventQuery, ServiceEvent


class OnPremEventSource:
    """Satisfies EventDetectionPort but refuses: bind the client's own event feed."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def detect(self, query: EventQuery) -> tuple[ServiceEvent, ...]:
        raise NotImplementedError(
            "on-prem event detection is a portability placeholder: bind the client's own "
            "operational event feed (see docs/onprem-migration.md). Returning no events would "
            "be indistinguishable from a quiet day."
        )
