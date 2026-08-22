"""Managed EventDetectionPort: the warehouse view the operational events are read from.

The query is a parameterised BigQuery read over a view the client owns, and the view is the
contract: this service does not know how a payment ledger records a decline, only that the view
exposes the columns below. That is what keeps the trigger engine deterministic while the
upstream systems change underneath it.

The ``google-cloud-bigquery`` import lives INSIDE the method, so the ``local`` and ``onprem``
profiles import this module with no GCP SDK installed. The configuration is checked first, so a
deployment that never named a view gets a refusal that says so rather than an import error that
does not.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import EventQuery, EventType, ServiceEvent
from ...ports.events import EventSourceUnavailableError

#: The columns the view must expose. Named once so the query and the row mapping cannot drift.
_COLUMNS = (
    "event_id",
    "event_type",
    "subject_id",
    "occurred_at",
    "market",
    "locale",
    "detail",
    "source_system",
    "attributes",
)


class WarehouseEventSource:
    """Read typed service events from a client-owned warehouse view."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def detect(self, query: EventQuery) -> tuple[ServiceEvent, ...]:
        view = self._settings.event_view.strip()
        if not view:
            raise EventSourceUnavailableError(
                "event_view is not configured, so there is nothing to detect events from. Set "
                "OUTREACH_EVENT_VIEW (config/settings.yaml event_view) to the "
                "fully-qualified warehouse view, or bind the offline fixture source."
            )
        return self._read(view, query)  # pragma: no cover - needs a live warehouse

    def _read(self, view: str, query: EventQuery) -> tuple[ServiceEvent, ...]:
        # pragma: no cover - needs a live warehouse
        from google.cloud import bigquery

        client = bigquery.Client()
        sql = (
            f"SELECT {', '.join(_COLUMNS)} FROM `{view}` "
            "WHERE tenant = @tenant AND occurred_at >= @since "
            "ORDER BY occurred_at ASC, event_id ASC LIMIT @limit"
        )
        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("tenant", "STRING", query.tenant),
                    bigquery.ScalarQueryParameter("since", "STRING", query.since),
                    bigquery.ScalarQueryParameter("limit", "INT64", query.limit),
                ]
            ),
        )
        return tuple(self._to_event(dict(row), query.tenant) for row in job.result())

    @staticmethod
    def _to_event(row: dict[str, Any], tenant: str) -> ServiceEvent:
        # pragma: no cover - needs a live warehouse
        attributes = row.get("attributes") or {}
        return ServiceEvent(
            event_id=str(row.get("event_id", "")),
            event_type=EventType(str(row.get("event_type", ""))),
            tenant=tenant,
            subject_id=str(row.get("subject_id", "")),
            occurred_at=str(row.get("occurred_at", "")),
            market=str(row.get("market", "")),
            locale=str(row.get("locale", "")),
            detail=str(row.get("detail", "")),
            source_system=str(row.get("source_system", "")),
            attributes={str(k): str(v) for k, v in dict(attributes).items()},
        )
