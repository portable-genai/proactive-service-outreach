"""The bank's policy, as frozen data loaded from configuration rather than module constants.

Every number a decision turns on lives here: which events are worth contacting a customer
about, how severe each one is, how often a subject may be contacted on a channel, when a market
is quiet, which events are consequential enough that nothing goes out without a human, and how
long a body may be. None of it is this codebase's opinion. It is the client's policy, so it is
configuration (the ``policy:`` block of ``config/settings.yaml``) and this module is only its
shape, its validation and its fail-closed accessors.

The shipped :data:`DEFAULT_POLICY` is a synthetic reference set, good enough to demo and to run
the offline gate against, and it is what a deployment overrides. It is not advice.

Fail closed, twice over
-----------------------
1. **Loading.** A ``policy:`` block that is present but malformed RAISES at load, so a typo in
   a cap is a boot failure rather than a silently absent cap. A section that is present and
   EMPTY is honoured as empty, which means "nothing is configured here", and the accessors
   below turn that into a refusal rather than into a default.
2. **Reading.** :meth:`OutreachPolicy.cap_for` and :meth:`OutreachPolicy.quiet_hours_for`
   return ``None`` when nothing is configured for the key asked about, and the eligibility
   engine denies on ``None``. An unconfigured requirement is a gap, never a pass: the opposite
   convention is how a market nobody wrote a quiet-hours row for gets called at 03:00.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .kernel import Severity
from .models import DELIVERABLE_CHANNELS, EventType


class PolicyError(ValueError):
    """Raised when the configured policy is malformed. Never swallowed into a default."""


def _int(block: Mapping[str, Any], key: str, where: str) -> int:
    raw = block.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise PolicyError(f"policy.{where}.{key} must be an integer, got {raw!r}")
    return raw


@dataclass(frozen=True, slots=True)
class QuietHours:
    """The local window in which a market does not accept service outreach.

    The offset is carried explicitly rather than resolved from a timezone database, because a
    decision that depends on which tzdata release the host happens to ship is not replayable,
    and replayability is the property the whole engine is built on. A deployment that needs
    daylight saving configures the offset it is operating under.
    """

    start_hour: int
    end_hour: int
    utc_offset_minutes: int

    def __post_init__(self) -> None:
        for name, value in (("start_hour", self.start_hour), ("end_hour", self.end_hour)):
            if not 0 <= value <= 23:
                raise PolicyError(f"quiet_hours.{name} must be an hour 0..23, got {value}")
        if not -720 <= self.utc_offset_minutes <= 840:
            raise PolicyError(
                f"quiet_hours.utc_offset_minutes is out of range: {self.utc_offset_minutes}"
            )

    @property
    def window(self) -> str:
        """The window as a label, for a citation and for the reviewer's screen."""
        return f"{self.start_hour:02d}:00-{self.end_hour:02d}:00 (UTC{self.utc_offset_minutes:+d}m)"

    def local_hour(self, as_of: datetime) -> int:
        """The market-local hour at ``as_of``, from the explicit offset."""
        return (as_of.astimezone(UTC) + timedelta(minutes=self.utc_offset_minutes)).hour

    def contains(self, as_of: datetime) -> bool:
        """Is ``as_of`` inside the quiet window? Start is inclusive, end exclusive.

        A window whose start is after its end wraps midnight, which is the normal case: 21:00
        to 08:00 is one window, not two, and writing it as two rows is how the small hours end
        up uncovered.
        """
        hour = self.local_hour(as_of)
        if self.start_hour == self.end_hour:
            return False
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour

    @classmethod
    def from_mapping(cls, data: Any, market: str) -> QuietHours:
        if not isinstance(data, dict):
            raise PolicyError(f"policy.quiet_hours.{market} must be a mapping, got {data!r}")
        where = f"quiet_hours.{market}"
        return cls(
            start_hour=_int(data, "start_hour", where),
            end_hour=_int(data, "end_hour", where),
            utc_offset_minutes=_int(data, "utc_offset_minutes", where),
        )


@dataclass(frozen=True, slots=True)
class FrequencyCap:
    """How many contacts a subject may receive on one purpose and channel, per window."""

    limit: int
    window_hours: int

    def __post_init__(self) -> None:
        if self.limit < 0:
            raise PolicyError(f"frequency cap limit must be >= 0, got {self.limit}")
        if self.window_hours <= 0:
            raise PolicyError(f"frequency cap window_hours must be > 0, got {self.window_hours}")

    @classmethod
    def from_mapping(cls, data: Any, key: str) -> FrequencyCap:
        if not isinstance(data, dict):
            raise PolicyError(f"policy.frequency_caps.{key} must be a mapping, got {data!r}")
        where = f"frequency_caps.{key}"
        return cls(limit=_int(data, "limit", where), window_hours=_int(data, "window_hours", where))


