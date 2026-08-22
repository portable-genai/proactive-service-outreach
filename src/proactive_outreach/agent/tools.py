"""Tool functions an agent runtime calls: thin, side-effect-honest wrappers on the services.

Design rules, in the order they matter:

* **No business logic here.** The domain service decides HOW; the model only decides WHICH tool
  to call. A rule that lives in a tool wrapper is a rule the CLI and the API do not have.
* **Rule R8 applies on this path too.** A result that must not auto-execute is ROUTED from
  inside the tool, in the same call that produced it. An agent surface that only returned the
  flag would be a third place an escalation can quietly stop, after the API and the CLI.
* **Import-safe without a runtime.** ``google.adk`` is imported lazily inside
  :func:`build_function_tools`, so these callables are importable, testable and runnable with
  no ADK and no cloud SDK installed.
* **Typed and documented.** A runtime derives each tool's name, description and JSON parameter
  schema from the signature and the docstring, so both are part of the contract.

One more rule that is specific to this vertical: an agent may ASK about outreach and may cause
outreach to be EVALUATED, but the decision to contact a customer stays with the deterministic
engine. There is no tool here that sends a message, overrides an eligibility refusal or edits a
drafted body, because a model that could do any of those would be the thing deciding whether a
person is contacted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hex_service_kit.serialization import to_jsonable
from pii_kit import redact

from ..config import Container, Settings, build_container
from ..domain.models import EventQuery, EventType, ServiceEvent
from ..domain.outreach_service import OutreachService
from ..domain.pii import PII_PATTERNS

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

#: The identity a tool call is attributed to when the runtime propagates none. It names the
#: SERVICE, not a person, so an unattributed action is never mistaken for a human's.
DEFAULT_ACTOR = "proactive-service-outreach-agent"


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def _service(container: Container) -> OutreachService:
    return OutreachService(
        audit=container.audit,
        consent=container.consent,
        drafting=container.drafting,
        delivery=container.delivery,
        speech=container.speech,
        tracer=container.tracer,
        events=container.events,
        policy=container.settings.policy,
    )


def _redacted(node: Any) -> Any:
    """Mask personal data in every string of a tool result, however deeply it is nested.

    A tool result is not an API response. The API returns to the authenticated caller the text
    that caller just submitted; a TOOL result goes into a model's context, and P-04 says
    minimise the data that reaches a model. Walking the whole structure rather than three named
    fields means a future field cannot arrive unredacted just because nobody remembered to add
    it.
    """
    if isinstance(node, str):
        return redact(node, PII_PATTERNS)
    if isinstance(node, dict):
        return {key: _redacted(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_redacted(value) for value in node]
    return node


def evaluate_service_event(
    event_id: str,
    event_type: str,
    subject_id: str,
    occurred_at: str,
    market: str = "SG",
    locale: str = "en-SG",
    detail: str = "",
    attributes: dict[str, str] | None = None,
    actor: str = DEFAULT_ACTOR,
    tenant: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Decide one operational event and route it for human review when it must not auto-send.

    Runs the deterministic pipeline: trigger rules, the consent question, the eligibility
    engine (consent, suppression, frequency cap, quiet hours), and only then a drafted body,
    schema-validated against the event's own facts. A consequential event is never delivered
    from here; it is held and routed to the human-review console (rule R8).

    Args:
      event_id: The source system's identifier for this event.
      event_type: One of failed_payment, delivery_exception, expiring_card, fraud_hold, outage.
      subject_id: The pseudonymous key for the customer, never a name.
      occurred_at: ISO-8601 instant WITH a timezone.
      market: The market whose quiet hours and consent rules apply.
      locale: The locale the notification would be written in.
      detail: Free text from the source system. Redacted before anything else happens.
      attributes: The deterministic facts a message may quote.
      actor: The verified identity this call is attributed to.
      tenant: Tenant partition asserted on an outbound review.

    Returns:
      A JSON-safe result dict with every string masked for personal data, plus ``review_ref``:
      where the escalation WENT. It is empty only when the result did not escalate.
    """
    container = _container(settings)
    event = ServiceEvent(
        event_id=event_id,
        event_type=EventType(event_type),
        tenant=tenant or container.settings.tenant,
        subject_id=subject_id,
        occurred_at=occurred_at,
        market=market,
        locale=locale,
        detail=detail,
        source_system="agent",
        attributes=dict(attributes or {}),
    )
    result = _service(container).evaluate(event, actor=actor)
    review_ref = ""
    if result.requires_human_review:
        review_ref = container.review_router.route(result, maker=actor, tenant=tenant)
    payload = _redacted(to_jsonable(result))
    if not isinstance(payload, dict):  # pragma: no cover - dataclasses serialise to objects
        raise TypeError("an outreach result must serialise to a JSON object")
    # Attached after the redaction pass: it is a routing reference, not narrative text, and
    # masking an identifier would break the caller's ability to look the review up.
    payload["review_ref"] = review_ref
    return payload


