"""The eligibility engine: may this contact be made, at this instant, on this evidence?

Four questions compose into one verdict: consent, suppression, frequency cap and quiet hours.
Pure stdlib, frozen in and frozen out, with an EXPLICIT ``as_of`` and no clock, so a decision
about contacting a person replays exactly. No model is consulted here and none can be: the
drafting port is not reachable from this module, and the service will not call it until this
engine has answered ``eligible``.

Worst wins. Every check that refuses contributes its reason, all reasons are carried, and one
refusal is enough. There is no scoring, no weighting and no "two soft failures make a pass".

FAIL CLOSED ON ANY UNKNOWN CONSENT STATE
----------------------------------------
This is the rule the whole module exists for, and it is deliberately stricter than "the store
said no":

* **no decision at all** (the store was unreachable, the port raised, nobody asked) denies. An
  absent answer is not a permissive one;
* **any outcome other than the exact allow token** denies. Not ``outcome != "denied"``: a
  truncated body, a typo, or an outcome string a newer store introduced would all pass that
  test, and each of them would be read as permission to contact a person;
* **a reason token this deployment does not recognise** denies, even alongside an allow. A
  store newer than the pinned client is far likelier to have added a refusal than a
  pleasantry, and ``consent-preference-kit`` already classifies unknown tokens as denying;
* **a decision about a different question** denies (``consent_mismatch``). A cached answer for
  another channel, purpose, subject or tenant is not an answer to this question;
* **a decision pinned to a different instant** denies (``consent_stale``). The store answers
  "as at T"; using it to justify a send at some other T is a decision nobody made;
* **an unconfigured cap or an unconfigured market** denies. A requirement nobody configured is
  a gap, never a pass. This is the direction that hurts: the opposite convention is how a
  market with no quiet-hours row gets telephoned at 03:00.
"""

from __future__ import annotations

from datetime import datetime

from consent_preference_kit import OUTCOME_ALLOWED, ConsentDecision

from .kernel import Citation
from .models import EligibilityDecision, OutreachTrigger
from .policy import OutreachPolicy

REASON_TRIGGER_NOT_FIRED = "trigger_did_not_fire"
REASON_CONSENT_UNKNOWN = "consent_unknown"
REASON_CONSENT_NOT_ALLOWED = "consent_not_allowed"
REASON_CONSENT_UNKNOWN_TOKEN = "consent_unknown_reason"
REASON_CONSENT_MISMATCH = "consent_mismatch"
REASON_CONSENT_STALE = "consent_stale"
REASON_SUPPRESSED = "suppressed"
REASON_CAP_UNCONFIGURED = "frequency_cap_unconfigured"
REASON_CAP_EXCEEDED = "frequency_cap_exceeded"
REASON_QUIET_UNCONFIGURED = "quiet_hours_unconfigured"
REASON_QUIET_HOURS = "quiet_hours"
REASON_ELIGIBLE = "eligible"

#: Every reason token this engine can emit that DENIES. Exported so the eval oracle and the
#: demo can assert against the vocabulary instead of against a hand-copied list of strings.
DENYING_REASONS: frozenset[str] = frozenset(
    {
        REASON_TRIGGER_NOT_FIRED,
        REASON_CONSENT_UNKNOWN,
        REASON_CONSENT_NOT_ALLOWED,
        REASON_CONSENT_UNKNOWN_TOKEN,
        REASON_CONSENT_MISMATCH,
        REASON_CONSENT_STALE,
        REASON_SUPPRESSED,
        REASON_CAP_UNCONFIGURED,
        REASON_CAP_EXCEEDED,
        REASON_QUIET_UNCONFIGURED,
        REASON_QUIET_HOURS,
    }
)


def _consent_reasons(
    trigger: OutreachTrigger, consent: ConsentDecision | None, as_of_iso: str
) -> tuple[list[str], list[Citation]]:
    """Everything the consent answer refuses for, in the order the checks are written.

    Note what this function CANNOT do: there is no branch in it that removes a reason, and no
    branch that returns an empty list because a field was absent. Absence adds a reason.
    """
    if consent is None:
        return [REASON_CONSENT_UNKNOWN], []

    reasons: list[str] = []
    citations = [
        Citation(
            source_id=f"consent:{consent.id}",
            title="Consent and preference store decision",
            snippet=(
                f"outcome={consent.outcome or 'absent'}; "
                f"reasons={', '.join(consent.reasons) or 'none'}"
            ),
        )
    ]
    citations.extend(
        Citation(source_id=c.source_id, title=c.title, snippet=c.snippet) for c in consent.citations
    )

    if consent.outcome != OUTCOME_ALLOWED:
        reasons.append(REASON_CONSENT_NOT_ALLOWED)
        reasons.extend(consent.denying_reasons)
    elif consent.denying_reasons:
        # An allow carrying a denying or unrecognised reason is a contradiction. Refuse it
        # rather than deciding which half of the store's answer to believe.
        reasons.append(REASON_CONSENT_NOT_ALLOWED)
        reasons.extend(consent.denying_reasons)
    if consent.unknown_reasons:
        reasons.append(REASON_CONSENT_UNKNOWN_TOKEN)
    if (
        consent.tenant != trigger.tenant
        or consent.subject_id != trigger.subject_id
        or consent.purpose != trigger.purpose
        or consent.channel != trigger.channel
    ):
        reasons.append(REASON_CONSENT_MISMATCH)
    if consent.as_of != as_of_iso:
        reasons.append(REASON_CONSENT_STALE)
    return reasons, citations


