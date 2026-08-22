"""Local DraftingPort: a deterministic offline stand-in for the generative drafter.

It renders the configured template against the closed fact set and returns it in the same JSON
envelope a model is asked for, so the offline gate exercises the real validator, the real
grounding check and the real discard path rather than skipping them.

Two things it deliberately is NOT:

* it is not a model, and it does not pretend to be one. The offline profile has no model, and a
  fake one that produced plausible prose would make every groundedness metric a tautology: the
  scorer would be checking output it generated itself against facts it chose;
* it is not a bypass of validation. Its output goes through
  :func:`~...domain.drafting.validate_draft` exactly like a model's would, and it would be
  rejected by the same rules if it ever produced an ungrounded figure.

The metric that judges the validator therefore scores it against an INDEPENDENTLY labelled set
of candidate drafts in ``eval/datasets/``, not against this adapter's output.
"""

from __future__ import annotations

import json

from ...config import Settings
from ...domain.drafting import render_template
from ...domain.models import DraftRequest
from ...ports.drafting import DraftingUnavailableError


class TemplateDraftingAdapter:
    """Return the deterministic body in the drafter's JSON envelope."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, request: DraftRequest) -> str:
        message = render_template(request, policy=self._settings.policy)
        if message is None:
            raise DraftingUnavailableError(
                f"no template is configured for {request.template_id!r}, so there is no "
                "deterministic body to fall back on and nothing may be improvised"
            )
        return json.dumps({"body": message.body}, sort_keys=True)
