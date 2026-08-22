"""Local EventDetectionPort: the SDK-free fixture source the offline gate and the demo run on.

Reads the shipped fixture set (:mod:`.fixtures`), or a JSON file when ``event_fixture_path``
names one. A path that is NAMED but missing raises: somebody pointed at a file, and quietly
serving the built-in set instead is how a deployment ends up demonstrating the wrong events.

``occurred_minutes_ago`` is resolved against the query's ``as_of``, so the same query at the
same instant produces byte-identical events forever, and the fixture set is still "live"
whenever it is read. That is the property that lets the demo, the eval and the self-test all
drive the real engines rather than a frozen snapshot of their output.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...config import Settings
from ...domain.models import EventQuery, EventType, ServiceEvent
from ...ports.events import EventSourceUnavailableError
from .fixtures import FIXTURE_EVENTS


def _resolve_as_of(query: EventQuery) -> datetime:
    """The instant relative ages are measured from: the query's, or this machine's clock.

    A clock in an ADAPTER is fine; a clock in the domain is not. The domain always receives an
    explicit instant, and a caller that wants a replayable sweep pins ``as_of`` on the query.
    """
    if query.as_of.strip():
        parsed = datetime.fromisoformat(query.as_of.strip())
        if parsed.tzinfo is None:
            raise EventSourceUnavailableError(
                f"EventQuery.as_of {query.as_of!r} has no timezone, so relative fixture ages "
                "cannot be resolved to an instant"
            )
        return parsed
    return datetime.now(UTC)


def _occurred_at(record: dict[str, Any], as_of: datetime) -> str:
    absolute = str(record.get("occurred_at", "") or "")
    if absolute:
        return absolute
    minutes = record.get("occurred_minutes_ago")
    if not isinstance(minutes, int):
        raise EventSourceUnavailableError(
            f"fixture event {record.get('event_id', '?')!r} carries neither occurred_at nor an "
            "integer occurred_minutes_ago"
        )
    return (as_of - timedelta(minutes=minutes)).isoformat()


def _to_event(record: dict[str, Any], tenant: str, as_of: datetime) -> ServiceEvent:
    raw_type = str(record.get("event_type", "") or "")
    try:
        event_type = EventType(raw_type)
    except ValueError as exc:
        raise EventSourceUnavailableError(
            f"fixture event {record.get('event_id', '?')!r} names an unknown type {raw_type!r}"
        ) from exc
    attributes = record.get("attributes") or {}
    if not isinstance(attributes, dict):
        raise EventSourceUnavailableError(
            f"fixture event {record.get('event_id', '?')!r} has non-mapping attributes"
        )
    return ServiceEvent(
        event_id=str(record.get("event_id", "") or ""),
        event_type=event_type,
        tenant=tenant,
        subject_id=str(record.get("subject_id", "") or ""),
        occurred_at=_occurred_at(record, as_of),
        market=str(record.get("market", "") or ""),
        locale=str(record.get("locale", "") or ""),
        detail=str(record.get("detail", "") or ""),
        source_system=str(record.get("source_system", "") or ""),
        attributes={str(k): str(v) for k, v in attributes.items()},
    )


class FixtureEventSource:
    """Serve synthetic operational events from the shipped set or a named JSON file."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _records(self) -> Iterable[dict[str, Any]]:
        configured = self._settings.event_fixture_path.strip()
        if not configured:
            return FIXTURE_EVENTS
        path = Path(configured)
        if not path.exists():
            raise EventSourceUnavailableError(
                f"event_fixture_path names {path}, which does not exist. Point it at a readable "
                "JSON array of events, or clear it to use the shipped fixture set."
            )
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EventSourceUnavailableError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(loaded, list):
            raise EventSourceUnavailableError(f"{path} must contain a JSON array of events")
        return [record for record in loaded if isinstance(record, dict)]

    def detect(self, query: EventQuery) -> tuple[ServiceEvent, ...]:
        """Every matching event for the tenant, oldest first, then by id for a stable order."""
        as_of = _resolve_as_of(query)
        wanted = set(query.event_types)
        events = [
            event
            for event in (_to_event(record, query.tenant, as_of) for record in self._records())
            if (not wanted or event.event_type.value in wanted)
            and (not query.since.strip() or event.occurred_at >= query.since.strip())
        ]
        events.sort(key=lambda event: (event.occurred_at, event.event_id))
        return tuple(events[: max(query.limit, 0)])