@dataclass(frozen=True, slots=True)
class TriggerRule:
    """When one event type becomes an outreach, and what that outreach is.

    ``required_attributes`` is the fail-closed half: an event missing a fact the message has to
    quote does not fire at all, because the alternative is a drafter inventing the fact.
    """

    event_type: EventType
    template_id: str
    purpose: str
    channel: str
    resolution_path: str
    severity: Severity
    max_age_hours: int
    required_attributes: tuple[str, ...] = ()
    consequential: bool = False

    def __post_init__(self) -> None:
        if self.channel not in DELIVERABLE_CHANNELS:
            raise PolicyError(
                f"policy.triggers.{self.event_type.value}.channel {self.channel!r} is not a "
                f"channel this service delivers on ({sorted(DELIVERABLE_CHANNELS)})"
            )
        if self.max_age_hours <= 0:
            raise PolicyError(f"policy.triggers.{self.event_type.value}.max_age_hours must be > 0")
        if not self.template_id.strip():
            raise PolicyError(f"policy.triggers.{self.event_type.value}.template_id is empty")

    @classmethod
    def from_mapping(cls, data: Any, key: str) -> TriggerRule:
        if not isinstance(data, dict):
            raise PolicyError(f"policy.triggers.{key} must be a mapping, got {data!r}")
        where = f"triggers.{key}"
        try:
            event_type = EventType(key)
        except ValueError as exc:
            raise PolicyError(f"policy.triggers.{key} is not a known event type") from exc
        severity_raw = str(data.get("severity", "") or "")
        try:
            severity = Severity(severity_raw)
        except ValueError as exc:
            raise PolicyError(f"policy.{where}.severity {severity_raw!r} is not a band") from exc
        required = data.get("required_attributes") or ()
        if not isinstance(required, list | tuple):
            raise PolicyError(f"policy.{where}.required_attributes must be a list")
        return cls(
            event_type=event_type,
            template_id=str(data.get("template_id", "") or ""),
            purpose=str(data.get("purpose", "") or ""),
            channel=str(data.get("channel", "") or ""),
            resolution_path=str(data.get("resolution_path", "") or ""),
            severity=severity,
            max_age_hours=_int(data, "max_age_hours", where),
            required_attributes=tuple(str(name) for name in required),
            consequential=bool(data.get("consequential", False)),
        )


@dataclass(frozen=True, slots=True)
class OutreachPolicy:
    """The whole configured policy, frozen, with fail-closed lookups."""

    triggers: Mapping[str, TriggerRule]
    frequency_caps: Mapping[str, FrequencyCap]
    quiet_hours: Mapping[str, QuietHours]
    templates: Mapping[str, str]
    suppressed_subjects: frozenset[str]
    banned_phrases: tuple[str, ...]
    max_body_chars: int

    # ---------------------------------------------------------------- lookups
    def trigger_for(self, event_type: EventType) -> TriggerRule | None:
        """The rule for one event type, or ``None`` when nobody configured one."""
        return self.triggers.get(event_type.value)

    @staticmethod
    def cap_key(purpose: str, channel: str) -> str:
        """The composite key a cap is configured under. One place, so the two never disagree."""
        return f"{purpose}:{channel}"

    def cap_for(self, purpose: str, channel: str) -> FrequencyCap | None:
        """The cap for one purpose and channel, or ``None``: an unconfigured cap is a gap."""
        return self.frequency_caps.get(self.cap_key(purpose, channel))

    def quiet_hours_for(self, market: str) -> QuietHours | None:
        """The quiet window for one market, or ``None``: an unconfigured market is a gap."""
        return self.quiet_hours.get(market)

    def template_for(self, template_id: str) -> str | None:
        """The body template, or ``None``. A missing template cannot be improvised."""
        return self.templates.get(template_id)

    def is_suppressed(self, subject_id: str) -> bool:
        return subject_id in self.suppressed_subjects

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_mapping(cls, data: Any) -> OutreachPolicy:
        """Build a policy from the settings file's ``policy:`` block.

        A section that is ABSENT inherits the shipped default, so a deployment overrides only
        what it means to change. A section that is PRESENT is used exactly as written, empty
        included, because an operator who wrote an empty caps block said something and it was
        not "use the vendor's numbers".
        """
        if data is None:
            return DEFAULT_POLICY
        if not isinstance(data, dict):
            raise PolicyError("settings 'policy' must be a mapping")
        return cls(
            triggers=(
                {
                    str(key): TriggerRule.from_mapping(value, str(key))
                    for key, value in dict(data["triggers"]).items()
                }
                if "triggers" in data
                else dict(DEFAULT_POLICY.triggers)
            ),
            frequency_caps=(
                {
                    str(key): FrequencyCap.from_mapping(value, str(key))
                    for key, value in dict(data["frequency_caps"]).items()
                }
                if "frequency_caps" in data
                else dict(DEFAULT_POLICY.frequency_caps)
            ),
            quiet_hours=(
                {
                    str(key): QuietHours.from_mapping(value, str(key))
                    for key, value in dict(data["quiet_hours"]).items()
                }
                if "quiet_hours" in data
                else dict(DEFAULT_POLICY.quiet_hours)
            ),
            templates=(
                {str(key): str(value) for key, value in dict(data["templates"]).items()}
                if "templates" in data
                else dict(DEFAULT_POLICY.templates)
            ),
            suppressed_subjects=(
                frozenset(str(value) for value in data["suppressed_subjects"] or ())
                if "suppressed_subjects" in data
                else DEFAULT_POLICY.suppressed_subjects
            ),
            banned_phrases=(
                tuple(str(value).lower() for value in data["banned_phrases"] or ())
                if "banned_phrases" in data
                else DEFAULT_POLICY.banned_phrases
            ),
            max_body_chars=(
                _int(data, "max_body_chars", "policy")
                if "max_body_chars" in data
                else DEFAULT_POLICY.max_body_chars
            ),
        )


