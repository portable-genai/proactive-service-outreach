# ARCHITECTURE: Proactive Service Outreach (E5)

Hexagonal ports-and-adapters. A pure-stdlib domain core speaks only to ports (`typing.Protocol`s);
adapter families implement them; one env var (`OUTREACH_PROFILE`) swaps the
whole stack with no domain edits.

Profile selection is an exact lookup. Every declared profile has an entry for every port; when
two profiles intentionally reuse one adapter, both entries name it. A missing local or exit
binding never inherits `gcp`, so it cannot import a managed SDK or change data custody silently.

`local` runs the real API, orchestration and deterministic domain with local or synthetic edges.
It may reduce narration quality, throughput, durability, enterprise identity, managed safety
and telemetry, but it does not change figures, evidence links, escalation rules or schemas.
`make portability` executes this boundary. A construction-only primary managed operation must
block API startup and Terraform serving authorization until its integration test exists.

## Layout (`src/proactive_outreach/`)
- `domain/` : pure stdlib, no cloud/framework imports. `kernel.py` (vertical-neutral types,
  `StrEnum` taxonomies from the commons), `models.py` (the events, triggers, decisions and
  messages), `pii.py` (the jurisdiction pattern selection + order), `policy.py` (the bank's
  numbers as a frozen dataclass with fail-closed lookups), `trigger_engine.py`,
  `eligibility.py`, `drafting.py` (three pure engines, each with an explicit `as_of` and no
  clock), and `outreach_service.py`, which owns only the ORDER and the ports.
