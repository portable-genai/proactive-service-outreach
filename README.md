# Proactive Service Outreach (E5)

Consent-gated, frequency-capped service outreach from deterministic operational triggers.

A bank knows a customer's payment failed, their delivery was missed, their card is about to
expire, a fraud hold has been placed or a service is degraded. Telling them, quickly and in the
right words, is good service. Telling the wrong person, or the right person too often, or at
03:00, or something that is not true, is a conduct failure, a privacy failure or both.

So the product here is not the message. It is the REFUSAL: a deterministic, replayable, fully
cited answer to "may this person be contacted, about this, on this channel, right now". The
model is reachable through exactly one port, is handed a closed set of facts and nothing else,
is called only after eligibility has already passed, and has whatever it writes discarded if it
contains a figure the event did not supply.

    redact -> trigger -> consent -> eligibility -> [draft] -> [validate] -> [deliver] -> audit

Nothing in brackets happens unless the step before it said yes.

A hexagonal ports-and-adapters build on the catalog commons. Every consequential value is pure,
deterministic stdlib; PII is redacted before anything is audited; every result carries a
citation; and a consequential result is HELD and ROUTED to a human reviewer (rule R8) rather
than delivered or left in a flag nobody reads.

## Commands

```bash
python3.12 -m venv .venv && source .venv/bin/activate
make install          # locked install from requirements-dev.lock, then the project --no-deps
make gate             # the full offline gate: lint + type + test + eval
make audit            # pip-audit over both lockfiles (needs network; a HARD gate in CI)
make lock             # re-resolve uv.lock and re-export both lockfiles after a dependency change
make test-integration # tests/integration only; needs a live project (the gate deselects it)
make run-api          # uvicorn (loopback for the no-auth local profile)
proactive_outreach sweep --tenant demo-bank        # every detected event, decided
proactive_outreach evaluate evt-1 failed_payment subj-000101 \
    2026-08-08T05:00:00+00:00 --attribute card_suffix=4242 --attribute retry_on=2026-08-11
```

The offline gate is SDK-free and is what CI runs (via the shared reusable hard-gate workflow):

```bash
ruff check src tests && ruff format --check src tests && mypy src && \
  pytest -m 'not integration' && python eval/run_eval.py
```

The demo surface sits OUTSIDE that gate, because the gate proves the service and the demo proves
the story it is presented with. It is enforced inside the offline gate by
`tests/unit/test_demo_surface.py`, which the hosted GitHub Actions check runs, so it cannot rot
quietly:

```bash
make demo             # the presenter-paced walkthrough (see DEMO.md)
make demo-selftest    # the same walkthrough, headless and unattended, asserting every step
make demo-static      # static audit-first HTML for screenshots
make portability      # the executable portability claim, pass or fail per named check
make docs-check       # relative links resolve, fences close, no em-dash in shipped prose
make ui-install ui-check   # the micro-frontend: tsc, node tests, production build, npm audit
```

## Profiles

One env var, `OUTREACH_PROFILE`, selects the adapter family:

- `local` (default) : SDK-free offline stack (seeded dev personas, hash-chained SQLite WORM audit
  from the commons). No cloud SDK. The default for dev/test/CI.
- `gcp` : managed cloud (Cloud Logging WORM, IAP identity). SDK imports are lazy.
- `onprem` : fail-fast `NotImplementedError` placeholders (the reversibility proof, P-12).

Unset means `local` adapters bind but nobody chose them. A value that is set but unknown, `Local`
and `GCP` included, raises at import: a typo must not silently pick a family. And because the
local profile's seeded personas authenticate nobody, the loopback exposure guard is registered on
the app object itself, so serving it off loopback returns 503 unless
`OUTREACH_ALLOW_INSECURE_DEMO=1` says otherwise. The guard reads the identity
BINDING to decide that, never a service credential: setting
`OUTREACH_S2S_TOKEN` closes the S2S routes and does not open anything else.
See `docs/runbook.md`.

## What comes from the commons

| Package | Used for |
|---|---|
| `hex-service-kit` | `Principal` / `IdentityPort` / seeded personas, fail-closed bind + CORS, `make_require_service_caller` / the app-object exposure guard / security headers (the end-user dependency is this repo's own, so a deployment that can authenticate nobody answers with a status and a reason rather than a blanket 401), the hash-chained WORM audit log, `StrEnum` taxonomies |
| `agent-eval-kit` | the `--mode smoke\|gate` scaffold, the Hrz4 gate client, the not-falsely-green harness |
| `pii-kit` | the jurisdiction PII pattern pack every redaction uses (SG, AU, JP) |
| `review-kit` | the rule R8 producer path: the review payload, the submission client and the outbox |
| `consent-preference-kit` | the CLIENT half of the consent and preference store. The store itself is Mkt6's asset; this repo asks it and holds no second copy of anybody's consent |
| `speech-lexicon-kit` | the text-to-speech port for the voice channel, re-exported rather than redeclared |

## Surfaces

The same capability is reachable five ways, and they behave the same because they share the
domain service rather than reimplementing it: the FastAPI app (`api/`), the argparse CLI
(`cli/`), the agent tools (`agent/`, advertised on the A2A card at
`/.well-known/agent-card.json`), the embeddable micro-frontend (`ui/`) and the eval harness.
Each of them routes a held result to human review in the same call that produced it, so rule R8
does not hold on four surfaces out of five.

**No surface lets its caller choose the instant a decision is made against.** The domain always
takes an explicit `as_of`, which is what makes a decision replayable months later, but quiet
hours are evaluated against that instant: a caller who could pick it could ask for a decision
"as at 14:00" at 23:00 and be told the market was open. It matters most on the agent surface,
where the caller is a model. Replay stays available to the eval, the tests and the demo, which
contact nobody.

`ui/` is a Next.js micro-frontend that runs standalone or embeds in a client application. Its
security value is that the browser never asserts who the user is: every client-supplied actor,
tenant, role and authorization header is discarded, identity is resolved server-side, the
service credential never leaves the server, and framing and CORS are per-tenant allowlists that
refuse a wildcard. **If this repo has no user-facing surface, run `make drop-ui`** rather than
leaving it half-wired; `tests/unit/test_ui_surface.py` holds the repo consistent in both
directions. See `ui/README.md`.

The tool results are masked for personal data before they return, which the API response is not:
a tool result becomes a model's context, and P-04 is about what reaches the model.

## Configuration

`config/settings.yaml` holds the per-port adapter map plus non-secret defaults, and it is the only
place a binding lives. `.env.example` documents every non-secret variable;
`.env.secrets.example` documents the secret NAMES with placeholder values. Every security-relevant
read resolves three states: unset, set-and-empty and set-and-valid are different, and a value an
operator deliberately emptied never inherits the more permissive unset default.
`tests/unit/test_three_state_env_reads.py` fails the build on any two-state read that ships, so
the rule is enforced rather than remembered.

**Name the profile.** `OUTREACH_PROFILE` has no default. Leaving it unset is
its own state: the offline adapters still bind, but the seeded dev personas are refused, no
service-to-service scheme is selected, the dev CORS allowlist and the `X-Dev-Persona` header are
withdrawn, and the exposure guard refuses every route to any non-loopback peer. A deployment that
loses the variable fails visibly instead of serving a stranger.

Deepest authority on intent, in order: `SPEC.md` -> `ARCHITECTURE.md` -> `COMPLIANCE.md` -> this
file. `docs/practices-audit.md` records the per-check verdict. Region pinned to
`asia-southeast1`.

## License

Apache-2.0. Synthetic, obviously fictional data only.
