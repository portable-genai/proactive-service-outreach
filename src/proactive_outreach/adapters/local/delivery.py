"""Local MessageDeliveryPort: an in-process chat outbox that records the whole envelope.

Nothing leaves the machine, and that is the only thing about it that is fake. The envelope, the
refusal rules and the receipt are the shipped ones, so the offline gate and the demo can assert
that a send carried the consent decision id and the cap counters WITHOUT a messaging platform.

The refusal is the load-bearing part. A send with no consent decision id is refused here, at the
last place a send can be stopped. It is not defensive decoration: the sequence that produces
one is a caller assembling an envelope by hand or a future surface that forgot the eligibility
step, and both of those are exactly the mistakes that end with a customer contacted on nobody's
authority.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import DeliveryEnvelope, DeliveryReceipt, OutreachMessage
from ...ports.delivery import DeliveryRefusedError


class LocalChatDelivery:
    """Append the message and its envelope to an in-memory outbox and return a receipt."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sent: list[tuple[OutreachMessage, DeliveryEnvelope]] = []

    def send(self, message: OutreachMessage, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        if not envelope.consent_decision_id.strip():
            raise DeliveryRefusedError(
                "refusing to deliver: the envelope carries no consent decision id, so nothing "
                "records what authorised contacting this subject"
            )
        self._sent.append((message, envelope))
        return DeliveryReceipt(
            channel="chat",
            reference=f"chat:{envelope.event_id}:{len(self._sent)}",
            delivered_at=envelope.as_of,
            detail=(
                f"consent={envelope.consent_decision_id} "
                f"cap={envelope.sends_in_window}/{envelope.cap_limit} "
                f"remaining={envelope.cap_remaining}"
            ),
        )

    @property
    def sent(self) -> tuple[tuple[OutreachMessage, DeliveryEnvelope], ...]:
        """Everything this outbox delivered, for inspection in tests, the eval and the demo."""
        return tuple(self._sent)
