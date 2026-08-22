"""On-prem DraftingPort: fail-fast portability placeholder (the sovereign-exit proof, P-12).

The client runs its own model on premises, so this binding refuses at call time. The service
treats the refusal as a discarded draft: the deterministic template body is prepared for a
human and nothing is delivered automatically, which is the same outcome as a model that
returned something the validator rejected.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import DraftRequest


class OnPremDraftingAdapter:
    """Satisfies DraftingPort but refuses: bind the client's own model endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, request: DraftRequest) -> str:
        raise NotImplementedError(
            "on-prem drafting is a portability placeholder: bind the client's own model "
            "endpoint (see docs/onprem-migration.md). The deterministic template body is "
            "always available, so a refusal here costs a phrasing, never a notification."
        )
