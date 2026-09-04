# SPEC: Proactive Service Outreach (E5)

Locked decisions, pinned stack, contracts. This document is the deepest authority on intent.

## Pinned stack
- Python `>=3.12`; ruff pinned exactly (`0.15.18`); mypy strict; deploy region `asia-southeast1`.
- Commons declared by tag in `pyproject.toml` (`pii-kit@v0.0.1`, `hex-service-kit@v0.0.1`, `agent-eval-kit@v0.0.1`, `review-kit@v0.0.1`, `consent-preference-kit@v0.0.1`, `speech-lexicon-kit@v0.0.1`) and pinned in the lockfiles to the 40-character COMMIT each tag resolved to. A tag can be moved; a commit cannot, so a lockfile that pinned the tag would let what installs change with no diff. `tests/unit/test_repo_artifacts.py` asserts the three-way agreement offline.
- The `hex-service-kit` pin is a security floor, not a preference: the kit checks the
  service-identity policy before the token, gates the zero-secret local opening on an exact
  profile match, and binds the loopback exposure guard over both HTTP and WebSocket scopes; it
  resolves every environment read in three states, so a variable set to empty fails closed
  instead of inheriting the unset default. Never move this pin backwards.
- Installs are LOCKED: `requirements-dev.lock` and `requirements-gcp.lock` are committed and are
  what `make install`, CI and the container image install. Nothing ships from an uncommitted
  resolve.

## What this system is for

A bank knows a customer's payment failed, their delivery was missed, their card is about to
expire, a fraud hold has been placed or a service is degraded. Telling them, quickly and in the
right words, is good service. Telling the wrong person, or the right person too often, or at
03:00, or something that is not true, is a conduct failure, a privacy failure or both.

So the product is not the message. The product is the REFUSAL: a deterministic, replayable,
fully-cited answer to "may this person be contacted, about this, on this channel, right now",
with a model allowed nowhere near it.

## The pipeline, and the order that is the control

    redact -> trigger -> consent -> eligibility -> [draft] -> [validate] -> [deliver] -> audit

Nothing in brackets happens unless the step before it said yes. The order lives in exactly one
place (`domain/outreach_service.py`) and every surface goes through it.

## Contracts
- **Identity**: a request's actor is a server-verified `Principal`; the client-supplied actor is
  discarded. The TENANT an event is evaluated under comes from that principal, never from the
  request body, so a caller cannot ask about another tenant's subject by typing its name. Local
  profile resolves a seeded dev persona from `X-Dev-Persona`.
- **The instant is the service's, never the caller's**. The domain always takes an explicit
  `as_of`, which is what makes a decision replayable; no SURFACE accepts one. Quiet hours are
  evaluated against that instant, so a caller who could choose it could ask for a decision "as
  at 14:00" at 23:00 and be told the market was open. It matters most on the agent surface,
  where the caller is a model. Replay stays available to the eval, the tests and the demo,
  which contact nobody.
- **Triggers are configuration**: five operational event types (failed payment, delivery
  exception, expiring card, fraud hold, outage), each a rule in the `policy:` block naming its
  template, channel, severity, freshness window and required attributes. An event with no rule,
  an unparseable or naive timestamp, a future timestamp, an event past its window, or an event
  missing an attribute the message would have to quote does NOT fire. Only the required
  attributes survive into the fact set, so an extra attribute cannot become a figure in a
  message.
- **Eligibility fails closed on any unknown consent state**. Consent, suppression, frequency cap
  and quiet hours compose worst-wins at one explicit instant. Contact is refused when there is
  no decision at all, when the outcome is anything other than the exact allow token, when the
  answer carries a reason token this deployment does not recognise, when it answers a different
  question (another tenant, subject, purpose or channel), when it is pinned to a different
  instant, when the cap for that purpose and channel is unconfigured, and when the market's
  quiet hours are unconfigured. An unconfigured requirement is a gap, never a pass.
- **The cap takes the SMALLER of two authorities**: this deployment's configured limit and any
  limit the consent store reports. Neither can be widened by the other's silence. A delivered
  message is recorded back to the store, because a cap counts recorded sends and nothing else.
- **The consent store is `marketing-compliance-gate`'s, not this repo's.** This system asks it through
  `consent-preference-kit` and holds no second copy of anybody's consent. On the managed profile
  an unset store URL REFUSES rather than falling back to anything.
- **The model may phrase and may not inform.** The drafting port is the only seam a model is
  reachable through, it returns a `str`, and it is called only after eligibility passes. A draft
  is discarded (never repaired, never truncated, never sent with a warning) for a digit run
  absent from the facts, a missing required fact, a banned phrase, personal data, over-length,
  or not being a JSON object carrying a body. A discarded draft means the deterministic body
  goes to a HUMAN and nothing is delivered.
- **Every send carries what authorised it**: a `DeliveryEnvelope` holding the consent decision
  id and the cap counters travels with the message, and a delivery adapter REFUSES an envelope
  without a decision id. Provenance arrives with the contact rather than as a second row to be
  joined on a timestamp.
- **Redaction before anything**: the source system's free-text detail is masked (via `pii-kit`)
  before it reaches a model, a citation, the wire or the audit record. No raw identifier reaches
  the WORM store.
- **Determinism**: every consequential value (whether a trigger fires, whether contact is
  permitted, the cap arithmetic, the severity band, whether a human must approve) is pure stdlib
  and replayable. An LLM phrases a message that has already been decided; it produces no number
  and no verdict.