def sweep_service_events(
    tenant: str = "",
    since: str = "",
    limit: int = 20,
    actor: str = DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Evaluate every detected event for one tenant and report what happened to each.

    There is deliberately no parameter for the instant to decide against. Quiet hours turn on
    it, so a model that could choose it could ask for a decision "as at 14:00" at 23:00 and
    have the engine agree the market was open. The service decides against the wall clock.

    Args:
      tenant: The tenant partition to sweep.
      since: Only consider events at or after this ISO-8601 instant.
      limit: The maximum number of events to evaluate.
      actor: The verified identity this call is attributed to.

    Returns:
      A JSON-safe dict with ``results`` (one masked result per event, each carrying its own
      ``review_ref``) and the counts a caller usually wants: evaluated, delivered, held.
    """
    container = _container(settings)
    query = EventQuery(tenant=tenant or container.settings.tenant, since=since, limit=limit)
    results = _service(container).sweep(query, actor=actor)
    payloads: list[Any] = []
    held = 0
    delivered = 0
    for result in results:
        review_ref = ""
        if result.requires_human_review:
            held += 1
            review_ref = container.review_router.route(result, maker=actor, tenant=query.tenant)
        delivered += 1 if result.delivered else 0
        payload = _redacted(to_jsonable(result))
        if isinstance(payload, dict):
            payload["review_ref"] = review_ref
        payloads.append(payload)
    return {
        "results": payloads,
        "evaluated": len(results),
        "delivered": delivered,
        "held_for_review": held,
    }


def verify_audit_trail(settings: Settings | None = None) -> dict[str, Any]:
    """Verify the audit trail's hash chain and its external head anchor.

    Returns:
      A dict with ``ok``, the record counts and a ``detail`` string. ``ok`` is false for an
      edited, deleted or reordered record, and, when an external anchor is configured, for a
      truncated tail as well. Without an anchor a truncation cannot be detected, and the detail
      says so rather than implying a stronger guarantee than the store provides.
    """
    resolved = settings or Settings.load()
    audit = _container(resolved).audit
    verify = getattr(audit, "verify", None)
    if verify is None:
        raise NotImplementedError(
            f"the {resolved.profile} audit adapter does not expose chain verification; a "
            "managed WORM sink is verified by its own retention policy, not from here"
        )
    report = verify()
    return {
        "ok": report.ok,
        "entries": report.entries,
        "chained": report.chained,
        "legacy": report.legacy,
        "first_bad_seq": report.first_bad_seq,
        "detail": report.detail,
        "anchored": bool(resolved.audit_anchor_path),
    }


#: The tool table. The agent card advertises exactly these, by function name.
TOOL_FUNCTIONS = (evaluate_service_event, sweep_service_events, verify_audit_trail)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each callable as a runtime FunctionTool (the only ADK-dependent code path).

    The import is deliberately here rather than at module scope: without it this module, the
    card and every tool would need an agent runtime installed to be imported at all, and the
    offline gate installs none.
    """
    # No ignore comment: the missing-import error for this module is already reported (and
    # ignored) at the TYPE_CHECKING import above, and a second one would be flagged as unused.
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=function) for function in TOOL_FUNCTIONS]
