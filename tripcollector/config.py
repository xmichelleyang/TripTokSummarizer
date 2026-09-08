"""Configuration for a TripCollector run."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Settings:
    """Everything a single run needs, resolved from CLI args + environment."""

    country: str
    out_root: Path = Path("trips")

    # Inputs (any combination; all are merged and de-duplicated).
    input_file: Optional[Path] = None
    collection_url: Optional[str] = None
    urls: List[str] = field(default_factory=list)

    # Transcription.
    source: str = "captions"  # captions | audio
    whisper_backend: str = "auto"  # auto | faster-whisper | openai-whisper | openai
    whisper_model: str = "small"
    language: Optional[str] = None  # None => auto-detect

    # Behavior.
    force: bool = False
    keep_video: bool = False
    write_index: bool = True
    verbose: bool = False

    # Summarization (OpenAI, optional).
    openai_model: str = field(
        default_factory=lambda: os.environ.get(
            "TRIPCOLLECTOR_OPENAI_MODEL", "gpt-4o-mini"
        )
    )

    @property
    def country_dir(self) -> Path:
        return self.out_root / _safe_country(self.country)

    @property
    def has_openai(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))


def _safe_country(name: str) -> str:
    """A filesystem-safe country folder name that keeps readability."""
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
    return "_".join(cleaned.split()).strip("_") or "Unknown"