- `ports/` : `@runtime_checkable` Protocols (`AuditSinkPort`, `ReviewRouterPort`,
  `EventDetectionPort`, `ConsentPort`, `DraftingPort`, `MessageDeliveryPort`; identity uses the
  commons `IdentityPort` and text-to-speech uses `speech-lexicon-kit`'s `TextToSpeechPort`),
  re-exported once with the `PORT_PROTOCOLS` map. `identity.py` adds
  this service's own identity vocabulary: what an adapter DECLARES about the end-user
  authentication it provides (`VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`), which is what the
  loopback exposure guard reads, plus the refusal type that carries a status and a reason when no
  end user can be authenticated at all.
- `adapters/{local,gcp,onprem}/` : one adapter per port per profile. GCP imports are lazy.
  `adapters/_review_payload.py` is the shared, redacted conversion to the review kit's wire shape.
- `config.py` : `Settings` + `Container` (lazy DI, dotted `module:Class` bindings loaded from
  `config/settings.yaml`).
- `api/` : FastAPI app wired with the commons identity / S2S / fail-closed helpers.
- `cli/` : a stdlib argparse CLI.
- `agent/` : the optional-but-scaffolded agent surface. `tools.py` holds plain Python callables
  that delegate to the domain services (no business logic of their own) and route escalations
  like every other surface; `agent_card.py` builds the A2A discovery card served at
  `/.well-known/agent-card.json`. Nothing here needs ADK or a cloud SDK to import or test:
  `build_function_tools()` is the single lazily-imported runtime seam.

## Surfaces outside `src/`
- `scripts/` : the demo surface. `demo.py` holds the scripted arc and drives the REAL services;
  `render_ui.py` paints its panels as dependency-free static HTML; `demo_server.py` serves the
  same panels live, one real step per click; `walkthrough.py` drives that server over loopback
  HTTP and asserts every step, which is what lets the presenter tool double as the unattended
  self-test. `portability_demo.py` and `check_docs_links.py` are standalone checks. Nothing here
  is imported by `src/`, and `.dockerignore` keeps all of it out of the serving image.
- `ui/` : the embeddable Next.js micro-frontend. Its security boundary is one policy module
  (`lib/embed-policy.mjs`) shared by the document-layer `proxy.ts` and the same-origin API route,
  plus one server-side identity module (`lib/server/identity.ts`). The browser never asserts an
  actor and never holds the service credential. Delete it with `make drop-ui` if this repo has no
  user-facing surface; the gate checks that decision for consistency in both directions.

## Test layout (`tests/`)
`unit/` (one module or service, driven by the REAL local adapters), `contract/` (the boundary
claims: conformance, the five-way port drift guard, behavioural parity), `integration/` (needs a
live service; marked so the offline gate deselects the whole directory) and `fixtures/` (shared
data only). `contract/canonical.py` holds ONE canonical request per port, so the structural and
behavioural suites cannot quietly assert different things.

## Request pipeline (`OutreachService.evaluate`, then the caller)

    redact -> trigger -> consent -> eligibility -> [draft] -> [validate] -> [deliver] -> audit

Nothing in brackets happens unless the step before it said yes, and THAT is the control this
service sells. Written out:

1. the source system's free-text detail is masked (P-04) before it reaches anything at all;
2. the trigger engine decides, from configured rules, whether the event is worth a contact;
3. the consent store (Mkt6, through `consent-preference-kit`) is asked one question, pinned to
   one instant. Any failure to obtain an answer becomes "no decision", which denies;
4. the eligibility engine composes consent, suppression, the frequency cap and quiet hours,
   worst-wins, failing closed on anything it does not fully understand;
5. ONLY THEN is a body drafted, from a closed fact set, through the single port a model is
   reachable through. It is validated and discarded on any failure;
6. delivery carries a `DeliveryEnvelope` with the consent decision id and the cap counters, and
   the send is recorded back so the cap actually binds;
7. the decision, including every refusal, is written to the already-redacted WORM trail.

A consequential event type, or a discarded draft, sets `requires_human_review`, delivers
NOTHING, and is routed to Hrz7 (R8) by the caller in the same request. The audit actor and the
review maker are both the verified `Principal`, never the request body, and the tenant comes
from the principal too.

The instant every step is decided against is an explicit argument, which is what makes the whole
thing replayable; no surface lets its caller choose it, because quiet hours turn on it.

## The port table
| Port | local | gcp | onprem |
|---|---|---|---|
| `AuditSinkPort` | hash-chained SQLite WORM (commons) | Cloud Logging WORM (lazy) | placeholder |
| `ConsentPort` | synthetic record set, same wire types | Mkt6 consent store over S2S (stdlib) | placeholder |
| `DraftingPort` | deterministic template in the drafter's envelope | managed model (lazy) | placeholder |
| `EventDetectionPort` | fixture events, stable order | client-owned warehouse view (lazy) | placeholder |
| `IdentityPort` | seeded personas (commons) | IAP assertion (lazy) | placeholder |
| `MessageDeliveryPort` | in-process chat outbox with the envelope | conversation platform (lazy) | placeholder |
| `ReviewRouterPort` | review-kit outbox (offline, inspectable) | Hrz7 service intake over S2S | placeholder |
| `TextToSpeechPort` | deterministic audio reference, no bytes | managed speech + in-region bucket (lazy) | placeholder |

The on-prem placeholders RAISE. Three of them matter more than the rest: a review router that
silently returned would convert every consequential result into an unreviewed one; a delivery
adapter that returned a receipt would count a contact that never happened against a customer's
frequency cap and tell the consent store about it; and a consent adapter that returned anything
at all would be inventing a legal position about a person.

Note what the consent row is NOT. There is no local consent STORE, on any profile. The store
lives inside Mkt6, which already models consent and already owns the rule engine a denial cites;
this repo is one of its consumers, and the offline adapter answers from a synthetic record set
using the store's own wire types so the gate exercises the real parsing and the real fail-closed
rules rather than a kinder second implementation of them.

A port is registered in FIVE places: `ports/__init__.py` (`PORT_PROTOCOLS`), `config.py`
(`DEFAULT_BINDINGS` and a `Container` accessor), `config/settings.yaml` and
`tests/contract/canonical.py`. `tests/contract/test_port_parity.py` asserts set equality across
all five, so a port that is bound but unregistered (or registered but unbound) fails the build
instead of running with no enforcement. The full touch list is in `CONTRIBUTING.md`.

## Audit integrity
The local WORM log is hash-chained AND anchored: `audit_anchor_path` points at an external file,
on a different volume, that every append writes the chain head to. The chain alone catches an
edit, a deletion or a reorder; only the anchor catches a truncated tail, because a truncated
chain still verifies. `tests/unit/test_audit_anchor.py` proves both halves, including the
control case where the same truncation goes undetected without an anchor.
