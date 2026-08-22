"""Minimal stdlib CLI: evaluate one event, or sweep a tenant's feed (argparse, no extra deps)."""

from __future__ import annotations

import argparse
import sys

from hex_service_kit.logging import configure_logging

from ..config import Container, build_container
from ..domain.models import EventQuery, EventType, ServiceEvent
from ..domain.outreach_service import OutreachService

_ATTRIBUTE_HELP = "name=value, repeatable; the closed fact set the message may quote"


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


def _attributes(pairs: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for pair in pairs:
        name, separator, value = pair.partition("=")
        if not separator:
            raise SystemExit(f"--attribute {pair!r} is not name=value")
        parsed[name.strip()] = value.strip()
    return parsed


def _report(container: Container, result: object, actor: str, tenant: str) -> None:
    """Print one result and, when it escalates, ROUTE it in the same breath (rule R8)."""
    from ..domain.models import OutreachResult

    assert isinstance(result, OutreachResult)
    print(f"{result.case_ref}: {result.severity.value} ({result.decision.value})")
    print(f"  {result.summary}")
    if result.eligibility is not None:
        verdict = result.eligibility
        print(
            f"  eligible: {verdict.eligible}"
            f"  consent: {verdict.consent_decision_id or 'none'}"
            f"  cap: {verdict.sends_in_window}/{verdict.cap_limit}"
        )
    if result.message is not None:
        print(f"  body ({result.message.source}): {result.message.body}")
    print(f"  delivered: {result.delivered} {result.delivery_ref}")
    if result.requires_human_review:
        # Rule R8 on the CLI path too: the same escalation, the same router. A surface that
        # only printed the flag would be a second place for an escalation to stop.
        ref = container.review_router.route(result, maker=actor, tenant=tenant)
        print(f"  routed to human review: {ref}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proactive_outreach")
    sub = parser.add_subparsers(dest="command", required=True)

    evaluate_cmd = sub.add_parser("evaluate", help="Evaluate a single operational event.")
    evaluate_cmd.add_argument("event_id")
    evaluate_cmd.add_argument("event_type", choices=[member.value for member in EventType])
    evaluate_cmd.add_argument("subject_id")
    evaluate_cmd.add_argument("occurred_at", help="ISO-8601 instant WITH a timezone")
    evaluate_cmd.add_argument("--market", default="SG")
    evaluate_cmd.add_argument("--locale", default="en-SG")
    evaluate_cmd.add_argument("--detail", default="")
    evaluate_cmd.add_argument("--attribute", action="append", default=[], help=_ATTRIBUTE_HELP)
    evaluate_cmd.add_argument("--actor", default="cli-user@bank.example")
    evaluate_cmd.add_argument("--tenant", default="", help="Tenant partition asserted to Hrz7.")

    sweep_cmd = sub.add_parser("sweep", help="Evaluate every detected event for a tenant.")
    sweep_cmd.add_argument("--tenant", default="demo-bank")
    sweep_cmd.add_argument("--since", default="")
    sweep_cmd.add_argument("--limit", type=int, default=50)
    sweep_cmd.add_argument("--actor", default="cli-user@bank.example")

    args = parser.parse_args(argv)
    container = build_container()
    # Idempotent: a process that is both an API app and a CLI configures once.
    configure_logging(container.settings.profile, service="proactive-service-outreach")
    service = _service(container)

    if args.command == "evaluate":
        tenant = args.tenant or container.settings.tenant
        event = ServiceEvent(
            event_id=args.event_id,
            event_type=EventType(args.event_type),
            tenant=tenant,
            subject_id=args.subject_id,
            occurred_at=args.occurred_at,
            market=args.market,
            locale=args.locale,
            detail=args.detail,
            source_system="cli",
            attributes=_attributes(args.attribute),
        )
        _report(container, service.evaluate(event, actor=args.actor), args.actor, tenant)
        return 0

    if args.command == "sweep":
        # No --as-of: quiet hours turn on the instant, so it is the service's to choose and
        # never the caller's. Replay lives in the eval and the demo, which contact nobody.
        query = EventQuery(tenant=args.tenant, since=args.since, limit=args.limit)
        for result in service.sweep(query, actor=args.actor):
            _report(container, result, args.actor, args.tenant)
        return 0

    return 2  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
