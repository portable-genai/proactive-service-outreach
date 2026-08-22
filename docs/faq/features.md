# FAQ: what it does

## In one paragraph?

It watches for five operational events (a failed payment, a delivery exception, an expiring
card, a fraud hold, a service outage), decides deterministically whether the customer may be
contacted about it, and only then writes them a short, grounded message on chat or by voice.
The interesting half is the refusals.

## What are the five triggers, and can we add a sixth?

They are configuration, not code: a block per event type in `config/settings.yaml` naming its
template, channel, severity, freshness window, required attributes and whether it is
consequential. Adding a sixth is a policy change plus a template, and the trigger engine already
refuses an event type nobody configured.

## Why would an event NOT produce a message?

Five reasons before consent is even asked: no configured rule, an unparseable or timezone-less
timestamp, a timestamp in the future, an event older than its freshness window, and an event
missing an attribute the message would have to quote. That last one matters most: a delivery
notification with no tracking reference would need the drafter to invent one.

Then eligibility: consent, suppression, the frequency cap and quiet hours, composed worst-wins.

## How does the frequency cap work when the consent store has one too?

The engine takes the SMALLER of the two limits, so neither authority can be widened by the
other's silence. A delivered message is then recorded back to the store, because a cap counts
recorded sends and nothing else: a system that decides but never records passes every cap
forever.

## What does the model do?

It phrases. It receives the template id, the locale, the channel and the event's facts, and
returns a candidate body that is then checked against those same facts. It cannot introduce a
figure, cannot omit a required fact, cannot use a banned phrase, cannot include personal data
and cannot exceed the configured length. It has no say in whether the message is sent.

## What does the operator see?

The whole chain, not just the outcome: which trigger fired, the consent decision id, the cap
counters, the quiet-hours window that applied, every reason that refused, and the citations.
`make demo` walks nine steps of it against the real services, offline.

## What is NOT in scope?

Marketing. Campaign selection. Any decision about a product or a price. Retrieval from a
knowledge base: a service notification quotes the operational event that caused it, and a corpus
would add a source of claims this service is not allowed to make.
