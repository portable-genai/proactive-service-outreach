"""Local TextToSpeechPort: a deterministic offline synthesiser that produces no audio.

It returns a :class:`~speech_lexicon_kit.SynthesisResult` whose ``AudioRef`` names a
content-addressed ``file:`` URI derived from the request. No bytes are produced, nothing is
written and no voice of any customer exists anywhere in the offline profile, which is the right
posture for a gate that runs on a laptop.

The URI is a digest of the request rather than a counter, so two runs of the same demo produce
the same reference and a replay comparison is meaningful. Synthesising real audio offline would
add a dependency, a codec and a temporary file to a gate whose whole value is that it needs
none of the three.
"""

from __future__ import annotations

import hashlib

from speech_lexicon_kit import AudioRef, SpeechSynthesisRequest, SynthesisResult

from ...config import Settings

#: The voice the offline profile reports. A name, not a model: nothing here renders audio.
OFFLINE_VOICE = "offline-fixture-voice"


class FixtureSpeechSynthesis:
    """Answer the TTS port with a deterministic audio reference and no audio."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def synthesize(self, request: SpeechSynthesisRequest) -> SynthesisResult:
        digest = hashlib.sha256(
            "|".join((request.request_id, request.locale, request.text)).encode("utf-8")
        ).hexdigest()[:16]
        return SynthesisResult(
            request_id=request.request_id,
            audio=AudioRef(
                uri=f"file:///offline/synthesis/{digest}.mp3",
                media_type=request.audio_encoding,
                sample_rate_hz=24000,
                channels=1,
            ),
            voice=self._settings.speech_voice.strip() or OFFLINE_VOICE,
            characters_billed=len(request.text),
        )
