"""On-prem TextToSpeechPort: fail-fast portability placeholder (the sovereign-exit proof).

The client runs its own speech stack on premises. Refusing means the voice channel is
unavailable, which the service reports as an undelivered notification rather than as a
delivered one, so nothing is counted against a customer's cap for a call that never happened.
"""

from __future__ import annotations

from speech_lexicon_kit import SpeechSynthesisRequest, SynthesisResult

from ...config import Settings


class OnPremSpeechSynthesis:
    """Satisfies TextToSpeechPort but refuses: bind the client's own speech stack."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def synthesize(self, request: SpeechSynthesisRequest) -> SynthesisResult:
        raise NotImplementedError(
            "on-prem speech synthesis is a portability placeholder: bind the client's own "
            "text-to-speech stack (see docs/onprem-migration.md)."
        )
