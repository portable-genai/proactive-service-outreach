# FAQ: compliance and conduct

## How do you prove consent for a message sent nine months ago?

Every send quotes a consent decision id, and that id is a content hash of the question AND the
answer. It rides the delivery envelope, lands on the audit record, and can be replayed against
the consent and preference store to re-derive the same decision at the same instant. So the
evidence is not "our system says it checked"; it is a reproducible answer with the store's own
citations attached.

## Where does consent actually live?

Inside Mkt6, the marketing compliance and brand governance system, which already models consent
as a rule and owns the rule engine a denial cites. This service holds NO copy of anybody's
consent on any profile. It asks, through `consent-preference-kit`, and on the managed profile an
unset store URL refuses rather than falling back to anything. A second store would be a second
answer to a legal question about a person.

## This sends messages. Is it marketing?

No, and the distinction is enforced rather than asserted. It asks the store under the `service`
purpose, so a subject who opted out of marketing is still told their card was declined, and a
subject who opted out of service contact is not contacted at all. Using it for marketing would
mean changing the configured purpose, which is a reviewable diff rather than a runtime choice.

## What is recorded when somebody is NOT contacted?

Everything. A refusal is audited as fully as a send, with the reasons that produced it and the
policy rows it applied. "Why was this customer not told about the outage" is a question asked
after an incident, and a system that only logs what it did cannot answer it.

## Who owns the numbers?

The bank. Trigger rules, frequency caps, quiet hours (with an explicit UTC offset, because a
decision that depended on the host's timezone database would not replay), message templates, the
suppression list, the banned phrases and the body length limit are all in the `policy:` block of
`config/settings.yaml`. The shipped values are a synthetic reference set and none of them is
advice. Second-line review of that block is expected; `COMPLIANCE.md` says so explicitly.

## What happens to a message a model wrote badly?

It is discarded. Not corrected, not truncated, not sent with a warning: there is no repair path
in the code. The deterministic template body is prepared for a human, `requires_human_review` is
set, and nothing is delivered. A half-true notification about somebody's money is worse than the
flat sentence it replaced.

## Which decisions never happen automatically?

Whatever the policy marks `consequential`. In the shipped set that is a fraud hold and an
outage: both are drafted, HELD and routed to the Hrz7 human-review console with the proposed
words attached, because a reviewer who cannot see the sentence cannot meaningfully approve it.
In this vertical "held" means the message did not go out, and the API, CLI, agent and contract
suites all assert the delivery did not happen rather than only that the flag was set.
