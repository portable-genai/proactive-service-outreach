# Model card: Proactive Service Outreach (E5)

This is a STARTER model card. It records the model boundary as built and the controls that must be
completed before a managed deployment. The deterministic engine is the system of record; the model
is a bounded, replaceable component that phrases a notification which has already been decided.

## What the model does, and does not do

- **Does**: rewrite one already-decided service notification in the requested locale, from a
  closed fact set, through the single seam `ports/drafting.py`. That port returns a `str`, not a
  domain object, deliberately: if it returned an `OutreachMessage` the model would be
  constructing a consequential value and the boundary would be a convention rather than a type.
  A second model, the managed text-to-speech voice behind `ports/speech.py`, reads an
  already-approved body aloud for the voice channel and returns an `AudioRef`, never bytes.
- **Does NOT**: decide anything. Whether a trigger fires and what facts it may carry
  (`domain/trigger_engine.py`), whether the subject may be contacted at all, the frequency-cap
  arithmetic, the market quiet-hours check and the consent verdict (`domain/eligibility.py`),
  the severity band and whether a human must approve (`domain/policy.py`,
  `domain/outreach_service.py`) are pure stdlib, take an explicit `as_of` and no clock, and
  replay exactly. The model is called only inside the `eligible` branch, so a refused contact
  costs no tokens and leaks no facts to a model at all.

## Boundary and validation

- **Redaction happens before anything is recorded.** `domain/outreach_service.py` redacts the
  source-system detail with `pii_kit.redact` against this deployment's jurisdiction pattern
  pack before the audit write and before any outbound payload, so a raw identifier never reaches
  a WORM record or the Hrz7 review console.
- **The prompt is a closed fact set.** `adapters/gcp/drafting.py` sends a template id, a locale,
  a channel and the facts the trigger engine assembled. Not the event, not the free-text detail,
  not the subject id, not the consent decision. The instruction itself is a module constant, so
  what the model is told is reviewable in a diff and no per-request value can enter it.
- **Every draft is untrusted, and a bad one is discarded rather than repaired.**
  `domain/drafting.validate_draft` rejects output that is not a JSON object, output with no
  usable `body`, a body over the policy length limit, any digit run the facts did not supply, a
  missing required fact, a banned phrase, and any personal data the pattern pack finds. There is
  no repair path and no retry-with-a-nicer-prompt loop: both would be the adapter deciding what
  the customer is told. On rejection the deterministic template body goes to a human instead.
  `tests/unit/test_drafting.py` has a named test per rejection shape, including
  `test_a_rejected_draft_is_never_repaired_into_a_message`.
- **A held result is a result that was NOT delivered.** For a `consequential` trigger (a fraud
  hold, an outage notice) the service sets `requires_human_review` and routes to Hrz7 in the same
  call, and the API, the CLI, the agent tools and the contract suite all assert the delivery did
  not happen rather than merely that a flag was set (rule R8).
- **No surface lets its caller choose the instant.** The domain takes an explicit `as_of` so a
  decision replays months later, but quiet hours are evaluated against it, so a caller that could
  pick it could evade them. That matters most on the agent surface, where the caller is a model.

## Adapters and profiles

| Profile | Drafting adapter | Speech adapter | Behaviour |
|---|---|---|---|
| `local` | `adapters/local/drafting.py` | `adapters/local/speech.py` | No model at all. The drafter renders the configured template into the same JSON envelope a model is asked for, so the offline gate exercises the real validator and the real discard path. The synthesiser produces no audio: it returns a content-addressed `file:` URI derived from the request, so no customer voice exists anywhere offline. SDK-free. |
| `gcp` | `adapters/gcp/drafting.py` | `adapters/gcp/speech.py` | The managed model named by `OUTREACH_DRAFTING_MODEL`, and the managed voice named by `OUTREACH_SPEECH_VOICE` writing to the in-region bucket `OUTREACH_SPEECH_OUTPUT_URI`. Both SDK imports are lazy. An empty `drafting_model` raises `DraftingUnavailableError`, which the service treats exactly like a rejected draft. |
| `onprem` | `adapters/onprem/drafting.py` | `adapters/onprem/speech.py` | Fail-fast placeholders for a client-hosted model and speech stack. A refusal costs a phrasing, never a notification: the deterministic body is still available, and an unavailable voice channel is reported as undelivered so nothing is counted against a customer's cap for a call that never happened. |

Because the local drafter is a template renderer rather than a fake model, the offline
groundedness metric is scored against an independently labelled set of candidate drafts in
`eval/datasets/`, not against the adapter's own output. A metric that scored a generator against
facts the generator chose would be a tautology.

## Remaining controls (TODO, repo owner)

- **Model id, version and routing.** `OUTREACH_DRAFTING_MODEL` is empty in the shipped settings.
  Pin the exact model and version for the `gcp` profile, record it here, and record the locale
  set you have actually reviewed output for.
- **Budget, rate control and a kill switch.** There is no per-tenant token budget, no request
  rate limit and no switch that forces template-only operation with the model disabled. The
  switch is cheap here because the deterministic template body always exists: it is the same
  path a rejected draft already takes.
- **Evaluation of the live model.** The offline eval scores the validator and the deterministic
  pipeline. Add a managed-profile run through the Hrz4 promotion gate that scores real drafted
  bodies for groundedness, locale fidelity and banned-phrase rate against the same golden cases.
- **Prompt-injection screening.** Event attributes reach the prompt as facts. Screen them through
  the Hrz1 guardrail gateway before generation, failing closed to the template body when the
  screen is unavailable. That port is not bound in this repo today.
- **Voice consent and retention.** Synthesised audio persists in a bucket. Record who may listen
  to it, for how long it is kept, and how a subject-access request reaches it.

Until these are complete the system is safe to run offline (deterministic engine plus template
renderer, no model, no audio) and the managed model path is not production-cleared.
