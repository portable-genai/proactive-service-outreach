"""Managed MessageDeliveryPort: deliver the chat notification through the conversation platform.

The envelope travels as request parameters, not as prose in the message, so the consent decision
id and the cap counters land in the platform's own log next to the delivery it authorised. An
investigation months later then reads one record rather than joining two on a timestamp.

The platform SDK import is lazy, so the offline profiles import this module with no SDK. The
configuration is checked first, so a deployment that never named an agent gets a refusal naming
the variable rather than an import error that names nothing useful.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import DeliveryEnvelope, DeliveryReceipt, OutreachMessage
from ...ports.delivery import DeliveryRefusedError


class ConversationChannelDelivery:
    """Send one notification on the managed conversation channel."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, message: OutreachMessage, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        if not envelope.consent_decision_id.strip():
            raise DeliveryRefusedError(
                "refusing to deliver: the envelope carries no consent decision id, so nothing "
                "records what authorised contacting this subject"
            )
        agent = self._settings.chat_agent.strip()
        if not agent:
            raise DeliveryRefusedError(
                "chat_agent is not configured, so there is no channel to deliver on. Set "
                "OUTREACH_CHAT_AGENT (config/settings.yaml chat_agent), or bind the "
                "offline chat outbox."
            )
        return self._dispatch(agent, message, envelope)  # pragma: no cover - needs a live channel

    def _dispatch(
        self, agent: str, message: OutreachMessage, envelope: DeliveryEnvelope
    ) -> DeliveryReceipt:
        # pragma: no cover - needs a live conversation platform
        from google.cloud import dialogflowcx_v3 as dialogflow

        client = dialogflow.SessionsClient()
        response = client.detect_intent(
            request={
                "session": f"{agent}/sessions/{envelope.event_id}",
                "query_input": {
                    "text": {"text": message.body},
                    "language_code": message.locale,
                },
                "query_params": {
                    "parameters": {
                        "consent_decision_id": envelope.consent_decision_id,
                        "cap_limit": envelope.cap_limit,
                        "sends_in_window": envelope.sends_in_window,
                        "cap_remaining": envelope.cap_remaining,
                        "purpose": envelope.purpose,
                    }
                },
            }
        )
        return DeliveryReceipt(
            channel="chat",
            reference=str(getattr(response, "response_id", "") or envelope.event_id),
            delivered_at=envelope.as_of,
            detail=f"consent={envelope.consent_decision_id}",
        )
