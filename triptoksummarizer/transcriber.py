"""Transcribe audio to text using a Whisper backend.

Backends, tried in order when ``backend == "auto"``:
    1. faster-whisper  (local, fast; recommended)
    2. openai-whisper  (local, pure PyTorch)
    3. openai API      (cloud whisper-1; needs OPENAI_API_KEY)
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Optional

from triptoksummarizer.utils import log, write_text


class TranscriptionError(RuntimeError):
    pass


def _available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def resolve_backend(preferred: str) -> str:
    """Pick a concrete backend given the user's preference."""
    if preferred != "auto":
        return preferred
    if _available("faster_whisper"):
        return "faster-whisper"
    if _available("whisper"):
        return "openai-whisper"
    if _available("openai") and os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise TranscriptionError(
        "No transcription backend available. Install one of:\n"
        "  pip install faster-whisper   (recommended)\n"
        "  pip install openai-whisper\n"
        "  pip install openai           (and set OPENAI_API_KEY)"
    )


def transcribe(
    audio_path: Path,
    out_path: Path,
    backend: str = "auto",
    model: str = "small",
    language: Optional[str] = None,
    force: bool = False,
) -> str:
    """Transcribe ``audio_path`` and write text to ``out_path``. Returns text."""
    if out_path.exists() and not force:
        log.info("Transcript exists, skipping: %s", out_path.name)
        return out_path.read_text(encoding="utf-8", errors="replace")

    chosen = resolve_backend(backend)
    log.info("Transcribing (%s / %s): %s", chosen, model, audio_path.name)

    if chosen == "faster-whisper":
        text = _transcribe_faster_whisper(audio_path, model, language)
    elif chosen == "openai-whisper":
        text = _transcribe_openai_whisper(audio_path, model, language)
    elif chosen == "openai":
        text = _transcribe_openai_api(audio_path, language)
    else:
        raise TranscriptionError(f"Unknown backend: {chosen}")

    text = text.strip()
    write_text(out_path, text + "\n")
    return text


def _transcribe_faster_whisper(
    audio_path: Path, model: str, language: Optional[str]
) -> str:
    from faster_whisper import WhisperModel  # type: ignore

    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _info = wm.transcribe(
        str(audio_path), language=language, vad_filter=True
    )
    return " ".join(seg.text.strip() for seg in segments)


def _transcribe_openai_whisper(
    audio_path: Path, model: str, language: Optional[str]
) -> str:
    import whisper  # type: ignore

    wm = whisper.load_model(model)
    result = wm.transcribe(str(audio_path), language=language)
    return str(result.get("text", ""))


def _transcribe_openai_api(audio_path: Path, language: Optional[str]) -> str:
    from openai import OpenAI  # type: ignore

    client = OpenAI()
    with open(audio_path, "rb") as fh:
        kwargs = {"model": "whisper-1", "file": fh}
        if language:
            kwargs["language"] = language
        resp = client.audio.transcriptions.create(**kwargs)
    return getattr(resp, "text", "") or ""
