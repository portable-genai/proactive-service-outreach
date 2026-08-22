# Runbook: Proactive Service Outreach (E5)

## Deploy (gcp)
1. `OUTREACH_PROFILE=gcp`, install `.[gcp]`, region `asia-southeast1`.
2. Apply `infra/terraform/`. See "The deploy stack" below for what it provisions and in what
   order; `make tf-check` validates the whole configuration offline first, with no project and
   no credentials.
3. Ingress is fronted by the external load balancer and IAP; the app authenticates the S2S
   caller fail-closed (`OUTREACH_S2S_TOKEN` local, Google OIDC plus allowlist secure).
4. **Set `OUTREACH_IAP_AUDIENCE`.** Without it the service starts, stays
   health-checkable and refuses every end-user request with 503 naming this variable. See below.

## The deploy stack

`infra/terraform/` is the enforcement half of this repo's compliance posture: a control that
lives only in a document is not a control. It provisions, all pinned to `asia-southeast1`:

| File | What it enforces |
|---|---|
| `variables.tf` | the residency allowlist; an out-of-allowlist region fails at plan, and the app validates the same list at settings load |
| `org_policy.tf` | `gcp.resourceLocations` pinned to the region, no service-account key creation, uniform bucket-level access |
| `kms.tf` | one regional CMEK key with a per-service-agent binding each for Vertex AI, Cloud Storage, Cloud Logging and Cloud Run (CMEK does not cascade) |
| `logging_worm.tf` | the locked WORM audit bucket and the sink that routes this service's audit log into it |
| `monitoring.tf` | log-based metrics and alerts on critical escalations, consent unavailability, policy-gap refusals, discarded drafts, service-account key creation, VPC-SC denials, CMEK changes and edge denials |
| `vpc_sc.tf` | the service perimeter, in DRY RUN until `vpc_sc_enforce = true` |
| `storage.tf` | the regional, CMEK-encrypted bucket synthesised voice notifications are written to |
| `warehouse.tf` | nothing, deliberately: the event view is the client's, so this file only grants dataset-scoped read on it |
| `iam.tf` | one least-privilege serving identity, with no exportable key |
| `production_edge.tf` | the Cloud Run service (load-balancer ingress only), Cloud Armor per-source throttle, the HTTPS load balancer and IAP |

What this stack deliberately does NOT create:

- **The event view.** `adapters/gcp/events.py` reads a view the client owns, and the view is
  the contract. Set `event_view` to its fully-qualified name. When it lives in a dataset in
  this project, set `event_view_dataset` too and the serving identity is granted
  `roles/bigquery.dataViewer` on that one dataset. When it lives in another project (the usual
  case), leave `event_view_dataset` empty and grant the `app_service_account` output read
  access in the project that owns it. That project's region is a residency decision this stack
  cannot make for you: confirm it before pointing at the view.
- **The Dialogflow CX agent.** The conversational design is the client's. The API is enabled
  and the serving identity holds `roles/dialogflow.client`; set `chat_agent` to the agent path.
- **A UI service.** `ui/` ships no Dockerfile, so a UI backend would point at an image nothing
  produces.

Order of operations that is not obvious:

1. Apply with `production_edge_enabled = false` first. The residency, encryption and audit
   stack stands up on its own and can be reviewed before anything serves traffic.
2. Locking the WORM bucket is IRREVERSIBLE. Confirm `retention_days` before that first apply.
3. The perimeter starts in dry run deliberately. Watch the `vpc_sc_denials` alert for a full
   business cycle, add the operator identities to `operator_members`, and only then set
   `vpc_sc_enforce = true`. Never enforce blind on a path nobody has watched.
4. The IAP audience needs TWO applies, because the value is the id of the backend service the
   first apply creates. Apply, read the `iap_audience` output, set the `iap_audience` variable
   to it, apply again. In between, the service is health-checkable and refuses every end-user
   request with the 503 described below, which is the documented fail-closed state and not a
   gap to work around.
5. `OUTREACH_SPEECH_OUTPUT_URI` is not a variable. The stack creates the audio bucket and sets
   the value from it, because an operator who could name the destination could name an
   out-of-region one.

`make tf-check` runs `terraform init -backend=false`, `validate`, `fmt -check` and
`terraform test`. The test file uses a mocked provider, so it proves the refusals (an
out-of-region deploy, a retention below six months, a mutable image tag, an edge with no
review console, an edge with no consent store, an edge with no alert channel, a moving secret
version) without a project and without credentials. A real `terraform plan` needs a project and
is an operator step.

## Installing the private commons

Four of the six pinned commons are public repositories and install with no credential.
`consent-preference-kit` and `speech-lexicon-kit` are PRIVATE, so an environment that cannot read
them cannot run `make install` at all, and the failure looks like a network error rather than an
authorisation one.

