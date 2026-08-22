# DEMO: Proactive Service Outreach (E5)

Everything here runs **offline**: no cloud project, no credentials, no API key, no browser
engine, no bundler. That is the first thing to say out loud, because it is the claim the rest of
the demo rests on.

```bash
make install          # locked install from requirements-dev.lock
make demo             # the presenter-paced walkthrough (starts its own server)
```

## The nine-step walkthrough

`make demo` starts a loopback server, opens the page, and then waits for you at every step. The
narration is printed on **your terminal**, never on the page, so the audience sees only the clean
output view. At a prompt: **Enter** runs the step, a **number** jumps to that step, **r** restarts
the run, **q** quits.

Every step drives the real services. Nothing is pre-recorded, and every step is ASSERTED: if the
service does not actually reach the state the narration just claimed, the walkthrough says so and
exits non-zero.

| # | Step | The point to make |
|---|---|---|
| 1 | Bound on the offline profile, policy loaded | One variable binds every port, and not one number a decision turns on is in the code. Caps, quiet hours and trigger rules all come from the settings file, because they are the bank's. |
| 2 | Five operational triggers | Failed payment, delivery exception, expiring card, fraud hold, outage. Two of the five are marked consequential. An event missing the fact the message would have to quote does not fire at all. |
| 3 | Eligibility fails closed | Seven questions, one permitted. An unknown subject, a withdrawn grant, a reason token this client has never seen, a subject at the cap, a suppressed subject and a market at 23:00 all refuse. The model has still not been called. |
| 4 | The model may phrase, not inform | Only now is anything drafted, from a closed fact set. A draft carrying an invented amount is DISCARDED, not corrected: there is no repair path in the code. |
| 5 | Every send carries what authorised it | The consent decision id and the cap counters ride the envelope, and the send is recorded back so the cap actually binds. A refusal is audited beside the sends. |
| 6 | Consequential outreach is held | A fraud hold: eligible, and still not sent. Routed to the console with the proposed words attached, because a reviewer who cannot see the sentence cannot approve it (rule R8). |
| 7 | The audit trail | Every decision including every refusal, hash-chained, externally anchored, exportable to JSON Lines that reload elsewhere with the chain intact. |
| 8 | A tampered record | An attacker with file access rewrites a record; the chain names exactly which one. Tamper-EVIDENT, not tamper-proof. |
| 9 | The exit profile | The same calls on `onprem`, no code edited: all eight seams refuse loudly rather than dropping the work. |

Steps 3 and 4 are the ones to linger on with a compliance audience, and step 8 with a technical
one. A demo where nothing ever goes wrong is a sales deck; this one refuses six contacts out of
seven, throws away a message the model wrote, and then breaks its own audit trail and detects it.

The whole arc is decided against ONE pinned instant, so it produces the same output every time.
That is not a demo convenience; it is the property the service sells, and it is worth saying so
while the numbers are on screen.

## The other three ways to run it

```bash
make demo-selftest    # unattended and headless, asserts every step, non-zero on failure
make demo-static      # demo.json plus out/index.html and out/step-*.html, for screenshots
make portability      # the executable portability claim: named checks, pass or fail each
```

`make demo-selftest` runs in CI on every push (`.github/workflows/demo-gate.yaml`), so the demo
cannot rot silently between showings. `scripts/README.md` documents each script and the
environment overrides.

## The claims, and their bounds

State the bounds yourself. An unbounded claim is the one an auditor disproves for you.

| Claimed | Proved by | NOT claimed |
|---|---|---|
| Runs with no cloud, credentials or network | the whole demo, plus `make gate` | that the managed profile works: that needs a project and lives in `tests/integration/` |
| Whether a customer is contacted is decided by pure code, and replays | steps 2 and 3, `make gate` | that a model's phrasing is deterministic; it is not, and it never decides |
| An unknown consent state never permits contact | step 3, the `consent_fail_closed` metric at 1.0 | that the consent RECORDS are correct; they are Mkt6's, and this service asks rather than holds them |
| A model cannot introduce a figure into a message | step 4, the `drafting_groundedness` metric at 1.0 | that the wording is good; a human still reviews the templates |
| Consequential outreach is not sent without a human | step 6, the `review_safety` metric at 1.0 | that a reviewer acted; the queue shows submitted, not reviewed |
| The audit record is tamper-evident and portable | steps 7 and 8, `make portability` | tamper-PROOF: file access beats any store |
| Every port is swappable and every seam is named | step 9, `make portability` | that an on-premises deployment exists, or model or infrastructure portability |

## The UI

```bash
make ui-install && make ui-dev     # http://localhost:3000, proxying to the service
```

Worth showing only if the audience cares about embedding. The point is not the screen: it is that
the browser never asserts who the user is, the service credential never leaves the server, and
framing and CORS are per-tenant allowlists that refuse a wildcard. See `ui/README.md`.

## Managed profile (gcp)

Set `OUTREACH_PROFILE=gcp` and install the `[gcp]` extra; identity becomes
the platform's signed assertion and audit becomes the Cloud Logging WORM sink. This is NOT part
of the offline demo and needs a real project. See `docs/runbook.md`.
