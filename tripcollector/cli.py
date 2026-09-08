"""Command-line entry point for TripCollector."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from tripcollector import __version__
from tripcollector.captions import collect_captions
from tripcollector.config import Settings
from tripcollector.downloader import (
    DownloadError,
    VideoItem,
    download_one,
    gather_urls,
)
from tripcollector.summarizer import summarize
from tripcollector.transcriber import TranscriptionError, transcribe
from tripcollector.utils import ensure_dir, log, setup_logging, write_text


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tripcollector",
        description="Turn TikTok travel collections into per-country trip notes.",
    )
    p.add_argument("--country", required=True, help="Country folder to write into.")
    p.add_argument("--input", type=Path, help="Text file with one TikTok URL per line.")
    p.add_argument("--collection", help="A TikTok collection/playlist URL to expand.")
    p.add_argument("--url", action="append", default=[], help="A TikTok URL (repeatable).")
    p.add_argument("--out", type=Path, default=Path("trips"), help="Output root (default: ./trips).")
    p.add_argument(
        "--source",
        default="captions",
        choices=["captions", "audio"],
        help=(
            "How to obtain each transcript: 'captions' fetches the TikTok's "
            "own caption track as text (no media download, no API key; "
            "default), 'audio' downloads audio and runs Whisper."
        ),
    )
    p.add_argument(
        "--whisper-backend",
        default="auto",
        choices=["auto", "faster-whisper", "openai-whisper", "openai"],
        help="Transcription backend (default: auto).",
    )
    p.add_argument("--whisper-model", default="small", help="Whisper model size (default: small).")
    p.add_argument("--language", help="Force transcription language, e.g. en, ja (default: auto).")
    p.add_argument("--force", action="store_true", help="Re-run every stage even if outputs exist.")
    p.add_argument("--keep-video", action="store_true", help="Keep the downloaded video file.")
    p.add_argument("--no-summary-index", action="store_true", help="Do not write the aggregate country summary.")
    p.add_argument("-v", "--verbose", action="store_true", help="More logging.")
    p.add_argument("--version", action="version", version=f"tripcollector {__version__}")
    return p


def settings_from_args(argv: Optional[List[str]] = None) -> Settings:
    args = build_parser().parse_args(argv)
    return Settings(
        country=args.country,
        out_root=args.out,
        input_file=args.input,
        collection_url=args.collection,
        urls=list(args.url or []),
        source=args.source,
        whisper_backend=args.whisper_backend,
        whisper_model=args.whisper_model,
        language=args.language,
        force=args.force,
        keep_video=args.keep_video,
        write_index=not args.no_summary_index,
        verbose=args.verbose,
    )


def process_video(url: str, s: Settings) -> Optional[VideoItem]:
    """Run transcript-collection -> summarize for a single URL.

    The transcript comes either from the TikTok's own caption track
    (``source == "captions"``, no media download) or from downloading audio and
    running Whisper (``source == "audio"``).
    """
    transcript = ""
    try:
        if s.source == "captions":
            item, transcript = collect_captions(
                url, s.country_dir, language=s.language, force=s.force
            )
        else:
            item = download_one(
                url, s.country_dir, keep_video=s.keep_video, force=s.force
            )
    except DownloadError as exc:
        log.error("Failed to collect %s: %s", url, exc)
        return None

    transcript_path = item.dir / "transcript.txt"
    summary_path = item.dir / "summary.md"

    if s.source == "audio":
        if item.audio_path and item.audio_path.exists():
            try:
                transcript = transcribe(
                    item.audio_path,
                    transcript_path,
                    backend=s.whisper_backend,
                    model=s.whisper_model,
                    language=s.language,
                    force=s.force,
                )
            except TranscriptionError as exc:
                log.error("Transcription failed for %s: %s", item.id, exc)
        else:
            log.warning("No audio for %s; skipping transcription.", item.id)

    if summary_path.exists() and not s.force:
        log.info("Summary exists, skipping: %s", summary_path.name)
    else:
        summary = summarize(
            transcript,
            title=item.title,
            country=s.country,
            url=item.url,
            openai_model=s.openai_model,
        )
        write_text(summary_path, summary + "\n")
        log.info("Wrote summary: %s", summary_path)

    return item


def write_country_index(items: List[VideoItem], s: Settings) -> Path:
    """Combine every per-video summary into one aggregate country file."""
    index_path = s.country_dir / f"_{s.country_dir.name}_summary.md"
    parts: List[str] = [
        f"# Trip notes: {s.country}",
        "",
        f"Auto-generated from {len(items)} TikTok(s) by TripCollector.",
        "",
    ]
    for item in items:
        summary_file = item.dir / "summary.md"
        if summary_file.exists():
            parts.append(summary_file.read_text(encoding="utf-8").strip())
            parts.append("\n")
    write_text(index_path, "\n".join(parts).rstrip() + "\n")
    log.info("Wrote country index: %s", index_path)
    return index_path


def run(s: Settings) -> int:
    setup_logging(s.verbose)
    ensure_dir(s.country_dir)

    log.info("Country: %s  ->  %s", s.country, s.country_dir)
    if not s.has_openai:
        log.info("No OPENAI_API_KEY set: using the heuristic summarizer.")

    try:
        urls = gather_urls(
            urls=s.urls,
            input_file=s.input_file,
            collection_url=s.collection_url,
        )
    except DownloadError as exc:
        log.error("%s", exc)
        return 2

    if not urls:
        log.error(
            "No TikTok URLs to process. Provide --collection, --input, or --url."
        )
        return 2

    log.info("Processing %d video(s).", len(urls))
    items: List[VideoItem] = []
    for i, url in enumerate(urls, 1):
        log.info("[%d/%d] %s", i, len(urls), url)
        item = process_video(url, s)
        if item:
            items.append(item)

    if s.write_index and items:
        write_country_index(items, s)

    log.info("Done. %d/%d videos processed.", len(items), len(urls))
    return 0 if items else 1


def main(argv: Optional[List[str]] = None) -> int:
    try:
        s = settings_from_args(argv)
        return run(s)
    except KeyboardInterrupt:
        log.error("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