Provision the credential deliberately, before the first build rather than after a red pipeline:

```bash
gh auth setup-git                 # a developer machine that already has gh
git config --global url."https://x-access-token:$TOKEN@github.com/".insteadOf \
    "https://github.com/"         # a build agent, with a read-only fine-grained token
```

The token needs read access to `portable-genai/consent-preference-kit` and
`portable-genai/speech-lexicon-kit` and nothing else. Do not vendor a copy of either kit to avoid
this: a vendored consent client is a second answer to a legal question about a person, which is
the whole reason the kit exists.

The lockfile headers carry the same note, so whoever reads the failure has it in front of them.

## The IAP audience (required for the gcp profile)
`OUTREACH_IAP_AUDIENCE` is the IAP-protected resource the assertion must be
addressed to: `/projects/<PROJECT_NUMBER>/global/backendServices/<BACKEND_SERVICE_ID>` behind an
HTTPS load balancer. Read through `iap_audience` in `config/settings.yaml`, so it resolves in the
usual three states and UNSET and SET-AND-EMPTY both land on empty.

It is not optional and there is no unverified fallback, because the fallback is the vulnerability.
`google.oauth2.id_token.verify_token` documents `audience=None` as "the audience is not verified",
so an adapter that omitted it would accept ANY Google-signed OIDC ID token, from any project and
any application, and turn its `email` claim into a verified principal on this service. The adapter
therefore refuses before it reads the assertion header at all, which also means the refusal does
not depend on the SDK being importable or on the network being up.

Two operator-facing refusals, both 503 rather than 401 because no credential the caller could
present would have helped, and both naming what to fix:

| Symptom | Cause | Fix |
|---|---|---|
| 503, detail names `OUTREACH_IAP_AUDIENCE` | no audience configured | set it to the protected resource above |
| 503, detail says the verifier is not installed | `google-auth` missing from the image | install `requirements-gcp.lock` (the shipped `Dockerfile` does) |

A caller-facing failure is different: a malformed, expired, wrong-audience, wrong-issuer or
wrong-key assertion answers **401 `authentication required`**, with the specific reason recorded in
the log and the exception chain rather than returned. That asymmetry is deliberate: telling an
unauthenticated caller which check failed tells them what to change next. Nothing in this path may
answer 500; `scripts/prove-exposure-matrix.sh` in the template drives each of those cases over a
real socket from a real LAN address and fails on a bare 500, and
`tests/unit/test_iap_crypto_matrix.py` runs the real verifier over locally minted assertions with
no project, no credential and no network.

## Interactive API docs
Swagger UI (`/docs`), ReDoc (`/redoc`) and the raw OpenAPI document (`/openapi.json`) are served
under the DELIBERATE offline `local` profile and nowhere else; every other posture answers 404
because the routes are not registered at all. They are a development affordance, and on a fronted
deployment they hand an uncredentialed caller the complete route inventory and every request and
response schema, for routes that same caller cannot reach. There is no variable to switch them back
on: the schema is generated from the source and available to anyone with the repository, and a
deployment that wants to publish it should serve the artifact from somewhere that is not the
authenticated service. Removing the routes rather than guarding them is what holds under `gcp`,
where the loopback guard has deliberately stood down and the process binds every interface.

## Rate limits / body caps
Enforced at the edge. `infra/terraform/production_edge.tf` provisions the Cloud Armor policy
that throttles per source IP (`edge_per_source_rate_limit_per_minute`, 120 by default) and
answers 429 above it, so the ceiling is applied before a sweep costs a warehouse read, a
consent question per event and a model call each.

## Exposure of an unauthenticated posture
An END-USER route is authenticated here when, and only when, the identity adapter the active
binding names can produce a verified principal WITHOUT trusting a header the client wrote. That is
the single question the guard below asks, and the answer comes from the adapter itself, which
declares it (`ports/identity.py`, `config.end_user_auth_kind`). The shipped answers:

