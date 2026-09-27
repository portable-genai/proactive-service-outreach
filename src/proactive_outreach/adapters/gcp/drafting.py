"""Managed DraftingPort: the generative drafter, and the narrowest prompt this repo can build.

What is sent to the model is a template id, a locale, a channel and the closed fact set the
trigger engine assembled. Not the event, not the free-text detail, not the subject id, not the
consent decision. There is nothing in the request the model could use to invent a figure,
because the only figures it is shown are the ones it is allowed to repeat.

The prompt itself is NOT built here. The domain renders it
(:func:`~...domain.drafting.drafting_prompt`), screens it through the guardrail (rule R1) and
hands this adapter the screened text, which is sent exactly as given. An adapter that rebuilt
its own prompt would send the model a string nobody screened. An empty prompt is refused rather
than sent, so a caller that skipped the screen gets no model call at all.

The model is asked for a JSON object with a single ``body`` string. Whatever comes back is
untrusted: the domain screens it on the way out and then puts it through
:func:`~...domain.drafting.validate_draft`, which discards it on any failure; the caller then
prepares the deterministic body for a human instead. This adapter therefore has no repair logic
and no retry-with-a-nicer-prompt loop: both would be this module deciding what the customer is
told.

The ``google.genai`` import is lazy, so the offline profiles import this module with no SDK.

Sampling is left FREE: the call sends no ``temperature`` at all, because this is drafting, not
extraction or scoring, and some models reject the parameter outright. Reproducibility is not
this adapter's job; the validator downstream decides what may be sent. After the call returns,
the adapter notes the model it called (``hex_service_kit.provenance``), which is what the
console's model pill names. No search tool is attached, so it never notes a search.
"""

from __future__ import annotations

from hex_service_kit import provenance

from ...config import Settings
from ...domain.models import DraftRequest
from ...ports.drafting import DraftingUnavailableError


class VertexDraftingAdapter:
    """Draft a notification body with a managed model, on a closed fact set."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, request: DraftRequest, *, prompt: str) -> str:
        model = self._settings.drafting_model.strip()
        if not model:
            raise DraftingUnavailableError(
                "drafting_model is not configured, so no drafter is reachable. Set "
                "OUTREACH_DRAFTING_MODEL (config/settings.yaml drafting_model), or "
                "bind the offline template drafter."
            )
        if not prompt.strip():
            raise DraftingUnavailableError(
                "no screened prompt was handed to the drafter, so nothing is sent to a model: "
                "the prompt is rendered and screened by the domain (rule R1), never built here"
            )
        return self._generate(model, prompt)  # pragma: no cover - needs a live model

    def _generate(self, model: str, prompt: str) -> str:
        # pragma: no cover - needs a live model endpoint
        from google import genai

        client = genai.Client(vertexai=True, location=self._settings.region)
        response = client.models.generate_content(model=model, contents=prompt)
        provenance.note_model(model)
        return str(getattr(response, "text", "") or "")