#: The reference policy: five event types, three markets, synthetic numbers. A deployment
#: replaces every number here with the client's own; none of it is advice.
DEFAULT_POLICY = OutreachPolicy(
    triggers={
        "failed_payment": TriggerRule(
            event_type=EventType.FAILED_PAYMENT,
            template_id="failed_payment_retry",
            purpose="service",
            channel="chat",
            resolution_path="update-payment-method",
            severity=Severity.MEDIUM,
            max_age_hours=48,
            required_attributes=("card_suffix", "retry_on"),
        ),
        "delivery_exception": TriggerRule(
            event_type=EventType.DELIVERY_EXCEPTION,
            template_id="delivery_exception_reschedule",
            purpose="service",
            channel="chat",
            resolution_path="reschedule-delivery",
            severity=Severity.LOW,
            max_age_hours=72,
            required_attributes=("tracking_ref", "next_attempt_on"),
        ),
        "expiring_card": TriggerRule(
            event_type=EventType.EXPIRING_CARD,
            template_id="expiring_card_renew",
            purpose="service",
            channel="chat",
            resolution_path="renew-card",
            severity=Severity.LOW,
            max_age_hours=720,
            required_attributes=("card_suffix", "expires_on"),
        ),
        "fraud_hold": TriggerRule(
            event_type=EventType.FRAUD_HOLD,
            template_id="fraud_hold_verify",
            purpose="service",
            channel="voice",
            resolution_path="verify-in-app",
            severity=Severity.CRITICAL,
            max_age_hours=6,
            required_attributes=("hold_ref", "card_suffix"),
            consequential=True,
        ),
        "outage": TriggerRule(
            event_type=EventType.OUTAGE,
            template_id="outage_status",
            purpose="service",
            channel="chat",
            resolution_path="check-status-page",
            severity=Severity.HIGH,
            max_age_hours=12,
            required_attributes=("outage_ref", "affected_service"),
            consequential=True,
        ),
    },
    frequency_caps={
        "service:chat": FrequencyCap(limit=3, window_hours=24),
        "service:voice": FrequencyCap(limit=1, window_hours=24),
    },
    quiet_hours={
        "SG": QuietHours(start_hour=22, end_hour=8, utc_offset_minutes=480),
        "AU": QuietHours(start_hour=21, end_hour=8, utc_offset_minutes=600),
        "JP": QuietHours(start_hour=21, end_hour=9, utc_offset_minutes=540),
    },
    templates={
        "failed_payment_retry": (
            "A payment on the card ending {card_suffix} did not go through. "
            "We will try again on {retry_on}. You can update the card in the app."
        ),
        "delivery_exception_reschedule": (
            "Delivery {tracking_ref} could not be completed. "
            "The next attempt is {next_attempt_on}, and you can reschedule in the app."
        ),
        "expiring_card_renew": (
            "The card ending {card_suffix} expires on {expires_on}. "
            "Renewing it in the app keeps your scheduled payments running."
        ),
        "fraud_hold_verify": (
            "A hold was placed on the card ending {card_suffix} (reference {hold_ref}). "
            "Please verify the recent activity in the app."
        ),
        "outage_status": (
            "{affected_service} is currently disrupted (reference {outage_ref}). "
            "The status page carries the latest update."
        ),
    },
    suppressed_subjects=frozenset({"subj-000900"}),
    banned_phrases=(
        "guaranteed",
        "refund approved",
        "compensation",
        "click here to confirm your password",
        "verify your card number",
    ),
    max_body_chars=320,
)
