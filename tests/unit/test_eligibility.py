"""The eligibility engine, and the one property it exists for: unknown consent DENIES.

Every test below that starts ``test_consent_`` is a different way for a consent answer to be
less than a clean, current, recognised grant, and every one of them must end with contact
refused. They are written separately rather than as one parametrised sweep because each is a
distinct real-world failure with its own fix, and a reader who greps for "stale" should land on
the case rather than on a table row.

Nothing here uses the wall clock. Quiet hours are the one rule that turns on WHEN the decision
is made, so both instants are pinned in ``tests/fixtures/sample_cases.py``: a suite that passed
before 22:00 and failed after it would be a suite nobody trusts.
"""

from __future__ import annotations

from dataclasses import replace

from consent_preference_kit import ConsentDecision

from proactive_outreach.domain import eligibility, trigger_engine
from proactive_outreach.domain.policy import DEFAULT_POLICY, FrequencyCap, OutreachPolicy

from tests.fixtures import sample_cases

_OPEN = sample_cases.OPEN_INSTANT.isoformat()
_QUIET = sample_cases.QUIET_INSTANT.isoformat()


def _trigger(as_of_iso: str = _OPEN):  # type: ignore[no-untyped-def]
    moment = sample_cases.OPEN_INSTANT if as_of_iso == _OPEN else sample_cases.QUIET_INSTANT
    return trigger_engine.evaluate(sample_cases.ROUTINE_EVENT, policy=DEFAULT_POLICY, as_of=moment)


def _allow(as_of_iso: str = _OPEN, **overrides: object) -> ConsentDecision:
    """A clean grant for the canonical question. Every test mutates ONE field of it."""
    base = ConsentDecision(
        id="cd-test-0001",
        tenant=sample_cases.TENANT,
        subject_id=sample_cases.ROUTINE_EVENT.subject_id,
        purpose="service",
        channel="chat",
        outcome="allowed",
        reasons=("consent_granted", "channel_opted_in", "within_frequency_cap"),
        market="AU",
        vertical="banking",
        as_of=as_of_iso,
        cap_limit=5,
        sends_in_window=0,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _assess(  # type: ignore[no-untyped-def]
    consent: ConsentDecision | None,
    as_of_iso: str = _OPEN,
    policy: OutreachPolicy | None = None,
):
    return eligibility.assess(
        _trigger(as_of_iso),
        consent=consent,
        policy=policy or DEFAULT_POLICY,
        as_of_iso=as_of_iso,
    )


# --------------------------------------------------------------------------- #
# The happy path, so the refusals below mean something
# --------------------------------------------------------------------------- #
def test_a_clean_grant_inside_the_cap_and_outside_quiet_hours_is_eligible() -> None:
    verdict = _assess(_allow())
    assert verdict.eligible is True
    assert verdict.reasons == (eligibility.REASON_ELIGIBLE,)
    assert verdict.consent_decision_id == "cd-test-0001"
    assert verdict.cap_remaining == 3


# --------------------------------------------------------------------------- #
# Unknown consent, in every shape it comes in
# --------------------------------------------------------------------------- #
def test_consent_absent_entirely_denies() -> None:
    """No decision at all is not a permissive one. This is the store-unreachable case."""
    verdict = _assess(None)
    assert verdict.eligible is False
    assert eligibility.REASON_CONSENT_UNKNOWN in verdict.reasons
    assert verdict.consent_decision_id == ""


def test_consent_with_an_empty_outcome_denies() -> None:
    """A truncated or partially parsed answer must not read as permission."""
    assert _assess(_allow(outcome="")).eligible is False


def test_consent_with_an_outcome_this_client_has_never_heard_of_denies() -> None:
    """Deliberately not ``outcome != "denied"``: a newer store's token is not an allow."""
    verdict = _assess(_allow(outcome="allowed_with_conditions"))
    assert verdict.eligible is False
    assert eligibility.REASON_CONSENT_NOT_ALLOWED in verdict.reasons


def test_consent_denied_denies_and_carries_the_store_reason_through() -> None:
    verdict = _assess(_allow(outcome="denied", reasons=("consent_withdrawn",)))
    assert verdict.eligible is False
    assert "consent_withdrawn" in verdict.reasons


def test_an_allow_carrying_an_unrecognised_reason_token_denies() -> None:
    """A store newer than its client is likelier to have added a refusal than a pleasantry."""
    verdict = _assess(_allow(reasons=("consent_granted", "seasonal_preference_pending")))
    assert verdict.eligible is False
    assert eligibility.REASON_CONSENT_UNKNOWN_TOKEN in verdict.reasons


def test_an_allow_that_also_carries_a_denying_reason_denies() -> None:
    """A contradiction is refused rather than resolved in the permissive direction."""
    verdict = _assess(_allow(reasons=("consent_granted", "suppressed")))
    assert verdict.eligible is False


def test_consent_about_a_different_question_denies() -> None:
    """A cached answer for another channel, purpose, subject or tenant is not an answer."""
    for field, value in (
        ("channel", "voice"),
        ("purpose", "marketing"),
        ("subject_id", "subj-000999"),
        ("tenant", "other-bank"),
    ):
        verdict = _assess(_allow(**{field: value}))
        assert verdict.eligible is False, f"a decision differing only in {field} was accepted"
        assert eligibility.REASON_CONSENT_MISMATCH in verdict.reasons


def test_consent_pinned_to_a_different_instant_denies() -> None:
    """The store answers "as at T"; using it to justify a send at some other T is nobody's call."""
    verdict = _assess(_allow(as_of="2026-01-01T00:00:00+00:00"))
    assert verdict.eligible is False
    assert eligibility.REASON_CONSENT_STALE in verdict.reasons


# --------------------------------------------------------------------------- #
# Suppression, caps and quiet hours
# --------------------------------------------------------------------------- #
def test_a_suppressed_subject_is_refused_whatever_the_store_says() -> None:
    policy = replace(DEFAULT_POLICY, suppressed_subjects=frozenset({"subj-000102"}))
    verdict = _assess(_allow(), policy=policy)
    assert verdict.eligible is False
    assert eligibility.REASON_SUPPRESSED in verdict.reasons


def test_the_cap_takes_the_smaller_of_the_two_authorities() -> None:
    """Neither the store's limit nor the bank's policy may be widened by the other's silence."""
    verdict = _assess(_allow(cap_limit=1))
    assert verdict.cap_limit == 1, "the store's tighter limit was ignored"
    assert verdict.cap_remaining == 1

    policy = replace(
        DEFAULT_POLICY, frequency_caps={"service:chat": FrequencyCap(limit=1, window_hours=24)}
    )
    assert _assess(_allow(cap_limit=9), policy=policy).cap_limit == 1


def test_a_subject_at_the_cap_is_refused_and_has_nothing_remaining() -> None:
    verdict = _assess(_allow(sends_in_window=3))
    assert verdict.eligible is False
    assert eligibility.REASON_CAP_EXCEEDED in verdict.reasons
    assert verdict.cap_remaining == 0


def test_an_unconfigured_cap_denies_rather_than_meaning_unlimited() -> None:
    policy = replace(DEFAULT_POLICY, frequency_caps={})
    verdict = _assess(_allow(), policy=policy)
    assert verdict.eligible is False
    assert eligibility.REASON_CAP_UNCONFIGURED in verdict.reasons


def test_quiet_hours_refuse_and_the_window_is_reported() -> None:
    verdict = _assess(_allow(as_of_iso=_QUIET), as_of_iso=_QUIET)
    assert verdict.eligible is False
    assert eligibility.REASON_QUIET_HOURS in verdict.reasons
    assert verdict.quiet_hours_window, "the refusal did not say which window applied"


def test_an_unconfigured_market_denies_rather_than_meaning_any_time_is_fine() -> None:
    """This is the direction that hurts: the opposite convention telephones people at 03:00."""
    policy = replace(DEFAULT_POLICY, quiet_hours={})
    verdict = _assess(_allow(), policy=policy)
    assert verdict.eligible is False
    assert eligibility.REASON_QUIET_UNCONFIGURED in verdict.reasons


def test_a_trigger_that_did_not_fire_is_never_eligible() -> None:
    incomplete = replace(sample_cases.ROUTINE_EVENT, attributes={})
    trigger = trigger_engine.evaluate(
        incomplete, policy=DEFAULT_POLICY, as_of=sample_cases.OPEN_INSTANT
    )
    verdict = eligibility.assess(trigger, consent=_allow(), policy=DEFAULT_POLICY, as_of_iso=_OPEN)
    assert verdict.eligible is False
    assert eligibility.REASON_TRIGGER_NOT_FIRED in verdict.reasons


def test_every_refusal_reason_is_in_the_published_vocabulary() -> None:
    """The eval oracle and the demo read these tokens, so a typo must fail here, not there."""
    verdict = _assess(None)
    assert set(verdict.reasons) <= eligibility.DENYING_REASONS


def test_a_refusal_still_cites_the_policy_it_applied() -> None:
    verdict = _assess(_allow(sends_in_window=3))
    sources = {citation.source_id for citation in verdict.citations}
    assert "policy:cap:service:chat" in sources
    assert "policy:quiet_hours:AU" in sources
