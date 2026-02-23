"""Whisper-based audio transcription for videos without subtitles.

Uses faster-whisper (CTranslate2) for GPU-accelerated speech-to-text.
The model is loaded lazily on first use and cached for subsequent calls.
"""

from __future__ import annotations

import logging
import os
import tempfile

import httpx

logger = logging.getLogger(__name__)

# Use HuggingFace mirror for regions where huggingface.co is blocked
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# Lazy-loaded model instance
_model = None
_model_size = os.environ.get("WHISPER_MODEL_SIZE", "large-v3")


def _get_model():
    """Load the faster-whisper model (cached after first call)."""
    global _model
    if _model is not None:
        return _model

    from faster_whisper import WhisperModel

    logger.info("Loading Whisper model '%s' (first call, may download)...", _model_size)
    _model = WhisperModel(
        _model_size,
        device="cuda",
        compute_type="float16",
    )
    logger.info("Whisper model loaded successfully")
    return _model


async def transcribe_from_url(
    audio_url: str,
    *,
    referer: str = "https://www.bilibili.com",
    language: str = "zh",
    max_duration: int = 1800,
) -> str | None:
    """Download audio from URL and transcribe it with Whisper.

    Args:
        audio_url: Direct URL to the audio stream.
        referer: Referer header for the download request.
        language: Language hint for Whisper.
        max_duration: Skip videos longer than this (seconds) to avoid OOM.

    Returns:
        Transcribed text, or None on failure.
    """
    tmp_path = None
    try:
        # Download audio to a temp file (streaming to avoid large memory usage)
        timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "GET",
                audio_url,
                headers={
                    "Referer": referer,
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
                    ),
                },
                follow_redirects=True,
            ) as resp:
                resp.raise_for_status()

                # Write to temp file in chunks
                with tempfile.NamedTemporaryFile(
                    suffix=".m4a", delete=False
                ) as tmp:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        tmp.write(chunk)
                    tmp_path = tmp.name

        audio_size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        logger.info(
            "[whisper] Downloaded audio: %.1f MB -> %s", audio_size_mb, tmp_path
        )

        # Transcribe
        import asyncio

        text = await asyncio.to_thread(_transcribe_sync, tmp_path, language)
        return text

    except Exception:
        logger.exception("[whisper] Transcription failed for %s", audio_url[:80])
        return None

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _transcribe_sync(audio_path: str, language: str) -> str | None:
    """Run Whisper transcription synchronously (called via asyncio.to_thread)."""
    model = _get_model()

    segments, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=300,
            threshold=0.3,
        ),
    )

    logger.info(
        "[whisper] Detected language: %s (prob=%.2f), duration=%.1fs",
        info.language,
        info.language_probability,
        info.duration,
    )

    texts = []
    for segment in segments:
        texts.append(segment.text.strip())

    full_text = "\n".join(texts)
    logger.info("[whisper] Transcribed %d segments, %d chars", len(texts), len(full_text))

    return full_text if full_text else None
