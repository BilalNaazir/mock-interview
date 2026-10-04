"""
transcription.py - Turning speech into text with Whisper.

Whisper is an open-source speech recognition model. We run it with the
faster-whisper library, which works well on an ordinary CPU, so the audio
never leaves our own worker: no external service, no per-minute fees.

The first time the worker starts, it downloads the model (about 150 MB for
"base.en") and caches it, so later starts are quick.
"""

import logging
from typing import Protocol

logger = logging.getLogger("mock_interview.transcription")


class Transcriber(Protocol):
    """
    Anything with a transcribe() method counts as a Transcriber. The worker
    only relies on this, so tests can pass in a fake one instead of loading
    a real 150 MB model.
    """

    def transcribe(self, media_path: str) -> str: ...


class WhisperTranscriber:
    def __init__(self, model_name: str, compute_type: str):
        # Imported here, not at the top of the file, so the API and the tests
        # never need this large library installed - only the worker does.
        from faster_whisper import WhisperModel

        logger.info("Loading Whisper model '%s' (downloads on first run)...", model_name)
        # Loading the model is slow, so the worker does it ONCE at startup
        # and reuses it for every job.
        self.model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
        logger.info("Whisper model ready")

    def transcribe(self, media_path: str) -> str:
        # Whisper reads the audio track straight out of the video file
        # (WebM from Chrome/Firefox/Edge, or MP4 from Safari).
        segments, _info = self.model.transcribe(
            media_path,
            beam_size=5,
            # Voice Activity Detection skips long silences, which makes it
            # faster and stops Whisper "hallucinating" words in the quiet bits.
            vad_filter=True,
        )
        # Whisper returns the speech in chunks ("segments"); join them up.
        return " ".join(segment.text.strip() for segment in segments).strip()
