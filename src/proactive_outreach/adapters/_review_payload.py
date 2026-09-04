"""Shared conversion from an escalated result to an ``review-kit`` Review payload.

Lives in the adapter layer, not the pure domain, because it depends on the kit. The subject, summary
and every citation snippet are redacted BEFORE they leave the process (the same
redact-before-anything rule the audit write obeys), using the shared ``pii-kit``, so no raw
identifier reaches human-review-console over the wire; human-review-console redacts again before its
own audit write (defence in depth). ``maker`` and ``tenant`` are asserted here and trusted by
human-review-console because the caller is an authenticated S2S service; per-hop on-behalf-of token
exchange is the deferred next layer.
"""

from __future__ import annotations

import re

from pii_kit import NATIONAL_ID_PATTERNS, UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit import redact as pii_redact
from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.kernel import Severity
from ..domain.models import OutreachResult

#: Cap the citations carried on the wire: enough for a reviewer to trace the decision without
#: copying the whole evidence set into the console.
_MAX_CITATIONS = 8

#: The console is a SHARED sink: a case filed in one market may still quote another market's
#: national id, so the payload is scrubbed against every jurisdiction's rows plus the universal
#: email/phone rows, whatever this deployment's own ``domain.pii.JURISDICTIONS`` selects.
_ALL_PATTERNS = (
    *national_patterns_for(tuple(NATIONAL_ID_PATTERNS.keys())),
    *UNIVERSAL_PATTERNS,
)

#: Bands that demand dual control (two approvals) rather than a single checker.
_DUAL_CONTROL = (Severity.CRITICAL,)


def _redact(text: str) -> str:
    """Mask every jurisdiction's identifiers plus email/phone, and normalise whitespace."""
    return re.sub(r"\s+", " ", pii_redact(text, _ALL_PATTERNS)).strip()


def _kit_citations(result: OutreachResult) -> tuple[KitCitation, ...]:
    seen: set[str] = set()
    out: list[KitCitation] = []
    for citation in result.citations:
        if citation.source_id in seen:
            continue
        seen.add(citation.source_id)
        out.append(
            KitCitation(
                source_id=citation.source_id,
                title=citation.title,
                snippet=_redact(citation.snippet),
            )
        )
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def result_to_review(result: OutreachResult, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to human-review-console when an outreach must not
    auto-execute.

    What the reviewer is asked to approve is a MESSAGE TO A CUSTOMER, so the body travels on the
    summary (redacted, like everything else) rather than being left behind for the console to
    fetch. A reviewer who cannot see the words cannot approve them.
    """
    body = result.message.body if result.message is not None else "(no body was drafted)"
    return Review(
        action="proactive_outreach:notify",
        subject=_redact(result.case_ref),
        maker=maker,
        tenant=tenant,
        summary=_redact(f"{result.summary} :: proposed body: {body}"),
        severity=result.severity.value,
        required_approvals=2 if result.severity in _DUAL_CONTROL else 1,
        sod_group="proactive_outreach-maker-checker",
        case_ref=result.case_ref,
        # Producer-owned, tenant-scoped key so a retried delivery is idempotent at the console.
        source_key=f"proactive-service-outreach:{result.event_id}:{result.severity.value}",
        citations=_kit_citations(result),
    )
