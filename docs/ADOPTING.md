# Adopting this repo as your base

This repository (E5, Proactive Service Outreach) is a **common base** that a bank, insurer or
other regulated institution forks to build its own **consent-gated outbound service messaging**:
a service that turns operational events (a failed payment, a missed delivery, an expiring card,
a fraud hold, an outage) into a deterministic, replayable, fully cited answer to "may this
person be contacted, about this, on this channel, right now", and only then lets a model phrase
the message. It ships a reusable hexagonal core (a pure-stdlib domain, typed ports, three
swappable adapter families, a green offline gate) plus a fully worked outreach vertical you can
keep, retune, or replace with your own event set.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical rebrand**
(one script) and the **human decisions** the script cannot make for you.

> Related reading: [`../ARCHITECTURE.md`](../ARCHITECTURE.md) (the port table and the topology),
> [`../CONTRIBUTING.md`](../CONTRIBUTING.md) (the file-by-file touch list for a new port or
> adapter), [`model-card.md`](model-card.md) (the model boundary), and the [`faq/`](faq/)
> directory.

---

## 1. What you keep vs what you rewrite

The domain is layered so the boundary is a physical module split, not a convention.
`domain/kernel.py` holds the vertical-neutral machinery and knows nothing about outreach;
everything else in `domain/` is this vertical.

| Layer | Where | For a new vertical |
|---|---|---|
| **Vertical-neutral machinery** | `domain/kernel.py`, `domain/pii.py`, every Protocol in `ports/`, the container wiring in `config.py`, and the commons (`hex-service-kit`, `pii-kit`, `review-kit`, `agent-eval-kit`, `consent-preference-kit`, `speech-lexicon-kit`) | keep untouched |
| **Policy (your numbers)** | the whole `policy:` block of `config/settings.yaml`: trigger rules, frequency caps, market quiet hours with an explicit UTC offset, templates, the suppression list, banned phrases and the body limit. Parsed and validated by `domain/policy.py` (`OutreachPolicy`, `TriggerRule`, `FrequencyCap`, `QuietHours`) | change by configuration, never by editing an engine |
| **Vertical (the outreach artifacts)** | `domain/models.py` (`ServiceEvent`, `OutreachTrigger`, `DraftRequest`, `OutreachMessage`, the decision types), `domain/trigger_engine.py`, `domain/eligibility.py`, `domain/drafting.py`, `domain/outreach_service.py`, the local fixtures in `adapters/local/fixtures.py`, the eval golden set and the UI views | rewrite or reseed for your data |

If your product is another *consent-gated outbound* system, most of this transfers directly: the
hexagon, the three families, the fail-closed eligibility pattern, the discard-on-failure drafting
path and the Hrz7 routing. You replace the trigger rules and the templates, and you retune the
policy numbers.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly.

- **Upstream-owned** (take our changes): `domain/kernel.py`, `ports/`, `tests/contract/`, the
  eval harness mechanics (`eval/run_eval.py`), the CI workflows, the `Container` wiring in
  `config.py`, and the fail-closed posture in `api/app.py`.
- **Adopter-owned** (yours; expect to edit): the `policy:` values in `config/settings.yaml`, the
  synthetic event fixtures, `adapters/onprem/*`, UI theming and branding, the golden eval
  dataset in `eval/datasets/`, and the regulator crosswalk section of
  [`../COMPLIANCE.md`](../COMPLIANCE.md).

Track upstream by git tag, and rebase your adopter-owned changes onto each release rather than
merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the package name (`proactive_outreach`, which is also the
console-script name), the `OUTREACH` environment prefix, the distribution and resource id
(`proactive-service-outreach`) and the Terraform `name_prefix` default, in one pass. Preview
first, then apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_service_outreach \
    --env-prefix ACMEOUTREACH --resource acme-service-outreach \
    --name-prefix acme-outreach --dry-run

# Apply:
python scripts/rename_fork.py --package acme_service_outreach \
    --env-prefix ACMEOUTREACH --resource acme-service-outreach \
    --name-prefix acme-outreach --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
