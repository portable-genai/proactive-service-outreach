# FAQ: adopting this

## What do we have to supply?

Four things, and none of them is code in this repo:

1. **The policy.** The `policy:` block of `config/settings.yaml`: trigger rules, frequency caps,
   quiet hours per market with an explicit UTC offset, message templates, the suppression list,
   banned phrases and the body limit. The shipped values are synthetic.
2. **The event source.** A warehouse view exposing the columns `adapters/gcp/events.py` names.
   The view is the contract, so this service never learns how a payment ledger records a decline.
3. **The consent store.** An `marketing-compliance-gate` deployment, reachable, with the subjects and purposes this
   service will ask about. There is no local fallback by design.
4. **The channels.** A conversation platform for chat, and a speech voice plus an in-region
   bucket for voice.

## What sibling systems does it need?

`agent-guardrail-gateway` (guardrails), `agent-registry` (agent registry), `agent-observability` (observability and immutable audit), `model-quality-gate` (the
promotion gate), `human-review-console` (human review, rule R8) and `marketing-compliance-gate` (the consent and preference store). `marketing-compliance-gate`
and `human-review-console` are the two it cannot run without: one answers whether a person may be contacted, the
other receives everything that must not go out automatically.

## How do we know a change did not break it?

`make gate` is offline, credential-free and network-free: lint, format, mypy strict, the whole
test suite except integration, and six eval metrics. `make demo-selftest` runs the nine-step
demo headless and asserts every narrated claim. `make portability` runs the exit tour. All three
run in the hosted check on every pull request and every push to main.

## The evals all report 1.000. Should we believe them?

Only because each one is proved able to report something else.
`tests/unit/test_not_falsely_green.py` hands every metric a planted mutant (a flipped label, an
unknown consent state relabelled as a grant, a cap count moved by one, an invented figure
labelled acceptable, a consequential case relabelled as deliverable, redaction switched off) and
fails the build if the metric still passes. A metric that cannot go red is not a metric.

## What is still open?

`docs/practices-audit.md` carries the honest per-check verdict and names the day-one work list.
`infra/terraform/` carries the residency allowlist, Org Policy, CMEK, the dry-run-first VPC-SC
perimeter and the locked WORM log bucket, and `make tf-check` proves the refusals offline against
a mocked provider. What remains is the part that needs your network and your project: the private-egress
rule that lets this service reach the consent store and the review console and nothing else,
the Interconnect attachment, and registering this repo's metric bundle with `model-quality-gate` so gate mode
has an authority to ask. The configuration in this repo is validated and tested; it has never
been applied.
