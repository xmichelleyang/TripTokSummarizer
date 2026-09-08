"""Small shared helpers: logging, slugs, safe filesystem names."""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("tripcollector")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


_slug_re = re.compile(r"[^a-zA-Z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    """Turn arbitrary text into a safe, compact slug."""
    slug = _slug_re.sub("-", text.strip().lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "item"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
