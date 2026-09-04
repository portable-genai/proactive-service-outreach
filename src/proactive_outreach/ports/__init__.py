"""The hexagon's boundaries, re-exported once so there is a single import site.

Every port is a ``@runtime_checkable`` Protocol and every port has a binding in every profile
(``config.DEFAULT_BINDINGS``); ``tests/contract/test_port_parity.py`` asserts both, plus set
equality across all five places a port is registered, so a port added here without a binding
fails the build.

Two of the eight are not declared in this package at all, and that is the point:

* ``IdentityPort`` comes from ``hex-service-kit``. What an identity adapter DECLARES about the
  authentication it provides is this service's own vocabulary, not the commons', and lives in
  :mod:`.identity` next to the re-export.
* ``TextToSpeechPort`` comes from ``speech-lexicon-kit`` (see :mod:`.speech`). A repo that
  writes its own speech types is a repo that will disagree with its siblings about what a
  customer was told and when.

``ConsentPort`` is declared here but its wire TYPES come from ``consent-preference-kit``, because
the consent store itself is marketing-compliance-gate's asset and this system is one of its
consumers.
"""

from __future__ import annotations

from hex_service_kit.identity import IdentityPort
from speech_lexicon_kit import TextToSpeechPort

from .audit import AuditSinkPort
from .consent import ConsentPort, ConsentUnavailableError
from .delivery import DeliveryRefusedError, MessageDeliveryPort
from .drafting import DraftingPort, DraftingUnavailableError
from .events import EventDetectionPort, EventSourceUnavailableError
from .identity import (
    CLIENT_ASSERTED,
    END_USER_AUTH_ATTR,
    END_USER_AUTH_KINDS,
    UNIMPLEMENTED,
    VERIFIED,
    EndUserAuthUnavailableError,
    declared_end_user_auth,
)
from .observability import (
    EvaluationGatePort,
    ObservabilityTracerPort,
    TokenUsage,
)
from .review_router import ReviewRouterPort
from .speech import SpeechUnavailableError

#: port name (the key in the settings ``adapters:`` block) -> the Protocol it must satisfy.
PORT_PROTOCOLS: dict[str, type] = {
    "audit": AuditSinkPort,
    "consent": ConsentPort,
    "delivery": MessageDeliveryPort,
    "drafting": DraftingPort,
    "events": EventDetectionPort,
    "identity": IdentityPort,
    "review_router": ReviewRouterPort,
    "speech": TextToSpeechPort,
    "tracer": ObservabilityTracerPort,
    "evaluation": EvaluationGatePort,
}

__all__ = [
    "TokenUsage",
    "ObservabilityTracerPort",
    "EvaluationGatePort",
    "CLIENT_ASSERTED",
    "END_USER_AUTH_ATTR",
    "END_USER_AUTH_KINDS",
    "PORT_PROTOCOLS",
    "UNIMPLEMENTED",
    "VERIFIED",
    "AuditSinkPort",
    "ConsentPort",
    "ConsentUnavailableError",
    "DeliveryRefusedError",
    "DraftingPort",
    "DraftingUnavailableError",
    "EndUserAuthUnavailableError",
    "EventDetectionPort",
    "EventSourceUnavailableError",
    "IdentityPort",
    "MessageDeliveryPort",
    "ReviewRouterPort",
    "SpeechUnavailableError",
    "TextToSpeechPort",
    "declared_end_user_auth",
]
