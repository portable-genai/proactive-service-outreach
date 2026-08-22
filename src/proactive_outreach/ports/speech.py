"""The voice channel: the text-to-speech port, RE-EXPORTED from ``speech-lexicon-kit``.

Nothing is declared here. ``TextToSpeechPort``, ``SpeechSynthesisRequest``, ``SynthesisResult``
and ``AudioRef`` come from the shared speech kernel, pinned by tag, and this module exists only
so the hexagon still has one import site for its boundary set.

Declaring a fourth incompatible TTS protocol is the failure this avoids. Several catalog systems
speak to or listen to customers, and a compliance statement like "the disclosure was read at
00:12 of turn 4" has to mean the same thing in all of them. The moment one repo writes its own
transcript, span or audio-reference type, two repos disagree about what was said and to whom,
and the disagreement is invisible until an auditor asks. The kit carries the kernel; this repo
carries its own message policy and nothing else.

Audio is referenced by URI, never held as bytes in the domain, so this service never becomes
the thing that persisted a customer's voice.
"""

from __future__ import annotations

from speech_lexicon_kit import (
    AudioRef,
    SpeechSynthesisRequest,
    SynthesisResult,
    TextToSpeechPort,
)


class SpeechUnavailableError(RuntimeError):
    """Raised when no speech synthesiser is configured or reachable."""


__all__ = [
    "AudioRef",
    "SpeechSynthesisRequest",
    "SpeechUnavailableError",
    "SynthesisResult",
    "TextToSpeechPort",
]
