"""MessageDeliveryPort: the chat channel, and the envelope every send is obliged to carry.

The envelope is the reason this port takes two arguments instead of one. A delivery adapter is
handed the message AND the :class:`~..domain.models.DeliveryEnvelope` that authorised it: the
consent decision id, the cap limit, the sends already counted in the window and what remained.
So the record of "why was this person contacted" travels with the contact, into the adapter's
own log and into this service's audit trail, rather than being two rows a later investigation
has to join on a timestamp.

An adapter must refuse an envelope with no consent decision id. That is not defensive
programming: it is the last place a send can be stopped, and a delivery path that would send
without one is a delivery path that will eventually be called from somewhere that forgot.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import DeliveryEnvelope, DeliveryReceipt, OutreachMessage


class DeliveryRefusedError(RuntimeError):
    """Raised when a send is attempted without the provenance that authorises it."""


@runtime_checkable
class MessageDeliveryPort(Protocol):
    def send(self, message: OutreachMessage, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        """Deliver one message on the chat channel, or raise. Never silently drop it."""
        ...