- **Maker-checker (P-06) and routing (R8)**: an event type marked `consequential` in policy
  (`fraud_hold` and `outage` in the shipped set) sets `requires_human_review=True`, is NOT
  delivered, and is routed through `ReviewRouterPort` to the `human-review-console` in the same request,
  with the proposed words attached so the reviewer can approve the sentence. A discarded draft
  does the same. The flag alone is not the escalation. The response carries `review_ref`, so a
  caller can tell a routed escalation from one that stopped here. The managed adapter refuses to
  run with no console configured rather than swallowing the escalation.
- **Profile**: resolved ONCE, at import, into a `ProfileChoice` and never a bare string. Three
  states of `OUTREACH_PROFILE`: UNSET is NO CHOICE (the SDK-free adapters
  still bind, but the seeded personas are refused, no service-to-service scheme is selected, every
  relaxation sees `unconfigured` and the exposure guard refuses every route to a non-loopback
  peer); SET AND EMPTY raises, so it can never inherit the unset behaviour; SET AND UNKNOWN,
  including a mis-capitalised value, raises. Only a deliberately named profile is honoured, and
  both raises happen before the process can serve anything.
- **Two derived postures, opposite directions**: `exposure_profile` drives every RELAXATION (CORS
  allowlist, the `X-Dev-Persona` allowed header, the HSTS baseline, the S2S scheme) and reads
  `unconfigured` when nobody chose; `bind_profile` drives the RESTRICTION (the loopback bound) and
  reads `local` when nobody chose. One string cannot do both without weakening one of them.
  Only `config.py` reads the variable.
- **End-user authentication is a property of the identity BINDING**, declared by the adapter
  (`VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`) and read by the loopback exposure guard. The
  service-to-service secret authenticates a calling SERVICE and no end user, so it takes no part
  in that decision: setting it closes the S2S routes and relaxes nothing.
- **Audit integrity**: the trail is hash-chained AND externally anchored. `audit_anchor_path`
  points at a file on a different volume that every append writes the chain head to; without it
  a truncated tail is undetectable, because the shorter chain still verifies. Once store and
  anchor disagree the service refuses to append rather than re-anchoring, so an ordinary write
  cannot launder a divergence. Re-anchoring is a deliberate operator action.
- **Agent surface**: optional but scaffolded. The A2A card at `/.well-known/agent-card.json` is
  built from the same tool table the runtime binds, so advertised skills and implemented tools
  are the same set. Tool results are masked for personal data before they return, because a tool
  result becomes model context (P-04); an API response to the caller who supplied the text is
  not. Nothing in `agent/` needs a runtime to import; `build_function_tools()` is the only seam.
- **Ports**: a port is registered in five places (`PORT_PROTOCOLS`, `DEFAULT_BINDINGS`, the
  `Container` accessor, `config/settings.yaml`, and the canonical-call table) and the contract
  suite asserts set equality across all five, in both directions.
- **Speech and consent types are not redeclared here.** The text-to-speech port comes from
  `speech-lexicon-kit` and the consent wire types from `consent-preference-kit`. A repo that
  writes its own would eventually disagree with its siblings about what a customer was told and
  what they had agreed to.
- **Demo**: the demo is code and it is asserted. `scripts/walkthrough.py` narrates nine steps
  and, at each one, checks that the service actually reached the state the narration claimed;
  `--auto --headless` runs the same steps unattended in CI. A step exists in exactly two places
  (`demo.STEPS` and `walkthrough.CHECKS`) and the two are held equal, so a narrated claim nobody
  verifies cannot exist. The demo needs no browser engine, no network and no cloud.
- **UI identity**: the browser never asserts who it is. Every client-supplied actor, tenant,
  role, ACL and authorization header is discarded before a request is forwarded; identity is
  resolved server-side and the resolved headers are attached afterwards. The service credential
  is read from the server environment only. Framing and CORS are allowlists that refuse a
  wildcard however it is written, and an empty allowlist denies rather than opening up.
- **Eval**: `--mode smoke` is the offline pre-merge check; `--mode gate` is the `model-quality-gate` promotion
  authority. The gate fails closed.
- **Tests**: split into `unit`, `contract` and `integration`. The offline gate runs the first
  two; every integration module is marked, and that marking is itself enforced.

## Metrics and thresholds (smoke)

Every metric scores against an INDEPENDENT oracle: the labels a human wrote in
`eval/datasets/`, never the pipeline's own verdict. Each is proved able to go RED on a planted
mutant in `tests/unit/test_not_falsely_green.py`, because a metric that cannot fail is not a
metric.

- `eligibility_accuracy >= 0.95` (the engine's verdict and its reason against the dataset's)
- `consent_fail_closed >= 1.0` (every denied or not-fully-understood consent state refuses
  contact, and nothing is delivered). Nothing less than 1.0 is meaningful here: a service that
  contacts one person in a hundred who never agreed is not 99 percent compliant.
- `frequency_cap_exactness >= 1.0` (the remaining-contacts arithmetic is exact, not close)
- `drafting_groundedness >= 1.0` (the validator accepts exactly the drafts that are safe to
  send, over an independently labelled candidate set including an invented amount, a missing
  fact, a banned promise, a phishing sentence, a leaked identifier and malformed output)
- `review_safety >= 1.0` (a consequential result is held and undelivered; a routine one does not
  manufacture a review)
- `pii_safety >= 0.99` (pack scan + pack-independent planted-literal check)
