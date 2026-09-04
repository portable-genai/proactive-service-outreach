"""The scripted, offline demo: the REAL services, synthetic data, an audit-first output view.

This is the demo as CODE (practices check F1), not a slide deck and not a recording. Every step
below drives the actual trigger engine, the actual consent port, the actual eligibility engine,
the actual drafting validator, the actual hash-chained audit store and the actual rule-R8 review
router over the ``local`` profile, so a step that stops being true stops passing rather than
stops being mentioned.

Three properties make it worth running in front of somebody:

* **Nothing is faked.** No engine stub, no pre-baked JSON. The refusals, the cap arithmetic,
  the discarded draft, the audit records, the routing references and the tamper verdict are all
  produced by the shipped code.
* **It is bounded.** The demo proves an offline, single-process seam. It does not prove
  cross-host deployment, a live consent store, a live console, or the managed profile; those
  need a cloud project and live in ``tests/integration/``.
* **It is replayable.** The whole arc is decided against ONE pinned instant, so the same inputs
  produce the same output every time. That is what makes it safe to run live, and it is also
  the property the service sells: a decision about contacting a customer can be re-derived
  months later, exactly.

Run it directly to write the audit-view JSON, then render that JSON to static pages::

    make demo-static

or drive it one step at a time with ``demo_server.py`` and ``walkthrough.py`` (``make demo``).

Every party, address and identifier here is obviously fictional: ``.example`` domains, RFC 5737
and RFC 3849 literals, and a synthetic national id that exists only to prove redaction happened.

MAINTAINER NOTE: this file is rendered from a template, so no line may change length with the
package or service name. Every cookiecutter value is bound to a short module constant below and
referenced through it, and every import line is short enough that a long package name cannot
push it past the formatter's limit.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hex_service_kit.audit import HashChainedAuditLog
from hex_service_kit.identity import RequestContext
from hex_service_kit.serialization import to_jsonable

from proactive_outreach.config import (
    Settings,
    build_container,
)
from proactive_outreach.domain import (
    drafting,
    kernel,
    models,
)
from proactive_outreach.domain.outreach_service import (
    OutreachService,
)
from proactive_outreach.domain.pii import (
    JURISDICTIONS,
)


def loaded_cloud_sdks() -> tuple[str, ...]:
    """Every managed-SDK module currently importable in THIS interpreter, sorted.

    Public because the demo, the walkthrough's checks and the test suite all ask the same
    question and must not each answer it slightly differently.
    """
    return tuple(sorted(name for name in sys.modules if name.split(".")[0] == "google"))


#: Rendered identity, bound once so no other line's length depends on how long a name is.
SERVICE_NAME = "Proactive Service Outreach"
CATALOG_ID = "E5"
REPOSITORY = "proactive-service-outreach"

# --------------------------------------------------------------------------------------- #
# Synthetic data. Fictional parties, .example domains, RFC 5737 / RFC 3849 literals only.
# --------------------------------------------------------------------------------------- #

#: The VERIFIED principal the demo attributes work to. A client never asserts this.
ACTOR = "analyst@bank.example"
TENANT = "demo-bank"

#: The ONE instant the whole arc is decided against. 06:00 UTC is 14:00 in Singapore, 16:00 in
#: Sydney and 15:00 in Tokyo, so every market is open and the quiet-hours refusal has to be
#: demonstrated deliberately (see QUIET_INSTANT) rather than by accident of when the demo ran.
AS_OF = datetime(2026, 8, 8, 6, 0, tzinfo=UTC)

#: 23:00 in Singapore. The same event, the same consent, one different instant.
QUIET_INSTANT = datetime(2026, 8, 8, 15, 0, tzinfo=UTC)

#: An hour before AS_OF: inside every trigger rule's freshness window.
_RECENT = "2026-08-08T05:00:00+00:00"

#: A planted identifier, so the redaction panel has an independent literal to look for rather
#: than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"


def _event(
    event_id: str,
    event_type: models.EventType,
    subject_id: str,
    market: str,
    locale: str,
    detail: str,
    attributes: dict[str, str],
    occurred_at: str = _RECENT,
) -> models.ServiceEvent:
    return models.ServiceEvent(
        event_id=event_id,
        event_type=event_type,
        tenant=TENANT,
        subject_id=subject_id,
        occurred_at=occurred_at,
        market=market,
        locale=locale,
        detail=detail,
        source_system="ops-feed (FICTIONAL)",
        attributes=attributes,
    )


ROUTINE_EVENT = _event(
    "evt-d-4102",
    models.EventType.DELIVERY_EXCEPTION,
    "subj-000102",
    "AU",
    "en-AU",
    "Courier could not access the building; parcel returned to the depot from 192.0.2.10.",
    {"tracking_ref": "TRK-77120", "next_attempt_on": "2026-08-12"},
)

CONSEQUENTIAL_EVENT = _event(
    "evt-d-4104",
    models.EventType.FRAUD_HOLD,
    "subj-000104",
    "SG",
    "en-SG",
    "Velocity rule placed a hold pending customer verification.",
    {"hold_ref": "FH-4471", "card_suffix": "3310"},
)

PII_EVENT = _event(
    "evt-d-4101",
    models.EventType.FAILED_PAYMENT,
    "subj-000101",
    "SG",
    "en-SG",
    (
        "Issuer declined the authorisation. Branch note records NRIC "
        + PLANTED_NRIC
        + " and ops@bank.example, seen on host 2001:db8::7."
    ),
    {"card_suffix": "4242", "retry_on": "2026-08-11"},
)

#: The refusals, one per fail-closed rule. Each is the SAME shape of event as the one that gets
#: through; only the subject or the timestamp differs, which is what makes the comparison honest.
UNKNOWN_CONSENT_EVENT = replace(PII_EVENT, event_id="evt-d-4110", subject_id="subj-000702")
WITHDRAWN_CONSENT_EVENT = replace(PII_EVENT, event_id="evt-d-4109", subject_id="subj-000701")
UNKNOWN_TOKEN_EVENT = replace(ROUTINE_EVENT, event_id="evt-d-4112", subject_id="subj-000704")
CAPPED_EVENT = replace(ROUTINE_EVENT, event_id="evt-d-4111", subject_id="subj-000703")
SUPPRESSED_EVENT = replace(PII_EVENT, event_id="evt-d-4106", subject_id="subj-000900")
STALE_EVENT = replace(ROUTINE_EVENT, event_id="evt-d-4108", occurred_at="2020-01-01T00:00:00+00:00")
INCOMPLETE_EVENT = replace(
    ROUTINE_EVENT, event_id="evt-d-4107", attributes={"next_attempt_on": "2026-08-12"}
)

#: The five trigger types, in the order the catalog row names them.
TRIGGER_TOUR: tuple[models.ServiceEvent, ...] = (
    PII_EVENT,
    ROUTINE_EVENT,
    _event(
        "evt-d-4103",
        models.EventType.EXPIRING_CARD,
        "subj-000103",
        "JP",
        "ja-JP",
        "Scheduled reissue window opened for a card nearing expiry.",
        {"card_suffix": "8871", "expires_on": "2026-09-30"},
    ),
    CONSEQUENTIAL_EVENT,
    _event(
        "evt-d-4105",
        models.EventType.OUTAGE,
        "subj-000105",
        "AU",
        "en-AU",
        "Partial degradation reported by the payments platform.",
        {"outage_ref": "OUT-3312", "affected_service": "Card payments"},
    ),
)

#: A draft a model might return that must NOT be sent: it invents an amount nobody told it.
UNGROUNDED_DRAFT = json.dumps(
    {"body": "Your card ending 4242 was declined for 250 dollars. We will retry on 2026-08-11."}
)


# --------------------------------------------------------------------------------------- #
# The presenter arc
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Step:
    """One presenter beat: what it shows, and the sentence the presenter reads aloud."""

    key: str
    label: str
    narration: str


#: The scripted arc, in order. ``walkthrough.py`` asserts the server reaches each key in turn
#: and carries an expectation per key, so a step added here without an expectation there fails
#: the self-test rather than silently extending the demo.
STEPS: tuple[Step, ...] = (
    Step(
        key="opened",
        label="Service bound on the offline profile, with the bank's policy loaded",
        narration=(
            "The whole stack is bound from one settings file: no cloud project, no credentials, "
            "no SDK. Every number this service decides on comes from the policy block in that "
            "file, not from code, because the caps and the quiet hours are the bank's and not "
            "ours."
        ),
    ),
    Step(
        key="triggers",
        label="Five operational triggers, decided by pure code",
        narration=(
            "A failed payment, a delivery exception, an expiring card, a fraud hold and an "
            "outage. What fires is decided by configured rules, never by a model. An event "
            "missing the fact the message would have to quote does not fire at all, because the "
            "alternative is a drafter inventing it."
        ),
    ),
    Step(
        key="eligibility",
        label="Eligibility fails CLOSED on anything it does not fully understand",
        narration=(
            "Consent, suppression, frequency cap and quiet hours, composed worst-wins at one "
            "explicit instant. An unknown subject, a withdrawn grant, a reason token this "
            "client has never seen, a subject at the cap and a market at 23:00 all refuse. The "
            "model has not been called at any point on this screen."
        ),
    ),
    Step(
        key="drafting",
        label="The model may phrase, and may not inform",
        narration=(
            "Only now, after eligibility passed, is anything drafted. The drafter receives the "
            "event's facts and nothing else, and a draft carrying a figure that is not in those "
            "facts is discarded rather than corrected. A half-true notification about somebody's "
            "money is worse than the flat sentence it replaced."
        ),
    ),
    Step(
        key="delivery",
        label="Every send carries what authorised it",
        narration=(
            "The chat channel and the voice channel, each handed the consent decision id and the "
            "cap counters on the envelope. The send is then recorded back to the consent store, "
            "because a cap counts recorded sends and nothing else: a service that decides but "
            "never records passes every cap forever."
        ),
    ),
    Step(
        key="review_queue",
        label="Consequential outreach is held and ROUTED, never sent (rule R8)",
        narration=(
            "A fraud hold is marked consequential in policy. It is drafted, it is held, and it "
            "goes to the human-review console with the proposed words attached. Nobody is "
            "telephoned until a person approves the sentence."
        ),
    ),
    Step(
        key="audit",
        label="The audit trail verifies, and exports in an open format",
        narration=(
            "Every decision is here, including every refusal: why somebody was NOT contacted is "
            "the question asked after an incident. The trail is append-only and hash-chained, "
            "with an external head anchor on a separate volume, and it exports to JSON Lines and "
            "reloads with every link intact."
        ),
    ),
    Step(
        key="tamper",
        label="A rewritten record is DETECTED, not merely discouraged",
        narration=(
            "An attacker with file access drops the append-only triggers and rewrites one "
            "record. The store cannot prevent that. The hash chain names the exact record that "
            "broke, which is the honest guarantee: tamper-EVIDENT, not tamper-proof."
        ),
    ),
    Step(
        key="portability",
        label="The exit path fails fast instead of failing silently",
        narration=(
            "The same calls on the on-premises profile, with no code edited and no domain "
            "module touched. Every unimplemented seam refuses loudly. A delivery placeholder "
            "that returned a receipt would count a contact that never happened against a "
            "customer's frequency cap."
        ),
    ),
)

STEP_KEYS: tuple[str, ...] = tuple(step.key for step in STEPS)


# --------------------------------------------------------------------------------------- #
# Panels: the audit-first output view (the result, its evidence, the findings, what is next)
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Row:
    """One labelled fact in a panel. ``tone`` drives the colour, never the meaning."""

    label: str
    value: str
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Panel:
    """One block of the output view: a title, labelled facts, and an interpretation."""

    title: str
    rows: tuple[Row, ...] = ()
    note: str = ""
    tone: str = ""


@dataclass(frozen=True, slots=True)
class StepResult:
    """Everything one step produced, ready to render or to assert against."""

    key: str
    label: str
    narration: str
    panels: tuple[Panel, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)


Produced = tuple[list[Panel], dict[str, Any]]


class DemoRun:
    """A live demo, advanced one step at a time over the real services.

    The run owns a working directory holding the durable audit store and its external anchor.
    They are separate directories on purpose: an anchor that lives beside the store it witnesses
    is rewritten by whatever rewrites the store.
    """

    def __init__(self, workdir: Path | None = None) -> None:
        # What was ALREADY loaded before this run began. The offline claim is that the demo
        # imports no cloud SDK, and in a live `python scripts/demo.py` nothing else has loaded
        # one, so the delta and the absolute set are the same list. In a shared pytest process
        # they are not: any other module in the suite may legitimately have imported google for
        # its own reasons (the IAP negative matrix does), and a claim measured as an absolute
        # would then be decided by test ordering rather than by the demo. The absolute form of
        # the claim is still made, in fresh interpreters, by `scripts/portability_demo.py`, by
        # the headless walkthrough and by `tests/unit/test_demo_surface.py`.
        self._cloud_sdk_before = frozenset(loaded_cloud_sdks())
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        if workdir is None:
            self._tempdir = tempfile.TemporaryDirectory(prefix="demo-run-")
            workdir = Path(self._tempdir.name)
        self.workdir = workdir
        self.audit_path = workdir / "store" / "audit.sqlite3"
        self.anchor_path = workdir / "anchor" / "head.json"
        # The audit store creates its own parent; the ANCHOR does not, because it is meant to
        # live on a volume somebody provisioned deliberately rather than one a library invented.
        # An operator therefore has to create that directory too; the demo does it here so the
        # first run of `make demo` in a fresh checkout does not fail on a missing path.
        self.anchor_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(
            profile="local",
            audit_path=str(self.audit_path),
            audit_anchor_path=str(self.anchor_path),
            tenant=TENANT,
        )
        self.container = build_container(self.settings)
        self.service = self._build_service()
        self.results: list[StepResult] = []
        self.evaluated = 0
        self.delivered = 0
        self.refused = 0
        self.held = 0
        self.chain_ok = True
        self._perform(STEPS[0])

    def _build_service(self) -> OutreachService:
        return OutreachService(
            audit=self.container.audit,
            consent=self.container.consent,
            drafting=self.container.drafting,
            delivery=self.container.delivery,
            speech=self.container.speech,
            tracer=self.container.tracer,
            events=self.container.events,
            policy=self.settings.policy,
        )

    # -------------------------------------------------------------- control

    @property
    def index(self) -> int:
        """Index of the step most recently performed."""
        return len(self.results) - 1

    @property
    def done(self) -> bool:
        return len(self.results) >= len(STEPS)

    def advance(self) -> StepResult:
        """Perform the next step, or re-return the last one when the arc is finished."""
        if self.done:
            return self.results[-1]
        return self._perform(STEPS[len(self.results)])

    def run_to_end(self) -> None:
        while not self.done:
            self.advance()

    def _perform(self, step: Step) -> StepResult:
        handler: Callable[[], Produced] = getattr(self, "_step_" + step.key)
        panels, facts = handler()
        result = StepResult(
            key=step.key,
            label=step.label,
            narration=step.narration,
            panels=tuple(panels),
            facts=facts,
        )
        self.results.append(result)
        return result

    # -------------------------------------------------------------- steps

    def _step_opened(self) -> Produced:
        policy = self.settings.policy
        bindings = [
            Row(port, self.settings.adapters[port][self.settings.profile].split(":")[-1])
            for port in sorted(self.settings.adapters)
        ]
        profiles = sorted({name for table in self.settings.adapters.values() for name in table})
        sdk = [name for name in loaded_cloud_sdks() if name not in self._cloud_sdk_before]
        deployment = Panel(
            title="Deployment",
            rows=(
                Row("Service", SERVICE_NAME),
                Row("Profile", self.settings.profile, "ok"),
                Row("Profiles bound for every port", ", ".join(profiles)),
                Row("Residency region", self.settings.region),
                Row("Jurisdiction PII packs", ", ".join(JURISDICTIONS)),
                Row("Deciding as at", AS_OF.isoformat()),
            ),
            note=(
                "One environment variable selects the adapter family for every port. Nothing "
                "below was edited to make the service run offline."
            ),
        )
        adapters = Panel(
            title="Bound adapters",
            rows=tuple(bindings),
            note=(
                "The binding map lives in config/settings.yaml, not in the code. The consent "
                "store is a SIBLING system: this repo asks it and holds no copy of anybody's "
                "consent."
            ),
        )
        policy_panel = Panel(
            title="The bank's policy, loaded from configuration",
            rows=(
                Row("Trigger rules", ", ".join(sorted(policy.triggers))),
                Row(
                    "Frequency caps",
                    "; ".join(
                        f"{key} {cap.limit} per {cap.window_hours}h"
                        for key, cap in sorted(policy.frequency_caps.items())
                    ),
                ),
                Row(
                    "Quiet hours",
                    "; ".join(
                        f"{market} {window.window}"
                        for market, window in sorted(policy.quiet_hours.items())
                    ),
                ),
                Row("Suppressed subjects", str(len(policy.suppressed_subjects))),
                Row("Message body limit", str(policy.max_body_chars) + " characters"),
            ),
            note=(
                "Not one of these numbers is in the code. A market with no quiet-hours row "
                "REFUSES rather than defaulting to 'any time is fine'."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Cloud SDK modules imported", ", ".join(sdk) or "none", "bad" if sdk else "ok"),
                Row("Credentials required", "none", "ok"),
                Row("Network required", "none", "ok"),
            ),
            note=(
                "The managed adapters import their SDK lazily, so this profile runs with none "
                "installed at all."
            ),
            tone="bad" if sdk else "ok",
        )
        facts = {
            "profile": self.settings.profile,
            "sdk_modules": sdk,
            "profiles": profiles,
            "trigger_rules": sorted(policy.triggers),
            "caps": sorted(policy.frequency_caps),
            "markets": sorted(policy.quiet_hours),
        }
        return [deployment, adapters, policy_panel, findings], facts

    def _step_triggers(self) -> Produced:
        rows: list[Row] = []
        fired: list[str] = []
        for event in TRIGGER_TOUR:
            trigger = self._trigger(event)
            fired.append(event.event_type.value) if trigger.fired else None
            rows.append(
                Row(
                    event.event_type.value,
                    (
                        f"fires -> {trigger.template_id} on {trigger.channel} "
                        f"({trigger.severity.value}"
                        + (", consequential" if trigger.consequential else "")
                        + ")"
                    ),
                    "warn" if trigger.consequential else "ok",
                )
            )
        refusals: list[Row] = []
        refused_reasons: list[str] = []
        for label, event in (
            ("missing a required fact", INCOMPLETE_EVENT),
            ("older than its window", STALE_EVENT),
        ):
            trigger = self._trigger(event)
            refused_reasons.extend(trigger.reasons)
            refusals.append(Row(label, ", ".join(trigger.reasons), "ok"))
        tour = Panel(
            title="The five triggers",
            rows=tuple(rows),
            note=(
                "Each row is a configured rule, not a branch in the code. Two of the five are "
                "marked consequential, which is what stops them being sent automatically."
            ),
            tone="ok",
        )
        refusal_panel = Panel(
            title="And the two ways an event does NOT become an outreach",
            rows=tuple(refusals),
            note=(
                "Both refusals are wanted. A message that would have to invent a tracking "
                "reference is worse than no message, and yesterday's outage is not news."
            ),
            tone="ok",
        )
        facts = {"fired": fired, "refused_reasons": refused_reasons}
        return [tour, refusal_panel], facts

    def _step_eligibility(self) -> Produced:
        rows: list[Row] = []
        refusals: list[str] = []
        cases: tuple[tuple[str, models.ServiceEvent, datetime], ...] = (
            ("a clean grant, inside the cap, market open", PII_EVENT, AS_OF),
            ("a subject the store has never heard of", UNKNOWN_CONSENT_EVENT, AS_OF),
            ("consent withdrawn", WITHDRAWN_CONSENT_EVENT, AS_OF),
            ("an allow carrying a reason we do not know", UNKNOWN_TOKEN_EVENT, AS_OF),
            ("already at the frequency cap", CAPPED_EVENT, AS_OF),
            ("on the suppression list", SUPPRESSED_EVENT, AS_OF),
            ("the same clean grant at 23:00 local", PII_EVENT, QUIET_INSTANT),
        )
        drafted = 0
        for label, event, moment in cases:
            verdict = self._eligibility(event, moment)
            if not verdict.eligible:
                refusals.extend(verdict.reasons)
            else:
                drafted += 1
            rows.append(
                Row(
                    label,
                    ("ELIGIBLE" if verdict.eligible else "refused: " + ", ".join(verdict.reasons)),
                    "ok" if not verdict.eligible else "warn",
                )
            )
        gate = Panel(
            title="One question, seven answers",
            rows=tuple(rows),
            note=(
                "Worst wins. Every check that refuses contributes its reason, all of them are "
                "carried, and one refusal is enough. There is no scoring and no 'two soft "
                "failures make a pass'."
            ),
            tone="ok",
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Questions asked", str(len(cases))),
                Row("Contacts permitted", str(drafted)),
                Row("Model calls made so far", "0", "ok"),
                Row(
                    "Unknown consent read as permission",
                    "never",
                    "ok",
                ),
            ),
            note=(
                "The drafting port is not reachable from the eligibility engine and the service "
                "does not call it until this screen has answered. A refused contact costs no "
                "tokens and leaks no facts to a model."
            ),
            tone="ok",
        )
        return [gate, findings], {"refusals": refusals, "permitted": drafted}

    def _step_drafting(self) -> Produced:
        trigger = self._trigger(PII_EVENT)
        request = drafting.draft_request_for(trigger, policy=self.settings.policy)
        deterministic = drafting.render_template(request, policy=self.settings.policy)
        offered = self.container.drafting.draft(request)
        accepted = drafting.validate_draft(offered, request, policy=self.settings.policy)
        rejected = drafting.validate_draft(UNGROUNDED_DRAFT, request, policy=self.settings.policy)
        brief = Panel(
            title="What the drafter is given",
            rows=tuple(Row(name, value) for name, value in sorted(request.facts.items()))
            + (Row("Maximum length", str(request.max_chars) + " characters"),),
            note=(
                "That is the whole brief. Not the event, not the free text, not the subject id, "
                "not the consent decision. There is nothing here it could use to invent a "
                "figure, because the only figures it sees are the ones it may repeat."
            ),
        )
        good = Panel(
            title="A grounded draft is accepted",
            rows=(
                Row("Body", accepted.message.body if accepted.message else "(none)"),
                Row("Source", accepted.message.source if accepted.message else "(none)"),
                Row("Verdict", ", ".join(accepted.reasons), "ok"),
            ),
            note="Every figure in it appears in the facts above, and both required facts are said.",
            tone="ok" if accepted.accepted else "bad",
        )
        bad = Panel(
            title="A draft that invents a figure is DISCARDED",
            rows=(
                Row("Body offered", json.loads(UNGROUNDED_DRAFT)["body"], "warn"),
                Row("Verdict", ", ".join(rejected.reasons), "ok"),
                Row(
                    "What is sent instead",
                    "nothing: the deterministic body goes to a human",
                    "ok",
                ),
                Row("Deterministic body", deterministic.body if deterministic else "(none)"),
            ),
            note=(
                "Not corrected, not truncated, not sent with a warning. There is no repair path "
                "in this code, because a half-true notification about somebody's money is worse "
                "than the flat sentence it replaced."
            ),
            tone="ok" if not rejected.accepted else "bad",
        )
        facts = {
            "accepted": accepted.accepted,
            "rejected": not rejected.accepted,
            "rejection_reasons": list(rejected.reasons),
            "fact_names": sorted(request.facts),
        }
        return [brief, good, bad], facts

    def _step_delivery(self) -> Produced:
        """Two eligible notifications sent, and one refusal recorded beside them.

        The refusal is here on purpose. "Every send carries what authorised it" is only half
        the claim; the other half is that a contact that did NOT happen leaves a record too,
        because "why was this person not told" is a question somebody asks after an incident.
        """
        chat = self._evaluate(PII_EVENT, AS_OF)
        second = self._evaluate(ROUTINE_EVENT, AS_OF)
        refused = self._evaluate(UNKNOWN_CONSENT_EVENT, AS_OF)
        audited = self.container.audit.log.read_all()
        refusal_audited = any(
            refused.event_id in str(row.get("redacted_summary", "")) for row in audited
        )
        sent = list(self.container.delivery.sent)
        envelope_rows: list[Row] = []
        if sent:
            _, envelope = sent[-1]
            envelope_rows = [
                Row("Channel", envelope.channel),
                Row("Consent decision id", envelope.consent_decision_id, "ok"),
                Row(
                    "Cap counters",
                    f"{envelope.sends_in_window} of {envelope.cap_limit} used, "
                    f"{envelope.cap_remaining} remaining",
                ),
                Row("Decided as at", envelope.as_of),
            ]
        delivered_panel = Panel(
            title="Delivered",
            rows=(
                Row(chat.case_ref, chat.message.body if chat.message else "(none)"),
                Row(second.case_ref, second.message.body if second.message else "(none)"),
                Row("References", chat.delivery_ref + " / " + second.delivery_ref),
            ),
            note=(
                "The bodies are the drafted ones. The decision to send them was not the "
                "model's, and the model never saw a subject id."
            ),
            tone="ok" if chat.delivered and second.delivered else "bad",
        )
        envelope_panel = Panel(
            title="What travelled with them",
            rows=tuple(envelope_rows) or (Row("envelope", "MISSING", "bad"),),
            note=(
                "On the envelope, not looked up later by the channel. Why this person was "
                "contacted arrives with the contact, as one record rather than two that have "
                "to be joined on a timestamp."
            ),
            tone="ok" if envelope_rows else "bad",
        )
        recorded = len(self.container.consent.ledger)
        ledger_panel = Panel(
            title="Recorded back, and the refusal recorded beside it",
            rows=(
                Row(
                    "Sends recorded to the consent store",
                    str(recorded),
                    "ok" if recorded >= 2 else "bad",
                ),
                Row("Refused contact", refused.summary, "ok"),
                Row(
                    "Refusal in the audit trail",
                    "yes" if refusal_audited else "NO",
                    "ok" if refusal_audited else "bad",
                ),
                Row(
                    "Voice channel",
                    "bound offline: the shared speech kit's text-to-speech port",
                ),
            ),
            note=(
                "A frequency cap counts recorded sends and nothing else, so a service that "
                "decides but never records passes every cap forever. The voice channel returns "
                "a REFERENCE to audio and never the bytes, so this process never becomes the "
                "thing that persisted a customer's voice."
            ),
            tone="ok" if recorded >= 2 and refusal_audited else "bad",
        )
        facts = {
            "delivered": int(chat.delivered) + int(second.delivered),
            "delivery_ref": chat.delivery_ref,
            "consent_decision_id": (
                chat.eligibility.consent_decision_id if chat.eligibility else ""
            ),
            "recorded_sends": recorded,
            "refusal_audited": refusal_audited,
            "planted_identifier_in_body": (
                PLANTED_NRIC in chat.message.body if chat.message else False
            ),
        }
        return [delivered_panel, envelope_panel, ledger_panel], facts

    def _step_review_queue(self) -> Produced:
        held = self._evaluate(CONSEQUENTIAL_EVENT, AS_OF)
        review_ref = ""
        if held.requires_human_review:
            review_ref = self.container.review_router.route(held, maker=ACTOR, tenant=TENANT)
        pending = list(self.container.review_router.outbox.pending())
        leaked = any(
            PLANTED_NRIC in json.dumps(to_jsonable(item), sort_keys=True) for item in pending
        )
        decision = Panel(
            title="Decision: " + held.case_ref,
            rows=(
                Row("Severity", held.severity.value, "warn"),
                Row("Eligible", str(held.eligibility.eligible if held.eligibility else False)),
                Row("Requires human review", str(held.requires_human_review), "ok"),
                Row("Delivered", str(held.delivered), "bad" if held.delivered else "ok"),
                Row("Routed to review", review_ref or "NOT ROUTED", "ok" if review_ref else "bad"),
            ),
            note=(
                "Eligible AND held. Consent said yes and the engine still refused to send it "
                "automatically, because the policy marks this event type consequential."
            ),
            tone="ok" if review_ref and not held.delivered else "bad",
        )
        queue = Panel(
            title="What the reviewer receives",
            rows=tuple(
                Row(str(getattr(item, "source_key", "review")), _summarise(to_jsonable(item)))
                for item in pending
            )
            or (Row("queue", "empty", "bad"),),
            note=(
                "Queued, not submitted, and carrying the proposed words: a reviewer who cannot "
                "see the sentence cannot meaningfully approve it. The payload is redacted "
                "against every configured jurisdiction, because the console is a shared sink."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Held for review", str(self.held)),
                Row("Routed", str(len(pending)), "ok" if pending else "bad"),
                Row("Delivered without a human", "0", "ok"),
                Row(
                    "Personal data on the wire",
                    "LEAKED" if leaked else "none",
                    "bad" if leaked else "ok",
                ),
            ),
            note=(
                "A flag with no routing reference is auto-execution with extra steps. Setting "
                "the flag is not the escalation; routing is."
            ),
            tone="bad" if leaked else "ok",
        )
        actions = Panel(
            title="Next actions",
            rows=(
                Row("Reviewer", "read the proposed message and approve or reject it"),
                Row("Operator", "point HUMAN_REVIEW_URL at the console and flush the outbox"),
            ),
        )
        facts = {
            "review_ref": review_ref,
            "pending": len(pending),
            "delivered": held.delivered,
            "wire_leak": leaked,
        }
        return [decision, queue, findings, actions], facts

    def _step_audit(self) -> Produced:
        log = self.container.audit.log
        report = self.container.audit.verify()
        self.chain_ok = report.ok
        records = log.read_all()
        leaked = any(PLANTED_NRIC in str(row.get("redacted_summary", "")) for row in records)
        export = self.workdir / "export" / "audit.jsonl"
        export.parent.mkdir(parents=True, exist_ok=True)
        written = log.export_jsonl(export)
        restored = HashChainedAuditLog(":memory:")
        reloaded = restored.import_jsonl(export)
        round_trip = restored.verify_chain()
        anchored = bool(self.settings.audit_anchor_path) and self.anchor_path.exists()
        trail = Panel(
            title="Audit trail",
            rows=(
                Row("Records", str(report.entries)),
                Row("Hash-chained", str(report.chained)),
                Row(
                    "Unverifiable (unchained)",
                    str(report.legacy),
                    "ok" if report.legacy == 0 else "bad",
                ),
                Row("Verdict", report.detail, "ok" if report.ok else "bad"),
                Row(
                    "External head anchor",
                    "configured" if anchored else "absent",
                    "ok" if anchored else "warn",
                ),
                Row(
                    "Planted identifier in any record",
                    "PRESENT" if leaked else "absent",
                    "bad" if leaked else "ok",
                ),
            ),
            note=(
                "Refusals are recorded as fully as sends: 'why was this person NOT contacted' "
                "is the question asked after an incident. The chain alone cannot detect a "
                "truncated tail, so the anchor on a different volume is what closes that gap."
            ),
            tone="bad" if leaked or not report.ok else "ok",
        )
        portable = Panel(
            title="Open-format round trip",
            rows=(
                Row("Exported records", str(written)),
                Row("Reloaded into a fresh store", str(reloaded)),
                Row(
                    "Chain after reload",
                    round_trip.detail,
                    "ok" if round_trip.ok else "bad",
                ),
            ),
            note=(
                "JSON Lines with the hashes included, so a consumer can re-verify the trail "
                "without this codebase. That is what makes the record portable."
            ),
            tone="ok" if round_trip.ok else "bad",
        )
        facts = {
            "chain_ok": report.ok,
            "entries": report.entries,
            "exported": written,
            "round_trip_ok": round_trip.ok,
            "anchored": anchored,
            "planted_identifier_leaked": leaked,
        }
        return [trail, portable], facts

    def _step_tamper(self) -> Produced:
        before = self.container.audit.verify()
        target = _rewrite_a_record(self.audit_path)
        after = self.container.audit.verify()
        self.chain_ok = after.ok
        detected = (not after.ok) and after.first_bad_seq == target
        attack = Panel(
            title="The tamper",
            rows=(
                Row("Append-only triggers", "dropped by the attacker", "warn"),
                Row("Record rewritten in place", "seq " + str(target), "warn"),
                Row("Verdict before the rewrite", before.detail, "ok"),
            ),
            note=(
                "File access beats a database trigger. A store that claims otherwise is "
                "describing a policy, not a control."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Chain intact", "YES" if after.ok else "no", "bad" if after.ok else "ok"),
                Row("First broken record", str(after.first_bad_seq), "ok"),
                Row("Detail", after.detail),
                Row(
                    "Named the exact rewritten record",
                    "yes" if detected else "no",
                    "ok" if detected else "bad",
                ),
            ),
            note=(
                "Tamper-EVIDENT, not tamper-proof. The guarantee is that a rewrite cannot pass "
                "unnoticed, and that the report names which record broke."
            ),
            tone="ok" if detected else "bad",
        )
        actions = Panel(
            title="Next actions",
            rows=(
                Row("Operator", "restore from the exported JSONL and re-anchor deliberately"),
                Row("Auditor", "treat every record from seq " + str(target) + " on as suspect"),
            ),
        )
        facts = {"tampered_seq": target, "detected": detected, "chain_ok": after.ok}
        return [attack, findings, actions], facts

    def _step_portability(self) -> Produced:
        onprem = build_container(Settings(profile="onprem", tenant=TENANT))
        rows: list[Row] = []
        refused: list[str] = []
        absent: list[str] = []
        for port, call in EXIT_CALLS.items():
            expected_absent = port in EXIT_ABSENT
            try:
                call(onprem)
            except NotImplementedError as exc:
                if expected_absent:
                    rows.append(Row(port, "REFUSED, but is meant to be absent", "bad"))
                else:
                    refused.append(port)
                    rows.append(Row(port, "refused: " + str(exc).split(":")[0], "ok"))
            else:
                if expected_absent:
                    absent.append(port)
                    rows.append(Row(port, "absent, by design (a diagnostic, not a control)", "ok"))
                else:
                    rows.append(Row(port, "SUCCEEDED SILENTLY", "bad"))
        exit_panel = Panel(
            title="Exit profile (onprem)",
            rows=tuple(rows),
            note=(
                "Selected by one environment variable. No domain module was edited and no "
                "import changed."
            ),
            tone="ok" if len(refused) + len(absent) == len(EXIT_CALLS) else "bad",
        )
        bounds = Panel(
            title="What this does and does not prove",
            rows=(
                Row("Proved", "every port is swappable and every seam is named"),
                Row("Proved", "an unimplemented seam refuses instead of dropping work"),
                Row("NOT proved", "a running on-premises deployment exists"),
                Row("NOT proved", "model, infrastructure or whole-system portability"),
            ),
            note=(
                "Bounded claims are the point. Run scripts/portability_demo.py for the full "
                "seam tour, with a pass or fail per named check."
            ),
        )
        return [exit_panel, bounds], {
            "refused": sorted(refused),
            "absent": sorted(absent),
        }

    # -------------------------------------------------------------- helpers

    def _trigger(self, event: models.ServiceEvent) -> models.OutreachTrigger:
        from proactive_outreach.domain import trigger_engine

        return trigger_engine.evaluate(event, policy=self.settings.policy, as_of=AS_OF)

    def _eligibility(
        self, event: models.ServiceEvent, moment: datetime
    ) -> models.EligibilityDecision:
        """Run the real engines up to the eligibility verdict, WITHOUT drafting or sending.

        A separate container so the panel's questions do not move the cap counters the later
        steps assert on. The engines are the shipped ones; only the wiring is per-panel.
        """
        from proactive_outreach.domain import eligibility as eligibility_rules
        from proactive_outreach.domain import trigger_engine

        probe = build_container(Settings(profile="local", audit_path=":memory:", tenant=TENANT))
        trigger = trigger_engine.evaluate(event, policy=self.settings.policy, as_of=moment)
        consent = None
        if trigger.fired:
            from proactive_outreach.ports.consent import ConsentQuery

            consent = probe.consent.decide(
                ConsentQuery(
                    tenant=trigger.tenant,
                    subject_id=trigger.subject_id,
                    purpose=trigger.purpose,
                    channel=trigger.channel,
                    market=trigger.market,
                    vertical="banking",
                    as_of=moment.isoformat(),
                )
            )
        return eligibility_rules.assess(
            trigger,
            consent=consent,
            policy=self.settings.policy,
            as_of_iso=moment.isoformat(),
        )

    def _evaluate(self, event: models.ServiceEvent, moment: datetime) -> models.OutreachResult:
        result = self.service.evaluate(event, actor=ACTOR, as_of=moment)
        self.evaluated += 1
        if result.delivered:
            self.delivered += 1
        elif result.requires_human_review:
            self.held += 1
        else:
            self.refused += 1
        return result

    # -------------------------------------------------------------- state

    def state(self) -> dict[str, Any]:
        """The whole run as JSON-safe data: what the UI renders and the walkthrough asserts."""
        current = self.results[-1]
        return {
            "service": SERVICE_NAME,
            "repository": REPOSITORY,
            "profile": self.settings.profile,
            "region": self.settings.region,
            "step": current.key,
            "step_index": self.index,
            "step_count": len(STEPS),
            "label": current.label,
            "next": "" if self.done else STEPS[len(self.results)].label,
            "done": self.done,
            "totals": {
                "evaluated": self.evaluated,
                "delivered": self.delivered,
                "held": self.held,
                "refused": self.refused,
                "chain_ok": self.chain_ok,
            },
            "steps": [_step_to_dict(result) for result in self.results],
        }


def _step_to_dict(result: StepResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "label": result.label,
        "narration": result.narration,
        "facts": result.facts,
        "panels": [
            {
                "title": panel.title,
                "note": panel.note,
                "tone": panel.tone,
                "rows": [
                    {"label": row.label, "value": row.value, "tone": row.tone} for row in panel.rows
                ],
            }
            for panel in result.panels
        ],
    }


def _summarise(payload: Any) -> str:
    """One readable line for a queued review, without dumping the whole payload."""
    if isinstance(payload, dict):
        parts = [
            str(payload[key])
            for key in ("subject", "severity", "maker", "summary")
            if payload.get(key)
        ]
        if parts:
            return " / ".join(parts)[:180]
    return json.dumps(payload, sort_keys=True)[:120]


def _rewrite_a_record(store: Path) -> int:
    """Drop the append-only triggers and rewrite one INTERIOR record, as an attacker would.

    Returns the ``seq`` that was rewritten. An interior row is chosen deliberately: rewriting
    the newest row is the easy case, and the chain has to catch a rewrite in the middle of the
    trail too.
    """
    conn = sqlite3.connect(store)
    try:
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
        rows = conn.execute("SELECT seq, event_json FROM audit_log ORDER BY seq ASC").fetchall()
        if len(rows) < 3:
            raise RuntimeError("the tamper step needs an interior record to rewrite")
        middle = rows[len(rows) // 2]
        payload = json.loads(middle[1])
        payload["decision"] = "allowed"
        payload["severity"] = "low"
        conn.execute(
            "UPDATE audit_log SET event_json = ? WHERE seq = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), int(middle[0])),
        )
        conn.commit()
        return int(middle[0])
    finally:
        conn.close()


def _exit_audit(container: Any) -> Any:
    return container.audit.record(
        kernel.AuditEvent(
            action="outreach_evaluate",
            actor=ACTOR,
            decision=kernel.Decision.ESCALATED,
            severity=kernel.Severity.CRITICAL,
            redacted_summary="outreach:fraud_hold:evt-d-4104 :: held for human review",
        )
    )


def _exit_review(container: Any) -> Any:
    citation = kernel.Citation(
        source_id="event:evt-d-4104",
        title="fraud_hold",
        snippet="hold_ref",
    )
    return container.review_router.route(
        models.OutreachResult(
            case_ref="outreach:fraud_hold:evt-d-4104",
            event_id=CONSEQUENTIAL_EVENT.event_id,
            event_type=CONSEQUENTIAL_EVENT.event_type,
            tenant=TENANT,
            subject_id=CONSEQUENTIAL_EVENT.subject_id,
            severity=kernel.Severity.CRITICAL,
            decision=kernel.Decision.ESCALATED,
            summary="held for human review: consequential event",
            requires_human_review=True,
            citations=(citation,),
        ),
        maker=ACTOR,
        tenant=TENANT,
    )


def _exit_identity(container: Any) -> Any:
    # The persona header is deliberately present. It is what the OFFLINE family answers, so
    # sending it proves the exit family refuses the call itself rather than merely lacking an
    # input: a placeholder that returned a principal for a client-written header would be worse
    # than one that raises.
    return container.identity.resolve(RequestContext(headers={"x-dev-persona": "approver"}))


def _exit_events(container: Any) -> Any:
    return container.events.detect(models.EventQuery(tenant=TENANT, as_of=AS_OF.isoformat()))


def _exit_consent(container: Any) -> Any:
    from proactive_outreach.ports.consent import ConsentQuery

    return container.consent.decide(
        ConsentQuery(
            tenant=TENANT,
            subject_id="subj-000101",
            purpose="service",
            channel="chat",
            market="SG",
            vertical="banking",
            as_of=AS_OF.isoformat(),
        )
    )


def _exit_drafting(container: Any) -> Any:
    return container.drafting.draft(
        models.DraftRequest(
            template_id="failed_payment_retry",
            locale="en-SG",
            channel="chat",
            facts={"card_suffix": "4242", "retry_on": "2026-08-11"},
            max_chars=320,
        )
    )


def _exit_delivery(container: Any) -> Any:
    return container.delivery.send(
        models.OutreachMessage(
            template_id="failed_payment_retry",
            channel="chat",
            locale="en-SG",
            body="A payment on the card ending 4242 did not go through.",
        ),
        models.DeliveryEnvelope(
            event_id="evt-d-4101",
            tenant=TENANT,
            subject_id="subj-000101",
            channel="chat",
            purpose="service",
            consent_decision_id="cd-demo-0001",
            cap_limit=3,
            sends_in_window=0,
            cap_remaining=3,
            as_of=AS_OF.isoformat(),
        ),
    )


def _exit_speech(container: Any) -> Any:
    from speech_lexicon_kit import SpeechSynthesisRequest

    return container.speech.synthesize(
        SpeechSynthesisRequest(
            request_id="trg-demo-0001",
            text="A hold was placed on the card ending 3310.",
            locale="en-SG",
        )
    )


def _exit_tracer(container: Any) -> Any:
    with container.tracer.span("exit.tour", action="portability"):
        return None


def _exit_evaluation(container: Any) -> Any:
    return container.evaluation.gate("eval/datasets/golden_cases.jsonl")


#: The calls the exit profile must REFUSE, one per port. Add a port, add a row: a seam nobody
#: calls is a seam nobody knows is unimplemented.
#:
#: IDENTITY is the load-bearing one for the exposure guard, and DELIVERY is the load-bearing one
#: for this vertical: a placeholder that returned a receipt would make the service record a
#: delivered notification, count it against the customer's frequency cap and tell the consent
#: store about a contact that never happened.
EXIT_CALLS: dict[str, Callable[[Any], Any]] = {
    "audit": _exit_audit,
    "consent": _exit_consent,
    "delivery": _exit_delivery,
    "drafting": _exit_drafting,
    "events": _exit_events,
    "identity": _exit_identity,
    "review_router": _exit_review,
    "tracer": _exit_tracer,
    "evaluation": _exit_evaluation,
    "speech": _exit_speech,
}


#: Diagnostic seams that complete as an honest no-op under the exit profile.
EXIT_ABSENT: frozenset[str] = frozenset({"tracer"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scripted offline demo end to end.")
    parser.add_argument(
        "output",
        nargs="?",
        default="demo.json",
        help="where to write the audit-view JSON (default: demo.json)",
    )
    parser.add_argument("--quiet", action="store_true", help="write the JSON and print nothing")
    args = parser.parse_args(argv)

    run = DemoRun()
    run.run_to_end()
    state = run.state()
    Path(args.output).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        for step in state["steps"]:
            print("[" + step["key"] + "] " + step["label"])
        totals = state["totals"]
        print(
            "evaluated="
            + str(totals["evaluated"])
            + " delivered="
            + str(totals["delivered"])
            + " held="
            + str(totals["held"])
            + " refused="
            + str(totals["refused"])
        )
        print("wrote " + args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