| Identity binding | Declares | End-user routes |
|---|---|---|
| `local` seeded dev personas | `client-asserted` | NOT authenticated: the caller names a persona in `X-Dev-Persona` and receives its groups and tenant |
| `gcp` IAP assertion | `verified` | authenticated: the signature (against IAP's own key set), the audience (against `OUTREACH_IAP_AUDIENCE`), the expiry and the issuer are all checked before any claim is read |
| `onprem` placeholder | `unimplemented` | nobody can be authenticated until the client's own IdP adapter is bound |

So a request arrives with nothing authenticating the end user in exactly three situations, and ALL
THREE are bounded by the guard below:

1. **Nobody chose a profile.** `OUTREACH_PROFILE` is absent, so no end-user
   identity scheme and no service-to-service scheme has been selected. This is what a production
   deployment looks like when the variable drops out of its environment, and it is refused rather
   than relaxed: the seeded-persona adapter will not construct (401), every S2S route answers 401,
   the dev CORS allowlist and the `X-Dev-Persona` header are withdrawn, HSTS is on, and every
   route, `/healthz` included, is refused to any non-loopback peer.
2. **The `local` profile, chosen deliberately.** The seeded personas are a client-asserted
   identity, so this is bounded whatever else is configured, INCLUDING when
   `OUTREACH_S2S_TOKEN` is set. Setting that secret closes the S2S
   dependency and nothing else: it authenticates a calling SERVICE and authenticates no end user,
   so it cannot make `/v1/outreach/evaluate` or `/v1/personas` authenticated and it does NOT switch the
   guard off. Were it to, a LAN peer with no credential at all would receive the full seeded
   persona list, approver included, and a real held outreach decision.
3. **The `onprem` profile with the placeholder still bound.** No identity provider is wired, so
   no end user can be authenticated. `/v1/outreach/evaluate` answers 501 with the reason and the name of the
   file to read; binding a verifying adapter (below) is what lifts both the 501 and the bound.

Symmetrically, the guard STANDS DOWN when the binding declares `verified`: `gcp` serves
`/healthz` and the discovery card to any peer (a fronted deployment must stay health-checkable
and neither carries per-caller data) while `/v1/outreach/evaluate` answers 401 without an IAP assertion. The
route does the authenticating, which is the whole reason the guard may stand down.

That is also why the declaration has to be EARNED rather than asserted. It was not: the verifier
was called with no audience and no key-set URL, so any Google-signed token from any project was
accepted, and the call was unwrapped, so a caller-supplied header that was not a JWT crashed out
of the route as a bare 500. Both are closed, and the interactive docs went with them (below):
under this profile the process really does bind every interface, so anything the guard is not
covering has to be safe on its own.

To lift the bound on an on-premises deployment, bind an identity adapter that verifies your IdP's
assertion under `adapters.identity.onprem` in `config/settings.yaml` and declare
`end_user_auth = VERIFIED` on it. See [onprem-migration.md](onprem-migration.md). Nothing else
lifts it except the explicit opt-out below.

The bound is applied twice, and the outer one is on the app object rather than on one entry point:

- `add_loopback_exposure_guard` is registered at module scope in `api/app.py`, so it holds under
  `uvicorn proactive_outreach.api.app:app --host 0.0.0.0` (what the Dockerfile `CMD`
  and `make run-api` do) as well as under `main()`. A non-loopback peer gets 503; a WebSocket is
  closed with 1008. A request carrying `x-forwarded-for` or `forwarded` is refused whatever it
  claims, because a proxy has already overwritten the ASGI peer address.
- `resolve_bind_host` still binds loopback in `main()`, for the same three situations: the
  start-up bound and the request-time guard read one derived posture, so a process can never bind
  every interface while refusing every caller on it.

Set `OUTREACH_ALLOW_INSECURE_DEMO=1` to accept the exposure deliberately.
That is the only opt-out, and it is read per request rather than baked in at import.

`scripts/prove-exposure-matrix.sh` in the template repo drives the whole matrix (profile x S2S
token x persona header) against a real socket from a real LAN address;
`tests/unit/test_serving_path_exposure.py` and `tests/unit/test_end_user_auth_posture.py` are the
in-gate halves, the second of which fails the build if the guard's posture ever reaches a service
credential again.

## Profile misconfiguration
`OUTREACH_PROFILE` is read once, in `config.py`, and it has three states:

| State | What happens |
|---|---|
| unset | No choice was recorded. The SDK-free adapters bind (the alternative is importing cloud SDKs that are not installed), but every relaxation is withdrawn and the exposure guard refuses every route to any non-loopback peer. Symptom: 401 on `/v1/outreach/evaluate` naming the variable, and 503 naming the `unconfigured` posture from off-box. Fix: set the variable. |
| set to an empty value | Refused AT IMPORT (`ConfiguredEmptyError`). The process does not start. An emptied variable is an expressed intent that names no profile, so it never inherits the unset behaviour. Common cause: a config map or deployment template that renders an empty string. |
| set but unknown, including `Local`, `LOCAL`, `GCP` | Refused AT IMPORT. A typo is not a synonym, and coercing the case would turn it into a silent choice. |

In every refusing case the process fails to boot or answers 4xx/5xx, rather than serving a first
request on a posture nobody chose. The relaxations key off a derived `exposure_profile` and the
loopback bound off a derived `bind_profile`, because those two fail closed in opposite directions:
see `config.ProfileChoice`.

## Human review routing (rule R8)
Set `HRZ_HUMAN_REVIEW_URL` to the Hrz7 console (HTTPS is required off loopback) and provide
`HRZ7_S2S_TOKEN`; `HRZ7_S2S_SIGNING_KEY` optionally signs the propagated actor. These are the
OUTBOUND credentials and are deliberately distinct from this service's own inbound
`OUTREACH_S2S_TOKEN`. With the URL unset, the managed router REFUSES rather
than swallowing the escalation, so a misconfiguration is a loud failure and never a silent
auto-execution. Under the local profile the escalation goes to the review-kit outbox, which is
inspectable and flushes to the console when one becomes reachable.

## Supply chain
Installs come from the committed lockfiles. After changing a dependency run `make lock` and commit
both files, then `make audit` (`pip-audit` over both locks). CI runs the same audit as a hard
failure, so a known-vulnerable dependency blocks the merge.

## Audit operations
The local WORM log supports `verify_chain()` and JSONL export/restore.

**Configure the external head anchor for any durable audit path.** Set
`OUTREACH_AUDIT_ANCHOR` (read by `audit_anchor_path` in
`config/settings.yaml`) to a file on a DIFFERENT volume from
`OUTREACH_AUDIT_PATH`, ideally writable by a different principal. This is
not decoration:

- the hash chain detects an edited, deleted or reordered record, because each of those breaks a
  link;
- it CANNOT detect a truncated tail, because dropping the newest rows leaves a shorter chain
  that verifies perfectly. Only the anchored head exposes that.

Leave it unset only for the ephemeral `:memory:` store the gate uses.

Operating rules:

- **The anchor is not last-write-wins.** Once the store and the anchor disagree, the service
  REFUSES to append rather than re-anchoring the store as it now stands, because one ordinary
  append would otherwise launder the divergence. Expect a hard failure on the write path, not a
  warning in a log nobody reads.
- **Re-establishing an anchor is a deliberate act.** Verify the store out of band first (against
  an exported trail held elsewhere), then call `reanchor()`. Never as a reflex to clear an alert.
- **Verify on a schedule**, not only after an incident: `verify_audit_trail` (the agent tool) and
  `HashChainedAuditLog.verify_chain()` both return the anchor cross-check, and the tool's
  `anchored` field says whether the stronger guarantee was even available.
- A managed WORM sink does not need the anchor: it provides non-rewritability itself.

## Agent surface
The A2A discovery card is served at `/.well-known/agent-card.json` and is built from the same
tool table the runtime binds, so it cannot advertise a skill the service does not implement.
Register it with the Hrz3 registry (rule R4). The tools themselves need no agent runtime to run;
only `build_function_tools()` imports one.

## Running the integration tests
`make test-integration` runs `tests/integration/`, which the offline gate deselects. Each test
SKIPS rather than fails when its configuration is absent, so an unconfigured run reports nothing
rather than a false pass. It writes an obviously fictional audit record to the configured project
and, when `HRZ_HUMAN_REVIEW_URL` is set, submits one fictional review to the live console.

## Alerts
`infra/terraform/monitoring.tf` creates a log-based metric and an alert policy for each posture
signal. Five come from the platform or apply to any service in the catalog: a service-account
key creation (org policy should have refused it, so this firing means the policy is off), a
VPC-SC violation, a CMEK key destroy or update, a Cloud Armor denial at the edge, and a
critical-severity escalation in this service's audit log.

Three are this vertical's own, and they exist because the interesting failure of an outbound
service is SILENCE rather than an error:

| Alert | Fires on | Why it is not noise |
|---|---|---|
| `consent_unavailable` | a refusal carrying `consent_unknown` | the eligibility engine returns it when the Mkt6 store gave no usable answer. Refusing is correct; it is also exactly what a total store outage looks like, and while it lasts this service contacts nobody while every request still answers 200 |
| `policy_gap_refusals` | a refusal carrying `frequency_cap_unconfigured` or `quiet_hours_unconfigured` | an unconfigured cap or market DENIES by design, so a policy gap presents as customers not being told things. This is the alert that tells the policy owner they have a hole rather than a quiet quarter |
| `draft_discarded` | the validator refused what the model wrote | one is a working control; a rate of them is a model or prompt regression, and each costs a human a review |

Attach a channel through `alert_notification_channels`; the serving edge refuses to plan
without one, because an alert nobody receives is not an alert.

There is deliberately NO alert on `frequency_cap_exceeded`. A cap that refuses a fourth message
in a day is the product working exactly as specified, many times a day, and an alert on the
intended outcome trains an operator to ignore the channel. The cap arithmetic is proved by
`frequency_cap_exactness >= 1.0` in the eval, which is where an arithmetic claim belongs.

There is likewise no guardrail-block alert: this service binds no guardrail port yet (see the
R1 row in `COMPLIANCE.md`), and a metric whose filter can never match reads as a green light
nobody earned. Add it in the same commit that binds the guardrail.
