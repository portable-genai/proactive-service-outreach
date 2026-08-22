"""Every eval metric is proved able to go RED. A metric that cannot fail is not a metric.

This is the standing answer to the most expensive failure mode in an eval suite: a scorer that
reads the product's own claims, or a golden set that planted no target, so the strictest-looking
metric is a constant 1.0 upstream of every subtlety. All six metrics report 1.000 on the shipped
dataset, which is exactly the situation in which somebody should be suspicious, so each one is
handed a MUTANT here and must score below its threshold on it.

The mutants are the real defects, not synthetic noise:

* ``eligibility_accuracy`` : the dataset's label flipped, which is what a golden set silently
  disagreeing with the engine looks like;
* ``consent_fail_closed``  : an unknown subject relabelled as a clean grant, which is the
  absence-read-as-consent defect this whole repo is built against;
* ``frequency_cap_exactness`` : the expected remaining count moved by one, because "roughly the
  right number of messages" is not a frequency cap;
* ``drafting_groundedness`` : a draft with an invented figure labelled acceptable;
* ``review_safety`` : a consequential case relabelled as one that may be delivered;
* ``pii_safety`` : the same audit summary with redaction switched off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval_kit import assert_can_go_red
from eval.run_eval import (  # type: ignore[import-not-found]
    THRESHOLDS,
    cap_exactness_score,
    consent_fail_closed_score,
    eligibility_score,
    groundedness_score,
    review_safety_score,
)
from pii_kit import pack_leak, redact

from proactive_outreach.domain.pii import (
    PII_PATTERNS,
)

from tests import REPO_ROOT

_CASES = REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"
_DRAFTS = REPO_ROOT / "eval" / "datasets" / "golden_drafts.jsonl"


def _load(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            row = json.loads(line)
            rows[str(row["id"])] = row
    return rows


def _case(case_id: str, **mutations: Any) -> dict[str, Any]:
    return {**_load(_CASES)[case_id], **mutations}


def _draft(draft_id: str, **mutations: Any) -> dict[str, Any]:
    return {**_load(_DRAFTS)[draft_id], **mutations}


def test_eligibility_accuracy_can_go_red() -> None:
    assert_can_go_red(
        eligibility_score,
        green=_case("c1"),
        # The dataset now says this contact must be refused; the engine allows it. A metric that
        # could not see that disagreement would be scoring the engine against itself.
        red=_case("c1", expected_eligible=False, expected_reason="consent_withdrawn"),
        threshold=THRESHOLDS["eligibility_accuracy"],
        metric="eligibility_accuracy",
    )


def test_consent_fail_closed_can_go_red() -> None:
    """The mutant is the defect itself: an unknown subject treated as a grant."""
    assert_can_go_red(
        consent_fail_closed_score,
        green=_case("c5"),
        red=_case("c5", expected_eligible=True, expected_reason="eligible"),
        threshold=THRESHOLDS["consent_fail_closed"],
        metric="consent_fail_closed",
    )


def test_frequency_cap_exactness_can_go_red() -> None:
    assert_can_go_red(
        cap_exactness_score,
        green=_case("c2"),
        red=_case("c2", expected_cap_remaining=1),
        threshold=THRESHOLDS["frequency_cap_exactness"],
        metric="frequency_cap_exactness",
    )


def test_drafting_groundedness_can_go_red() -> None:
    assert_can_go_red(
        groundedness_score,
        green=_draft("d2"),
        # d2 invents an amount. Labelling it acceptable is what a permissive validator would
        # need in order to look correct.
        red=_draft("d2", expected_accepted=True),
        threshold=THRESHOLDS["drafting_groundedness"],
        metric="drafting_groundedness",
    )


def test_review_safety_can_go_red() -> None:
    assert_can_go_red(
        review_safety_score,
        green=_case("c3"),
        red=_case("c3", expected_requires_review=False, expected_delivered=True),
        threshold=THRESHOLDS["review_safety"],
        metric="review_safety",
    )


_RAW_SUMMARY = (
    "outreach:failed_payment:gc-4101 :: delivered on chat :: "
    "issuer note records NRIC S1234567D on file"
)


def _pii_safety(summary: str) -> float:
    """1.0 unless a raw identifier (per the shared pack) survives into the summary."""
    return 0.0 if pack_leak(summary, PII_PATTERNS) else 1.0


def test_pii_safety_can_go_red() -> None:
    assert_can_go_red(
        _pii_safety,
        green=redact(_RAW_SUMMARY, PII_PATTERNS),  # redaction on: the NRIC is masked
        red=_RAW_SUMMARY,  # redaction off (the mutant): the raw NRIC survives
        threshold=THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )
