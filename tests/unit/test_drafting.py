"""The drafting validator: the model may phrase, and may not inform.

The interesting tests here are the rejections. An accepted draft proves the validator can say
yes; a rejected one proves it can say no to the specific thing that would have reached a
customer. The invented-figure case is the one this module exists for: a notification that tells
somebody the wrong amount is worse than the flat template sentence it replaced.
"""

from __future__ import annotations

import json
from dataclasses import replace

from proactive_outreach.domain import drafting
from proactive_outreach.domain.models import DraftRequest
from proactive_outreach.domain.policy import DEFAULT_POLICY

_FACTS = {"card_suffix": "4242", "retry_on": "2026-08-11"}

_REQUEST = DraftRequest(
    template_id="failed_payment_retry",
    locale="en-SG",
    channel="chat",
    facts=dict(_FACTS),
    max_chars=DEFAULT_POLICY.max_body_chars,
    required_facts=tuple(sorted(_FACTS)),
)

_GOOD_BODY = (
    "A payment on the card ending 4242 did not go through. "
    "We will try again on 2026-08-11. You can update the card in the app."
)


def _judge(body: str) -> drafting.DraftVerdict:
    return drafting.validate_draft(json.dumps({"body": body}), _REQUEST, policy=DEFAULT_POLICY)


def test_a_grounded_complete_draft_is_accepted_and_marked_as_the_models_work() -> None:
    verdict = _judge(_GOOD_BODY)
    assert verdict.accepted is True
    assert verdict.message is not None
    assert verdict.message.source == "model"
    assert verdict.reasons == (drafting.REASON_ACCEPTED,)


def test_an_invented_figure_is_rejected_and_the_reason_names_the_figure() -> None:
    verdict = _judge("Your card ending 4242 was declined for 250 dollars. Retry on 2026-08-11.")
    assert verdict.accepted is False
    assert any(reason.endswith(":250") for reason in verdict.reasons)


def test_a_draft_that_omits_a_required_fact_is_rejected() -> None:
    verdict = _judge("A payment did not go through. Please check the app.")
    assert verdict.accepted is False
    assert any(reason.startswith(drafting.REASON_MISSING_FACT) for reason in verdict.reasons)


def test_a_banned_promise_is_rejected() -> None:
    verdict = _judge(_GOOD_BODY + " Compensation will be applied.")
    assert verdict.accepted is False
    assert any(reason.startswith(drafting.REASON_BANNED) for reason in verdict.reasons)


def test_a_credential_phishing_sentence_is_rejected() -> None:
    """A bank that sends one of these has trained its customers to fall for the next one."""
    verdict = _judge(_GOOD_BODY + " Please verify your card number to continue.")
    assert verdict.accepted is False


def test_personal_data_in_a_body_is_rejected() -> None:
    """The facts are already minimised, so an identifier here came from the model."""
    verdict = _judge(_GOOD_BODY + " Quote NRIC S1234567D at the branch.")
    assert verdict.accepted is False
    assert drafting.REASON_PERSONAL_DATA in verdict.reasons


def test_an_over_long_body_is_rejected_rather_than_truncated() -> None:
    """A truncated legal sentence is a different sentence, so it is refused, not trimmed."""
    verdict = _judge(_GOOD_BODY + " " + ("padding " * 60))
    assert verdict.accepted is False
    assert drafting.REASON_TOO_LONG in verdict.reasons


def test_output_that_is_not_json_is_rejected() -> None:
    verdict = drafting.validate_draft("just some prose", _REQUEST, policy=DEFAULT_POLICY)
    assert verdict.reasons == (drafting.REASON_NOT_JSON,)


def test_json_that_is_not_an_object_is_rejected() -> None:
    verdict = drafting.validate_draft('["a body"]', _REQUEST, policy=DEFAULT_POLICY)
    assert verdict.reasons == (drafting.REASON_NOT_OBJECT,)


def test_an_envelope_with_no_body_is_rejected() -> None:
    for payload in ('{"note": "fine"}', '{"body": ""}', '{"body": 42}'):
        verdict = drafting.validate_draft(payload, _REQUEST, policy=DEFAULT_POLICY)
        assert verdict.reasons == (drafting.REASON_NO_BODY,), payload


def test_a_rejected_draft_is_never_repaired_into_a_message() -> None:
    """There is no partial acceptance: the message is None or it is whole."""
    assert _judge("Declined for 999 dollars.").message is None


# --------------------------------------------------------------------------- #
# The deterministic body the service falls back to
# --------------------------------------------------------------------------- #
def test_the_template_render_is_grounded_by_construction() -> None:
    message = drafting.render_template(_REQUEST, policy=DEFAULT_POLICY)
    assert message is not None
    assert message.source == "template"
    for value in _FACTS.values():
        assert value in message.body
    # What the template produces must itself survive the validator, or the fallback would be a
    # body the service is not allowed to send.
    assert _judge(message.body).accepted is True


def test_a_template_with_a_missing_fact_renders_nothing_rather_than_a_gap() -> None:
    """``{card_suffix}`` left in a sent message is worse than no message."""
    thin = replace(_REQUEST, facts={"retry_on": "2026-08-11"})
    assert drafting.render_template(thin, policy=DEFAULT_POLICY) is None


def test_an_unconfigured_template_renders_nothing_rather_than_improvising() -> None:
    unknown = replace(_REQUEST, template_id="not_configured")
    assert drafting.render_template(unknown, policy=DEFAULT_POLICY) is None
