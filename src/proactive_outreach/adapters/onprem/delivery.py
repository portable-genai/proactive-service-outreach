"""On-prem MessageDeliveryPort: fail-fast portability placeholder (the sovereign-exit proof).

The client's own messaging platform delivers on premises, so this binding refuses at call time.
A placeholder that returned a receipt would be the worst possible failure on this port: the
service would record a delivered notification, count it against the frequency cap and tell the
consent store about a contact that never happened.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import DeliveryEnvelope, DeliveryReceipt, OutreachMessage


class OnPremDelivery:
    """Satisfies MessageDeliveryPort but refuses: bind the client's own messaging platform."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, message: OutreachMessage, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        raise NotImplementedError(
            "on-prem delivery is a portability placeholder: bind the client's own messaging "
            "platform (see docs/onprem-migration.md). Returning a receipt for a message nobody "
            "sent would count against the customer's frequency cap for a contact they never got."
        )