def assess(
    trigger: OutreachTrigger,
    *,
    consent: ConsentDecision | None,
    policy: OutreachPolicy,
    as_of_iso: str,
    local_hour_source: str = "",
) -> EligibilityDecision:
    """Decide eligibility for one fired trigger, at one explicit instant.

    ``as_of_iso`` is the instant in ISO-8601 form and is the SAME string handed to the consent
    store, which is what makes the ``consent_stale`` check meaningful rather than decorative.
    ``local_hour_source`` is unused by the arithmetic and exists only so a caller can record
    which clock it believed; the quiet-hours decision comes from the configured offset.
    """
    reasons: list[str] = []
    citations: list[Citation] = list(trigger.citations)

    if not trigger.fired:
        return EligibilityDecision(
            eligible=False,
            as_of=as_of_iso,
            reasons=(REASON_TRIGGER_NOT_FIRED, *trigger.reasons),
            citations=tuple(citations),
        )

    consent_reasons, consent_citations = _consent_reasons(trigger, consent, as_of_iso)
    reasons.extend(consent_reasons)
    citations.extend(consent_citations)

    if policy.is_suppressed(trigger.subject_id):
        reasons.append(REASON_SUPPRESSED)
        citations.append(
            Citation(
                source_id="policy:suppression",
                title="Suppression list",
                snippet=f"{trigger.subject_id} is suppressed for all outreach",
            )
        )

    # ------------------------------------------------------------------ cap
    cap = policy.cap_for(trigger.purpose, trigger.channel)
    sends_in_window = consent.sends_in_window if consent is not None else 0
    cap_limit = 0
    if cap is None:
        reasons.append(REASON_CAP_UNCONFIGURED)
    else:
        # Worst wins across the two authorities. The store may carry a tighter limit than this
        # deployment's policy (a market rule, a subject-level preference); taking the smaller
        # of the two means neither authority can be widened by the other's silence.
        store_limit = consent.cap_limit if consent is not None else None
        cap_limit = cap.limit if store_limit is None else min(cap.limit, store_limit)
        citations.append(
            Citation(
                source_id=f"policy:cap:{policy.cap_key(trigger.purpose, trigger.channel)}",
                title="Frequency cap",
                snippet=(
                    f"limit {cap_limit} per {cap.window_hours}h; "
                    f"{sends_in_window} already sent in the window"
                ),
            )
        )
        if sends_in_window >= cap_limit:
            reasons.append(REASON_CAP_EXCEEDED)

    cap_remaining = max(cap_limit - sends_in_window, 0)

    # ---------------------------------------------------------- quiet hours
    quiet = policy.quiet_hours_for(trigger.market)
    quiet_window = ""
    if quiet is None:
        reasons.append(REASON_QUIET_UNCONFIGURED)
    else:
        quiet_window = quiet.window
        moment = datetime.fromisoformat(as_of_iso)
        citations.append(
            Citation(
                source_id=f"policy:quiet_hours:{trigger.market}",
                title="Quiet hours",
                snippet=f"{quiet_window}; market-local hour {quiet.local_hour(moment):02d}",
            )
        )
        if quiet.contains(moment):
            reasons.append(REASON_QUIET_HOURS)

    denying = [reason for reason in reasons if reason != REASON_ELIGIBLE]
    eligible = not denying
    return EligibilityDecision(
        eligible=eligible,
        as_of=as_of_iso,
        reasons=tuple(denying) if denying else (REASON_ELIGIBLE,),
        consent_decision_id=consent.id if consent is not None else "",
        consent_outcome=consent.outcome if consent is not None else "",
        cap_limit=cap_limit,
        sends_in_window=sends_in_window,
        cap_remaining=cap_remaining,
        quiet_hours_window=quiet_window,
        citations=tuple(citations),
    )


__all__ = [
    "DENYING_REASONS",
    "REASON_CAP_EXCEEDED",
    "REASON_CAP_UNCONFIGURED",
    "REASON_CONSENT_MISMATCH",
    "REASON_CONSENT_NOT_ALLOWED",
    "REASON_CONSENT_STALE",
    "REASON_CONSENT_UNKNOWN",
    "REASON_CONSENT_UNKNOWN_TOKEN",
    "REASON_ELIGIBLE",
    "REASON_QUIET_HOURS",
    "REASON_QUIET_UNCONFIGURED",
    "REASON_SUPPRESSED",
    "REASON_TRIGGER_NOT_FIRED",
    "assess",
]
