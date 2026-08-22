"""Drafting: the deterministic body, and the schema that judges whatever a model writes.

Two functions and one rule. :func:`render_template` produces the body from configured template
text and the closed fact set, in pure code, with no model anywhere near it.
:func:`validate_draft` takes what a model returned and decides whether it may be used at all.

The rule is that the model may PHRASE and may not INFORM. Everything a customer is told (the
card suffix, the retry date, the outage reference) comes from the event, through the trigger
engine's closed fact set, and a draft that contains a figure not in that set is discarded
rather than corrected. There is no repair path and no "fix it up and send it anyway": a
half-true notification about somebody's money is worse than the deterministic sentence the
template would have produced.

What the validator refuses, and why each one is a real failure rather than a style rule:

* not JSON, or not an object, or no ``body`` string: the output has no schema, so it has no
  meaning (P-08: validate model output, discard on failure);
* a body longer than the configured cap: a channel has limits, and a truncated legal sentence
  is a different sentence;
* a figure the facts do not contain: this is the hallucinated-number case, and it is checked
  by DIGIT RUN rather than by a fuzzy similarity score, because "did the model invent a number"
  has an exact answer;
* a required fact missing from the body: a notification that never says which card, or when,
  is not a notification;
* a phrase from the configured banned list: promises, compensation offers and the classic
  credential-phishing sentences a bank must never send;
* any personal data the pattern pack recognises: the facts are already minimised and masked,
  so an identifier appearing in a body came from the model and must not be delivered.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from pii_kit import pack_leak

from .kernel import Citation
from .models import DraftRequest, OutreachMessage, OutreachTrigger
from .pii import PII_PATTERNS
from .policy import OutreachPolicy

REASON_NOT_JSON = "draft_not_json"
REASON_NOT_OBJECT = "draft_not_an_object"
REASON_NO_BODY = "draft_body_missing"
REASON_TOO_LONG = "draft_too_long"
REASON_UNGROUNDED = "draft_ungrounded_figure"
REASON_MISSING_FACT = "draft_missing_required_fact"
REASON_BANNED = "draft_unsupported_claim"
REASON_PERSONAL_DATA = "draft_contains_personal_data"
REASON_ACCEPTED = "draft_accepted"

#: A run of digits, which is what an invented figure looks like. Currency separators and dates
#: are split into their runs, so "1,250" is checked as "1" and "250" and both must be grounded.
_DIGIT_RUN = re.compile(r"\d+")

#: Placeholders a template may carry. Anything else in the template text is literal.
_PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")


class DraftVerdict:
    """Whether a draft may be used, why not if not, and the message when it may.

    A plain class rather than a frozen dataclass because it carries an optional message and is
    never serialised; the two attributes are set once in the constructor and never mutated.
    """

    __slots__ = ("message", "reasons")

    def __init__(self, reasons: tuple[str, ...], message: OutreachMessage | None) -> None:
        self.reasons = reasons
        self.message = message

    @property
    def accepted(self) -> bool:
        return self.message is not None


def _grounded_digits(facts: Mapping[str, str]) -> set[str]:
    """Every digit run that appears in a fact value: the closed set a body may quote."""
    allowed: set[str] = set()
    for value in facts.values():
        allowed.update(_DIGIT_RUN.findall(value))
    return allowed


def render_template(request: DraftRequest, *, policy: OutreachPolicy) -> OutreachMessage | None:
    """The deterministic body, built from configured template text and the fact set.

    ``None`` when no template is configured for the id: a body cannot be improvised, and a
    notification with no configured wording is a gap for the policy owner to close, not
    something for this code to invent.
    """
    template = policy.template_for(request.template_id)
    if template is None:
        return None
    missing = [
        name for name in _PLACEHOLDER.findall(template) if not request.facts.get(name, "").strip()
    ]
    if missing:
        return None
    body = _PLACEHOLDER.sub(lambda m: str(request.facts.get(m.group(1), "")), template)
    return OutreachMessage(
        template_id=request.template_id,
        channel=request.channel,
        locale=request.locale,
        body=body.strip(),
        source="template",
        facts_used=tuple(sorted(request.facts)),
        citations=(
            Citation(
                source_id=f"policy:template:{request.template_id}",
                title="Configured message template",
                snippet=template,
            ),
        ),
    )


def validate_draft(raw: str, request: DraftRequest, *, policy: OutreachPolicy) -> DraftVerdict:
    """Judge a model's draft against the schema, the facts and the policy. Never repair it."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return DraftVerdict((REASON_NOT_JSON,), None)
    if not isinstance(parsed, dict):
        return DraftVerdict((REASON_NOT_OBJECT,), None)
    body = parsed.get("body")
    if not isinstance(body, str) or not body.strip():
        return DraftVerdict((REASON_NO_BODY,), None)
    body = body.strip()

    reasons: list[str] = []
    if len(body) > request.max_chars:
        reasons.append(REASON_TOO_LONG)

    allowed_digits = _grounded_digits(request.facts)
    invented = sorted({run for run in _DIGIT_RUN.findall(body) if run not in allowed_digits})
    if invented:
        reasons.extend(f"{REASON_UNGROUNDED}:{run}" for run in invented)

    lowered = body.lower()
    for name in request.required_facts:
        value = request.facts.get(name, "").strip()
        if not value or value.lower() not in lowered:
            reasons.append(f"{REASON_MISSING_FACT}:{name}")
    for phrase in policy.banned_phrases:
        if phrase in lowered:
            reasons.append(f"{REASON_BANNED}:{phrase}")
    if pack_leak(body, PII_PATTERNS):
        reasons.append(REASON_PERSONAL_DATA)

    if reasons:
        return DraftVerdict(tuple(reasons), None)
    return DraftVerdict(
        (REASON_ACCEPTED,),
        OutreachMessage(
            template_id=request.template_id,
            channel=request.channel,
            locale=request.locale,
            body=body,
            source="model",
            facts_used=tuple(sorted(request.facts)),
            citations=(
                Citation(
                    source_id=f"event-facts:{request.template_id}",
                    title="Grounding facts",
                    snippet="; ".join(f"{k}={v}" for k, v in sorted(request.facts.items())),
                ),
            ),
        ),
    )


def draft_request_for(trigger: OutreachTrigger, *, policy: OutreachPolicy) -> DraftRequest:
    """The closed brief a drafter receives for one fired trigger."""
    return DraftRequest(
        template_id=trigger.template_id,
        locale=trigger.locale,
        channel=trigger.channel,
        facts=dict(trigger.facts),
        max_chars=policy.max_body_chars,
        required_facts=tuple(sorted(trigger.facts)),
    )


__all__ = [
    "REASON_ACCEPTED",
    "REASON_BANNED",
    "REASON_MISSING_FACT",
    "REASON_NOT_JSON",
    "REASON_NOT_OBJECT",
    "REASON_NO_BODY",
    "REASON_PERSONAL_DATA",
    "REASON_TOO_LONG",
    "REASON_UNGROUNDED",
    "DraftVerdict",
    "draft_request_for",
    "render_template",
    "validate_draft",
]
