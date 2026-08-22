"""Managed TextToSpeechPort: synthesise the spoken notification, return a reference to it.

Bytes never enter the domain. The adapter writes the synthesised audio to the configured
in-region bucket and returns an ``AudioRef``, so residency and retention are properties of a
storage location an operator provisioned rather than of a value this process is holding.

The ``google-cloud-texttospeech`` import is lazy, so the offline profiles import this module
with no SDK installed.
"""

from __future__ import annotations

from speech_lexicon_kit import AudioRef, SpeechSynthesisRequest, SynthesisResult

from ...config import Settings
from ...ports.speech import SpeechUnavailableError


class CloudTextToSpeech:
    """Synthesise one notification with the managed speech service."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def synthesize(self, request: SpeechSynthesisRequest) -> SynthesisResult:
        voice = self._settings.speech_voice.strip()
        destination = self._settings.speech_output_uri.strip()
        if not voice or not destination:
            raise SpeechUnavailableError(
                "speech_voice and speech_output_uri must both be configured before the voice "
                "channel can be used. Set OUTREACH_SPEECH_VOICE and "
                "OUTREACH_SPEECH_OUTPUT_URI, or bind the offline fixture synthesiser."
            )
        return self._synthesize(voice, destination, request)  # pragma: no cover - needs the API

    def _synthesize(
        self, voice: str, destination: str, request: SpeechSynthesisRequest
    ) -> SynthesisResult:
        # pragma: no cover - needs a live speech endpoint and a bucket
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()
        response = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=request.text),
            voice=texttospeech.VoiceSelectionParams(language_code=request.locale, name=voice),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
        )
        uri = destination.rstrip("/") + "/" + request.request_id + ".mp3"
        _write_audio(uri, response.audio_content)
        return SynthesisResult(
            request_id=request.request_id,
            audio=AudioRef(uri=uri, media_type="audio/mpeg", sample_rate_hz=24000, channels=1),
            voice=voice,
            characters_billed=len(request.text),
        )


def _write_audio(uri: str, payload: bytes) -> None:  # pragma: no cover - needs a live bucket
    """Persist the synthesised audio at ``uri`` in the residency region's bucket."""
    from google.cloud import storage

    bucket_name, _, blob_name = uri.removeprefix("gs://").partition("/")
    storage.Client().bucket(bucket_name).blob(blob_name).upload_from_string(
        payload, content_type="audio/mpeg"
    )
