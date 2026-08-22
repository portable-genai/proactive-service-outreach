# FAQ: security

## What is the largest risk in a system like this, and what do you do about it?

Contacting the wrong person, or the right person about something untrue. Both are one bad
default away in most implementations, so both are answered structurally rather than by review.

The model cannot cause a contact. It is reachable through exactly one port
(`ports/drafting.py`), that port returns a `str`, and it is called only after the deterministic
eligibility engine has already decided the contact may happen. It never sees the subject id, the
free-text detail from the source system, or the consent decision: it gets a template id, a
locale, a channel and a handful of already-minimised facts. Anything it writes containing a
figure that is not in those facts is discarded.

## What stops an unknown consent state being treated as permission?

`domain/eligibility.py`, and it is deliberately stricter than "the store said no". Contact is
refused when there is no decision at all, when the outcome is anything other than the exact
allow token, when the answer carries a reason token this deployment does not recognise, when it
answers a different question (another tenant, subject, purpose or channel), when it is pinned to
a different instant, and when the cap or the market's quiet hours are unconfigured. There is no
branch in that module that removes a reason, and none that produces permission from an absent
value. The `consent_fail_closed` eval metric holds it at 1.0 and is proved able to go red.

## Can a caller evade quiet hours?

No surface accepts an `as_of` from its caller. The domain takes an explicit instant, which is
what makes a decision replayable, but that instant is what quiet hours are evaluated against: a
caller who could choose it could ask for a decision "as at 14:00" at 23:00 and be told the
market was open. It matters most on the agent surface, where the caller is a model. No request
schema, tool parameter or CLI flag offers one.

## Who is the actor on a decision?

A server-verified `Principal`. The client-asserted actor is discarded everywhere, and the TENANT
an event is evaluated under comes from that principal rather than from the request body, so a
caller cannot ask about another tenant's subject by naming it. Under the managed profile the
identity adapter verifies an IAP assertion against the configured audience, against IAP's own
key set and against the issuer, and refuses rather than falling back when the audience is unset.

## What is the exposure posture if the profile variable goes missing?

The process still binds the SDK-free adapters (the alternative is importing cloud SDKs that are
not installed), but nobody chose them, so every relaxation is withdrawn: the seeded dev personas
refuse to be served, no service-to-service scheme is selected, the dev CORS allowlist and the
`X-Dev-Persona` header are gone, the interactive docs are not registered, and the loopback
exposure guard refuses every route to any non-loopback peer. Setting the service-to-service
token does not change that: it authenticates a calling service and no end user.

## Where does personal data go?

Into one field, the source system's free-text `detail`, and out of it immediately. It is masked
with `pii-kit` before it reaches a citation, a model, the wire or the audit record. The audit
trail is hash-chained and externally anchored. A drafted body carrying personal data is rejected
outright, so the model cannot put an identifier back in.
