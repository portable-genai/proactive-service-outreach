# On-prem migration (the reversibility proof, P-12)

The `onprem` profile ships fail-fast `NotImplementedError` placeholders for every port, so the
exit path is explicit rather than implied.

The identity placeholder is the one with a serving consequence, so it refuses with a STATUS and a
REASON rather than a bare crash: `OnPremIdentityUnimplementedError` is both a
`NotImplementedError` (the exit family's uniform refusal, which the contract suite and
`scripts/portability_demo.py` assert for every port) and an `EndUserAuthUnavailableError`, so
`POST /v1/outreach/evaluate` answers 501 with the message below instead of a 500 with no body. Until it is
replaced, no end user can be authenticated at all, and the loopback exposure guard treats the
deployment accordingly: see the exposure section of [runbook.md](runbook.md).

## Steps
1. Set `OUTREACH_PROFILE=onprem`. A primary path that needs an unbound port
   fails fast with a message pointing here.
2. Implement each port against the client's own stack:
   - `AuditSinkPort` -> the client's append-only WORM store (the commons hash-chained log is a
     drop-in reference; the audit trail exports as JSON Lines and reloads with the chain intact).
   - `IdentityPort` -> the client's OIDC/SAML IdP (verify the assertion server-side; keep
     discarding any client-asserted actor). Set `end_user_auth = VERIFIED` on the new class
     (`ports/identity.py`). That declaration is what tells the exposure guard the end-user routes
     are authenticated, and it is what lifts the loopback bound; an adapter that omits it is read
     as client-asserted, which is the fail-closed default and not a bug in the guard.
   - `ReviewRouterPort` -> the client's own maker-checker queue. Rule R8 does not relax on exit:
     a consequential result must still reach a human, so this placeholder RAISES rather than
     returning quietly. An adapter that dropped the escalation would leave the service
     auto-executing with the appearance of review.
   - `ConsentPort` -> the client's own preference centre. Nothing here may synthesise a decision:
     an adapter that returned anything without asking a store would be inventing a legal position
     about a person. The wire types stay `consent-preference-kit`'s, so the domain does not
     change; only where the answer comes from does.
   - `EventDetectionPort` -> the client's own operational event feed. The placeholder refuses
     rather than returning an empty tuple, because a sweep reporting no events is
     indistinguishable from a quiet morning and nobody investigates a quiet morning.
   - `DraftingPort` -> the client's own model endpoint. This is the one port whose absence is
     survivable: a refusal is treated as a discarded draft, so the deterministic template body
     goes to a human and a notification is delayed rather than lost.
   - `MessageDeliveryPort` and `TextToSpeechPort` -> the client's own messaging and speech
     stacks. The delivery placeholder is the most dangerous one to get wrong: an adapter that
     returned a receipt for a message nobody sent would count the contact against the customer's
     frequency cap and tell the consent store it happened.
3. Bind the new adapters under `onprem` in `config/settings.yaml` (and in
   `config.DEFAULT_BINDINGS`, which the settings test holds equal to it) and run the gate.

No domain code changes: that is the point of the hexagon.
