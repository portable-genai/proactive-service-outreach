"""Managed DraftingPort: the generative drafter, and the narrowest prompt this repo can build.

What is sent to the model is a template id, a locale, a channel and the closed fact set the
trigger engine assembled. Not the event, not the free-text detail, not the subject id, not the
consent decision. There is nothing in the request the model could use to invent a figure,
because the only figures it is shown are the ones it is allowed to repeat.

The model is asked for a JSON object with a single ``body`` string. Whatever comes back is
untrusted and goes through :func:`~...domain.drafting.validate_draft`, which discards it on any
failure; the caller then prepares the deterministic body for a human instead. This adapter
therefore has no repair logic and no retry-with-a-nicer-prompt loop: both would be this module
deciding what the customer is told.

The ``google.genai`` import is lazy, so the offline profiles import this module with no SDK.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import DraftRequest
from ...ports.drafting import DraftingUnavailableError

#: The instruction. It is a constant rather than a built string so that what the model is told
#: is reviewable in a diff, and so no per-request value can enter the instruction itself.
_INSTRUCTION = (
    "Rewrite the service notification below in the requested locale. Use ONLY the facts "
    "provided. Do not add figures, dates, amounts, references or promises of any kind. Return "
    'a JSON object of the form {"body": "..."} and nothing else.'
)


class VertexDraftingAdapter:
    """Draft a notification body with a managed model, on a closed fact set."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, request: DraftRequest) -> str:
        model = self._settings.drafting_model.strip()
        if not model:
            raise DraftingUnavailableError(
                "drafting_model is not configured, so no drafter is reachable. Set "
                "OUTREACH_DRAFTING_MODEL (config/settings.yaml drafting_model), or "
                "bind the offline template drafter."
            )
        return self._generate(model, request)  # pragma: no cover - needs a live model

    def _generate(self, model: str, request: DraftRequest) -> str:
        # pragma: no cover - needs a live model endpoint
        from google import genai

        client = genai.Client(vertexai=True, location=self._settings.region)
        facts = "\n".join(f"- {name}: {value}" for name, value in sorted(request.facts.items()))
        prompt = (
            f"{_INSTRUCTION}\n\nlocale: {request.locale}\nchannel: {request.channel}\n"
            f"template: {request.template_id}\nmax_characters: {request.max_chars}\n"
            f"facts:\n{facts}\n"
        )
        response = client.models.generate_content(model=model, contents=prompt)
        return str(getattr(response, "text", "") or "")
