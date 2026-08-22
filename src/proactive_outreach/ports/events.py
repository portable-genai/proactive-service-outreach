"""EventDetectionPort: where operational events come from (the upstream edge of the hexagon).

The detection side is a port and not a library call because it is the piece that differs most
between deployments: a warehouse query in the managed profile, a fixture file offline, a
client's own message bus on premises. What every implementation owes the domain is the same:
already-typed :class:`~..domain.models.ServiceEvent` values, in a stable order, for one tenant.

Ordering is part of the contract. An adapter that returned events in whatever order its store
happened to yield would make a sweep's audit trail depend on storage internals, so
implementations sort by ``occurred_at`` then ``event_id``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import EventQuery, ServiceEvent


class EventSourceUnavailableError(RuntimeError):
    """Raised when the event source cannot be reached or is not configured.

    Deliberately NOT a silent empty list. "No events" and "I could not look" are different
    facts, and a sweep that reports the second as the first looks like a quiet day.
    """


@runtime_checkable
class EventDetectionPort(Protocol):
    def detect(self, query: EventQuery) -> tuple[ServiceEvent, ...]:
        """Return the tenant's matching events, oldest first, or raise rather than guess."""
        ...
