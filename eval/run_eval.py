#!/usr/bin/env python3
"""Evaluation gate for Proactive Service Outreach (E5).

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change: it drives the REAL
  pipeline (trigger engine, consent port, eligibility engine, drafting validator, delivery) with
  SDK-free local adapters and scores six metrics. * **gate** - the promotion verdict from the shared
  model-quality-gate authority (requires the ``gcp`` profile), via
  ``agent_eval_kit.PromotionGateClient``.

Exit is ``0`` iff every metric meets its threshold (and, in gate mode, the authority agrees).

THE ORACLE IS THE DATASET, NEVER THE PIPELINE
---------------------------------------------
Every score below compares the engine's answer with a label a human wrote in
``datasets/golden_cases.jsonl`` or ``datasets/golden_drafts.jsonl`` from the policy and the
consent fixtures. No metric re-reads the pipeline's own verdict, no metric asks the redactor
whether it redacted, and no metric scores a drafter against facts that drafter chose. Each of
the six is proved able to go RED in ``tests/unit/test_not_falsely_green.py`` with
``agent_eval_kit.assert_can_go_red``: a metric that cannot fail is not a metric.

Every case runs on a FRESH container. Recording a send moves a cap counter, so a shared
container would make case 8's cap arithmetic depend on how many cases ran before it, and the
metric would be measuring test ordering.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_eval_kit import EvalMetricResult, EvalReport, PromotionGateClient, eval_main
from pii_kit import pack_leak

from proactive_outreach.adapters.local.audit import (
    LocalAuditAdapter,
)
from proactive_outreach.adapters.local.consent import (
    LocalConsentAdapter,
)
from proactive_outreach.adapters.local.delivery import (
    LocalChatDelivery,
)
from proactive_outreach.adapters.local.drafting import (
    TemplateDraftingAdapter,
)
from proactive_outreach.adapters.local.speech import (
    FixtureSpeechSynthesis,
)
from proactive_outreach.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from proactive_outreach.config import (
    Settings,
)
from proactive_outreach.domain.drafting import (
    validate_draft,
)
from proactive_outreach.domain.models import (
    DraftRequest,
    EventType,
    OutreachResult,
    ServiceEvent,
)
from proactive_outreach.domain.outreach_service import (
    OutreachService,
)
from proactive_outreach.domain.pii import (
    PII_PATTERNS,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"
DRAFT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_drafts.jsonl"

THRESHOLDS: dict[str, float] = {
    "eligibility_accuracy": 0.95,
    # 1.0, and nothing less. An unknown consent state that produces a contact once in a hundred
    # is not a ninety-nine percent pass; it is a service that contacts people who never agreed.
    "consent_fail_closed": 1.0,
    "frequency_cap_exactness": 1.0,
    "drafting_groundedness": 1.0,
    "review_safety": 1.0,
    "pii_safety": 0.99,
}
#: The registered model-quality-gate metric bundle for this vertical (model-quality-gate owns the
#: metrics + thresholds).
_BUNDLE = "proactive-service-outreach"

#: The consent labels whose cases the fail-closed metric scores: everything that is NOT a clean,
#: recognised grant. A store answer this deployment cannot fully understand belongs here too.
FAIL_CLOSED_FAMILIES = frozenset({"denied", "unknown"})


@dataclass(frozen=True, slots=True)
class Evaluated:
    """One golden case, run through the real pipeline, with its audit records."""

    case: dict[str, Any]
    result: OutreachResult
    audit_records: tuple[str, ...]


def _load(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


def _mean(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def run_case(case: dict[str, Any]) -> Evaluated:
    """Drive one golden case through the REAL pipeline on a fresh, isolated container."""
    settings = Settings(profile="local", audit_path=":memory:", tenant="demo-bank")
    audit = LocalAuditAdapter(settings)
    service = OutreachService(
        audit=audit,
        consent=LocalConsentAdapter(settings),
        drafting=TemplateDraftingAdapter(settings),
        delivery=LocalChatDelivery(settings),
        speech=FixtureSpeechSynthesis(settings),
        tracer=LocalNoopTracerAdapter(settings),
        policy=settings.policy,
    )
    event = ServiceEvent(
        event_id=str(case["event_id"]),
        event_type=EventType(str(case["event_type"])),
        tenant="demo-bank",
        subject_id=str(case["subject_id"]),
        occurred_at=str(case["occurred_at"]),
        market=str(case["market"]),
        locale=str(case["locale"]),
        detail=str(case.get("detail", "")),
        source_system="eval",
        attributes={str(k): str(v) for k, v in dict(case.get("attributes", {})).items()},
    )
    result = service.evaluate(
        event, actor="eval-bot", as_of=datetime.fromisoformat(str(case["as_of"]))
    )
    records = tuple(str(entry.get("redacted_summary", "")) for entry in audit.log.read_all())
    return Evaluated(case=case, result=result, audit_records=records)


# --------------------------------------------------------------------------------------- #
# The six scorers. Each takes ONE case and returns 0.0 or 1.0, so the falsification test can
# feed it a clean case and a mutated one and watch the score move.
# --------------------------------------------------------------------------------------- #
def eligibility_score(case: dict[str, Any]) -> float:
    """Did the engine reach the eligibility verdict the dataset says it should have?"""
    evaluated = run_case(case)
    verdict = evaluated.result.eligibility
    if verdict is None:  # pragma: no cover - every evaluation produces one
        return 0.0
    if verdict.eligible != bool(case["expected_eligible"]):
        return 0.0
    expected_reason = str(case["expected_reason"])
    reasons = set(verdict.reasons) | set(
        evaluated.result.trigger.reasons if evaluated.result.trigger else ()
    )
    return 1.0 if expected_reason in reasons else 0.0


def consent_fail_closed_score(case: dict[str, Any]) -> float:
    """For a denied or not-fully-understood consent state, did the engine REFUSE contact?

    Scored only over the cases the dataset labels as such, and the labelling is the dataset's,
    not the engine's. A case in this subset that ends eligible, or that delivers anything at
    all, is 0.0 with no partial credit.
    """
    if str(case.get("consent_family", "")) not in FAIL_CLOSED_FAMILIES:
        return 1.0
    evaluated = run_case(case)
    verdict = evaluated.result.eligibility
    if verdict is None or verdict.eligible or evaluated.result.delivered:
        return 0.0
    return 1.0 if str(case["expected_reason"]) in set(verdict.reasons) else 0.0


def cap_exactness_score(case: dict[str, Any]) -> float:
    """Is the remaining-contacts arithmetic EXACTLY what the dataset says, not merely close?"""
    evaluated = run_case(case)
    verdict = evaluated.result.eligibility
    if verdict is None:  # pragma: no cover - every evaluation produces one
        return 0.0
    return 1.0 if verdict.cap_remaining == int(case["expected_cap_remaining"]) else 0.0


def review_safety_score(case: dict[str, Any]) -> float:
    """Did a consequential result stay unsent, and a routine one avoid a manufactured review?"""
    evaluated = run_case(case)
    result = evaluated.result
    if result.requires_human_review != bool(case["expected_requires_review"]):
        return 0.0
    if result.delivered != bool(case["expected_delivered"]):
        return 0.0
    # The rule the whole flag exists for: nothing consequential may have been delivered.
    return 0.0 if (result.requires_human_review and result.delivered) else 1.0


def pii_safety_score(case: dict[str, Any]) -> float:
    """Did every raw identifier stay out of the immutable audit record?

    Two independent checks, because either alone can be falsely green: the pattern pack's own
    scan, and a literal search for the identifier the dataset planted. The second fires even if
    a pack row is broken, which is the lesson a previous rollout paid for.
    """
    evaluated = run_case(case)
    planted = str(case.get("planted", ""))
    for record in evaluated.audit_records:
        if pack_leak(record, PII_PATTERNS):
            return 0.0
        if planted and planted in record:
            return 0.0
    return 1.0


def groundedness_score(draft: dict[str, Any]) -> float:
    """Did the validator accept exactly the drafts the dataset says are safe to send?"""
    settings = Settings(profile="local")
    facts = {str(k): str(v) for k, v in dict(draft["facts"]).items()}
    request = DraftRequest(
        template_id=str(draft["template_id"]),
        locale=str(draft["locale"]),
        channel=str(draft["channel"]),
        facts=facts,
        max_chars=settings.policy.max_body_chars,
        required_facts=tuple(sorted(facts)),
    )
    verdict = validate_draft(str(draft["candidate"]), request, policy=settings.policy)
    return 1.0 if verdict.accepted == bool(draft["expected_accepted"]) else 0.0


def run_smoke(dataset: Path) -> EvalReport:
    cases = _load(dataset)
    drafts = _load(DRAFT_DATASET)

    fail_closed_cases = [
        case for case in cases if str(case.get("consent_family", "")) in FAIL_CLOSED_FAMILIES
    ]
    if not fail_closed_cases:
        raise SystemExit(
            f"{dataset}: no case is labelled denied or unknown, so consent_fail_closed would "
            "score a vacuous 1.0 over an empty set. Add the cases back."
        )

    results = (
        EvalMetricResult.scored(
            "eligibility_accuracy",
            _mean([eligibility_score(case) for case in cases]),
            THRESHOLDS["eligibility_accuracy"],
        ),
        EvalMetricResult.scored(
            "consent_fail_closed",
            _mean([consent_fail_closed_score(case) for case in fail_closed_cases]),
            THRESHOLDS["consent_fail_closed"],
        ),
        EvalMetricResult.scored(
            "frequency_cap_exactness",
            _mean([cap_exactness_score(case) for case in cases]),
            THRESHOLDS["frequency_cap_exactness"],
        ),
        EvalMetricResult.scored(
            "drafting_groundedness",
            _mean([groundedness_score(draft) for draft in drafts]),
            THRESHOLDS["drafting_groundedness"],
        ),
        EvalMetricResult.scored(
            "review_safety",
            _mean([review_safety_score(case) for case in cases]),
            THRESHOLDS["review_safety"],
        ),
        EvalMetricResult.scored(
            "pii_safety",
            _mean([pii_safety_score(case) for case in cases]),
            THRESHOLDS["pii_safety"],
        ),
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(cases) + len(drafts))


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile != "gcp":
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"OUTREACH_PROFILE=gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    client = PromotionGateClient(
        os.environ.get("OUTREACH_QUALITY_URL", "http://localhost:8084"),
        bundle=_BUNDLE,
        model="gemini-3.5-flash",
    )
    return client.evaluate(str(dataset)), client.gate(str(dataset))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / model-quality-gate for E5.",
        )
    )