make install
make gate
```

There is deliberately no `--cli` flag: `[project.scripts]` names the console script after the
package, so `--package` renames both and a second flag could only drift out of step. There is no
`--dist` flag either: the distribution name, the GitHub id in `[project.urls]`, the A2A
agent-card name and the Hrz4 eval bundle id are the same one literal, and `--resource` renames
it. Add `--include-docs` to sweep Markdown prose too. The script deliberately does NOT touch the
human decisions below.

## 4. The human decisions (the script can't make these)

1. **Region and residency.** The build pins `asia-southeast1` (MAS and Singapore). Change it in
   BOTH places: `region` in `config/settings.yaml` (via `GCP_REGION`), and the Terraform pair
   `region` and `allowed_regions` in `infra/terraform/variables.tf`, which are validated against
   each other at plan time so an unapproved region fails before anything moves. Do not set
   `OUTREACH_SPEECH_OUTPUT_URI` by hand in a deployed stack: the Terraform sets it from the
   bucket it created, because an operator who could name the destination could name an
   out-of-region one. Prove the change with `make tf-check` (mocked provider, no project, no
   credentials). See [`runbook.md`](runbook.md).
2. **Identity and your IdP.** This repo owns no login flow. Under `gcp` the identity adapter
   verifies the Cloud IAP-injected assertion and refuses when `OUTREACH_IAP_AUDIENCE` is unset or
   emptied; under `local` it seeds dev personas that authenticate nobody; under `onprem` it is a
   client-IdP placeholder that raises. Configure IAP on the deployed service and set the
   audience, or implement the `onprem` adapter against your own issuer.
3. **The policy numbers, which are your conduct position.** Every value a decision turns on is
   in the `policy:` block: which events fire and what attributes they require, which of them are
   `consequential` (drafted, held and routed to a human rather than delivered), the frequency
   caps per purpose and channel, and quiet hours per market with the UTC offset written out. A
   purpose and channel with no cap row DENIES, and a market with no quiet-hours row DENIES: that
   is deliberate, and it means adding a market is a policy act rather than an oversight. Own
   these with your conduct and compliance functions, and pin your values with a test.
4. **The consent store.** There is no consent store in this repo and there must not be one:
   `consent-preference-kit` is the client half and Mkt6 owns the record. Point `consent_url`
   (`MKT_CONSENT_STORE_URL`) at your deployment and load the subjects and purposes this service
   will ask about. Every unknown consent state denies (`domain/eligibility.py`), so a
   misconfigured store refuses to contact anyone rather than contacting everyone.
5. **The event source.** `event_view` (`OUTREACH_EVENT_VIEW`) names a client-owned warehouse view
   exposing the columns `adapters/gcp/events.py` reads. The view is the contract, so this service
   never learns how your ledger records a decline. It is also the one location this stack cannot
   pin to a region, because it lives in your project; say so in your own residency assessment.
6. **The templates and the channels.** The message templates in the `policy:` block are the words
   your customer actually receives, so they are a conduct artifact and not a vendor default.
   Wire `chat_agent` for the chat channel, and `speech_voice` plus the audio bucket for voice.
7. **Reference data is fictional.** Every event fixture, subject id and eval case uses obviously
   fake parties and `.example` domains. Replace them with your own synthetic data. **Do not run
   against real customer events without your own legal, privacy and model-risk sign-off.**
8. **Eval golden set.** Rebuild `eval/datasets/` and the rubrics for your triggers and templates:
   a fork inherits a green gate that measures the WRONG policy until you do. The gate structure
   and the not-falsely-green harness (`tests/unit/test_not_falsely_green.py`) are generic; the
   golden cases are yours.
9. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root), `infra/terraform/`
   (Org Policy, CMEK, the dry-run-first VPC-SC perimeter, the locked WORM log bucket) and the
   loopback-by-default API binding before you expose anything. The Terraform in this repo has been
   validated and tested; it has never been applied.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it *touches* are
owned by sibling services, and you integrate rather than rebuild them. See
[`faq/features.md`](faq/features.md) for the full boundary map.

- **Mkt6** consent and preference store: consumed through `consent-preference-kit`. This service
  holds no second copy of anybody's consent, because a second copy is a second answer to a legal
  question about a person.
- **Hrz7** human-review console: every held result is routed there in the same call that produced
  it, over the shared `review-kit` (rule R8). You wire your endpoint; you do not
  re-implement the console.
- **Hrz1** guardrail gateway: the injection-defence and output-filtering hop for the drafted body.
- **Hrz3** agent registry: this agent publishes its A2A card at
  `/.well-known/agent-card.json` for discovery.
- **Hrz4** AI-quality and model-risk gate: owns promotion. `eval/run_eval.py --mode gate`
  delegates the verdict to it, and refuses to run off the managed profile.
- **Hrz5** observability and immutable WORM audit: trace spans and audit events go there.
- **Hrz2** enterprise knowledge base: **not** integrated, and should not be. This service
  retrieves nothing. Its messages are rendered from a closed fact set the trigger engine
  assembled, so there is no retrieval path to ground.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make gate` green.
- [ ] Set the region in `config/settings.yaml` AND the Terraform `region` / `allowed_regions`
      pair, and `make tf-check` still passes.
- [ ] Configured IAP on the deployed service and set `OUTREACH_IAP_AUDIENCE`, or implemented the
      `onprem` identity adapter.
- [ ] Replaced every value in the `policy:` block with your own, and pinned them with a test.
- [ ] Pointed `consent_url` at your Mkt6 deployment and loaded the subjects and purposes.
- [ ] Pointed `event_view` at your warehouse view and confirmed the column contract.
- [ ] Had your conduct function sign off the message templates and the `consequential` flags.
- [ ] Replaced every synthetic fixture and event.
- [ ] Rebuilt the eval golden set and rubrics for your triggers.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, bind address) before exposing anything.
- [ ] Wired your Hrz7 endpoint and decided which sibling services you integrate vs stub.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
