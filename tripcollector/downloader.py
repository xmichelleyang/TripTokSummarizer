"""Download TikTok audio (and metadata) with yt-dlp.

Handles both single video URLs and *collection* URLs like
    https://www.tiktok.com/@user/collection/Peru-7681920804111616782
by first expanding them into their member videos.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from tripcollector.utils import ensure_dir, log, slugify

# TikTok now blocks plain HTTP clients; yt-dlp must impersonate a real browser
# (requires the optional ``curl_cffi`` dependency).
IMPERSONATE_ARGS: List[str] = ["--impersonate", "chrome"]


@dataclass
class VideoItem:
    """One TikTok video after download."""

    id: str
    url: str
    title: str
    uploader: str
    description: str
    dir: Path
    audio_path: Optional[Path]
    video_path: Optional[Path]


class DownloadError(RuntimeError):
    pass


def _yt_dlp() -> str:
    exe = shutil.which("yt-dlp")
    if not exe:
        raise DownloadError(
            "yt-dlp not found on PATH. Install it with `pip install yt-dlp`."
        )
    return exe


def _run_json(args: List[str]) -> str:
    """Run yt-dlp and return stdout, raising a helpful error on failure."""
    full = [*IMPERSONATE_ARGS, *args]
    log.debug("yt-dlp %s", " ".join(full))
    proc = subprocess.run(
        [_yt_dlp(), *full],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise DownloadError(
            f"yt-dlp failed ({proc.returncode}): {proc.stderr.strip()[:500]}"
        )
    return proc.stdout


def expand_collection(url: str) -> List[str]:
    """Expand a collection/playlist URL into a list of video URLs."""
    out = _run_json(["--flat-playlist", "-J", url])
    data = json.loads(out)
    entries = data.get("entries") or []
    urls: List[str] = []
    for e in entries:
        vid_url = e.get("url") or e.get("webpage_url")
        vid_id = e.get("id")
        if vid_url and vid_url.startswith("http"):
            urls.append(vid_url)
        elif vid_id:
            # Reconstruct a canonical video URL from an id + uploader.
            uploader = e.get("uploader_id") or e.get("uploader") or ""
            uploader = uploader.lstrip("@")
            if uploader:
                urls.append(f"https://www.tiktok.com/@{uploader}/video/{vid_id}")
    log.info("Collection expanded into %d videos", len(urls))
    return urls


def _looks_like_collection(url: str) -> bool:
    return "/collection/" in url


def gather_urls(
    urls: Optional[List[str]] = None,
    input_file: Optional[Path] = None,
    collection_url: Optional[str] = None,
) -> List[str]:
    """Merge all input sources into a de-duplicated, ordered URL list."""
    collected: List[str] = []

    if collection_url:
        if _looks_like_collection(collection_url):
            collected.extend(expand_collection(collection_url))
        else:
            collected.append(collection_url)

    if input_file:
        for raw in Path(input_file).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if _looks_like_collection(line):
                collected.extend(expand_collection(line))
            else:
                collected.append(line)

    for u in urls or []:
        if _looks_like_collection(u):
            collected.extend(expand_collection(u))
        else:
            collected.append(u)

    # De-duplicate, preserve order.
    seen = set()
    ordered = []
    for u in collected:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


def probe_metadata(url: str) -> dict:
    """Fetch a TikTok's metadata (including subtitle tracks) without media."""
    out = _run_json(["-J", "--skip-download", url])
    return json.loads(out)


# Backwards-compatible private alias.
_probe_metadata = probe_metadata


def write_item_metadata(item_dir: Path, meta: dict, url: str) -> dict:
    """Write ``metadata.json`` and return the normalized fields."""
    vid_id = str(meta.get("id") or slugify(url))
    title = meta.get("title") or meta.get("description") or vid_id
    uploader = meta.get("uploader") or meta.get("uploader_id") or ""
    description = meta.get("description") or ""
    fields = {
        "id": vid_id,
        "url": meta.get("webpage_url") or url,
        "title": title,
        "uploader": uploader,
        "description": description,
        "duration": meta.get("duration"),
    }
    (item_dir / "metadata.json").write_text(
        json.dumps(fields, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return fields


def download_one(
    url: str,
    country_dir: Path,
    keep_video: bool = False,
    force: bool = False,
) -> VideoItem:
    """Download a single TikTok's audio (+ metadata) into its own folder."""
    meta = probe_metadata(url)
    item_dir = ensure_dir(country_dir / str(meta.get("id") or slugify(url)))
    fields = write_item_metadata(item_dir, meta, url)
    vid_id = fields["id"]
    title = fields["title"]

    audio_path = item_dir / "audio.mp3"
    video_path = item_dir / "video.mp4"

    need_audio = force or not audio_path.exists()
    if need_audio:
        args = [
            *IMPERSONATE_ARGS,
            "-x",
            "--audio-format",
            "mp3",
            "-o",
            str(item_dir / "audio.%(ext)s"),
            "--no-playlist",
        ]
        if keep_video:
            args += ["-k"]  # keep intermediate; user can also request mp4
        args.append(url)
        log.info("Downloading audio: %s", title[:70])
        proc = subprocess.run(
            [_yt_dlp(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise DownloadError(
                f"Audio download failed for {url}: "
                f"{proc.stderr.strip()[:400]}"
            )
    else:
        log.info("Audio already present, skipping download: %s", vid_id)

    return VideoItem(
        id=vid_id,
        url=fields["url"],
        title=title,
        uploader=fields["uploader"],
        description=fields["description"],
        dir=item_dir,
        audio_path=audio_path if audio_path.exists() else None,
        video_path=video_path if video_path.exists() else None,
    )
