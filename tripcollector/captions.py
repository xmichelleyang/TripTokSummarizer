"""Fetch a TikTok's transcript from its **caption track** — no media download.

TikTok videos usually ship an on-screen caption / subtitle track (creator
supplied or auto-generated). yt-dlp can retrieve just that text file with
``--write-subs --skip-download``, which is far lighter than downloading the
audio and running Whisper, and needs no API key. This module turns that VTT
track into a plain-text transcript.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Optional

from tripcollector.downloader import (
    IMPERSONATE_ARGS,
    DownloadError,
    VideoItem,
    _yt_dlp,
    probe_metadata,
    write_item_metadata,
)
from tripcollector.utils import ensure_dir, log, slugify


def choose_sub_lang(meta: dict, preferred: Optional[str]) -> Optional[str]:
    """Pick the best caption language from a video's metadata.

    Prefers creator subtitles over auto-captions, and within those prefers the
    user's requested language, then any English track, then whatever exists.
    """
    for source in ("subtitles", "automatic_captions"):
        langs = list((meta.get(source) or {}).keys())
        if not langs:
            continue
        if preferred:
            for lang in langs:
                if lang.lower().startswith(preferred.lower()):
                    return lang
        for lang in langs:
            if lang.lower().startswith("en"):
                return lang
        return langs[0]
    return None


_LANG_RE = re.compile(r"caption\.(?P<lang>.+)\.vtt$", re.IGNORECASE)


def _lang_of(path: Path) -> str:
    m = _LANG_RE.search(path.name)
    return m.group("lang").lower() if m else ""


def _pick_vtt(files: List[Path], preferred: Optional[str]) -> Path:
    """Choose the best caption file: requested language, then English, then any."""

    def rank(p: Path) -> int:
        lang = _lang_of(p)
        if preferred and lang.startswith(preferred.lower()):
            return 0
        if lang.startswith("en"):
            return 1
        return 2

    return sorted(files, key=lambda p: (rank(p), p.name))[0]


def vtt_to_text(vtt: str) -> str:
    """Convert WEBVTT cue text into a clean, single-paragraph transcript."""
    out: List[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "WEBVTT" or ":" in line and line.split(":", 1)[0] in (
            "Kind",
            "Language",
            "NOTE",
        ):
            continue
        if "-->" in line:
            continue
        if line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line)  # strip inline timing/style tags
        line = line.strip()
        if not line or (out and out[-1] == line):
            continue
        out.append(line)
    return " ".join(out).strip()


def _download_vtts(url: str, item_dir: Path) -> List[Path]:
    """Fetch every available caption track into ``item_dir``; return the files.

    TikTok's ``-J`` metadata does not list subtitle tracks, so we ask yt-dlp to
    write them directly (``--sub-langs all``). Tracks are tiny text files.
    """
    stem = item_dir / "caption"
    args = [
        *IMPERSONATE_ARGS,
        "--write-subs",
        "--sub-langs",
        "all",
        "--sub-format",
        "vtt",
        "--skip-download",
        "--no-playlist",
        "-o",
        f"{stem}.%(ext)s",
        url,
    ]
    proc = subprocess.run(
        [_yt_dlp(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise DownloadError(
            f"Caption fetch failed for {url}: {proc.stderr.strip()[:400]}"
        )
    return sorted(item_dir.glob("caption.*.vtt"))


def collect_captions(
    url: str,
    country_dir: Path,
    language: Optional[str] = None,
    force: bool = False,
) -> tuple[VideoItem, str]:
    """Fetch metadata + caption transcript for one TikTok, writing both to disk.

    Returns the :class:`VideoItem` (with ``audio_path=None``) and the transcript
    text. When no caption track exists, the transcript is an empty string.
    """
    meta = probe_metadata(url)
    item_dir = ensure_dir(country_dir / str(meta.get("id") or slugify(url)))
    fields = write_item_metadata(item_dir, meta, url)

    transcript_path = item_dir / "transcript.txt"
    if transcript_path.exists() and not force:
        log.info("Transcript exists, skipping: %s", transcript_path.name)
        text = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
    else:
        log.info("Fetching captions: %s", fields["title"][:60])
        vtt_files = _download_vtts(url, item_dir)
        if not vtt_files:
            log.warning("No caption track available for %s", fields["id"])
            text = ""
        else:
            best = _pick_vtt(vtt_files, language)
            log.info("Using caption track '%s' for %s", _lang_of(best), fields["id"])
            text = vtt_to_text(best.read_text(encoding="utf-8"))
            for f in vtt_files:  # keep only the plain-text transcript
                f.unlink()
            if not text:
                log.warning("Caption track for %s was empty", fields["id"])
        transcript_path.write_text(text + "\n", encoding="utf-8")

    item = VideoItem(
        id=fields["id"],
        url=fields["url"],
        title=fields["title"],
        uploader=fields["uploader"],
        description=fields["description"],
        dir=item_dir,
        audio_path=None,
        video_path=None,
    )
    return item, text
