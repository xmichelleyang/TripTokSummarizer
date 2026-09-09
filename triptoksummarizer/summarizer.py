"""Summarize a TikTok transcript into travel notes ("where to go").

Two backends:
    * OpenAI chat model  -> rich, structured notes (needs OPENAI_API_KEY).
    * Heuristic extractor -> always available, no dependencies; pulls place
      names, food, activities and tips straight from the transcript text.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from triptoksummarizer.utils import log

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def summarize(
    transcript: str,
    title: str,
    country: str,
    url: str = "",
    openai_model: str = "gpt-4o-mini",
) -> str:
    """Return a markdown summary for one TikTok. Falls back to heuristics."""
    transcript = (transcript or "").strip()
    if not transcript:
        return _empty_summary(title, url)

    if os.environ.get("OPENAI_API_KEY"):
        try:
            return _summarize_openai(
                transcript, title, country, url, openai_model
            )
        except Exception as exc:  # noqa: BLE001 - fall back gracefully
            log.warning("OpenAI summary failed (%s); using heuristics.", exc)

    return _summarize_heuristic(transcript, title, country, url)


# ---------------------------------------------------------------------------
# OpenAI backend
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a travel assistant. You are given the transcript of a short "
    "travel TikTok about places to visit in a country. Extract concrete, "
    "actionable trip-planning notes. Be specific: name the exact places, "
    "neighborhoods, restaurants, and activities mentioned. Do not invent "
    "details that are not in the transcript. If information is missing, omit "
    "that section rather than guessing."
)

_USER_TEMPLATE = """Country: {country}
Video title: {title}
Video URL: {url}

Transcript:
\"\"\"
{transcript}
\"\"\"

Write the notes as GitHub-flavored Markdown with EXACTLY these sections
(omit a section only if there is truly nothing to put in it):

## {title}

**Where to go:** a one-sentence summary of the place(s) this video is about.

### Places / neighborhoods
- bulleted list of specific places, landmarks, or areas to visit

### Food & drink
- bulleted list of restaurants, cafes, dishes, or drinks to try

### Things to do
- bulleted list of specific activities or experiences

### Tips
- bulleted list of practical tips (best time, cost, booking, getting there)
"""


def _summarize_openai(
    transcript: str, title: str, country: str, url: str, model: str
) -> str:
    from openai import OpenAI  # type: ignore

    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _USER_TEMPLATE.format(
                    country=country,
                    title=title,
                    url=url,
                    transcript=transcript[:12000],
                ),
            },
        ],
    )
    body = (resp.choices[0].message.content or "").strip()
    return _with_footer(body, url)


# ---------------------------------------------------------------------------
# Heuristic backend
# ---------------------------------------------------------------------------

_FOOD_WORDS = (
    "eat", "restaurant", "cafe", "café", "coffee", "food", "dish", "meal",
    "breakfast", "lunch", "dinner", "brunch", "snack", "drink", "bar",
    "bakery", "street food", "market", "try the", "menu", "delicious",
    "tasty", "cuisine", "wine", "beer", "cocktail",
)
_DO_WORDS = (
    "visit", "see", "go to", "walk", "hike", "tour", "explore", "beach",
    "temple", "shrine", "museum", "park", "view", "viewpoint", "sunset",
    "sunrise", "waterfall", "mountain", "lake", "river", "trail", "ruins",
    "castle", "palace", "cathedral", "church", "old town", "market",
    "boat", "swim", "dive", "snorkel", "climb", "ride", "experience",
)
_TIP_WORDS = (
    "tip", "make sure", "don't", "do not", "avoid", "best time", "book",
    "reserve", "cheap", "expensive", "free", "cost", "price", "budget",
    "bring", "wear", "早", "early", "late", "crowd", "busy", "worth",
    "recommend", "must", "should", "careful", "watch out", "note that",
)

# A capitalized multi-word phrase, optionally joined by lowercase articles.
# Note: no "." inside names, so we never span a sentence boundary.
_PLACE_RE = re.compile(
    r"\b([A-Z][a-zA-Z'’-]+(?:\s+(?:of|the|de|la|el|del|"
    r"[A-Z][a-zA-Z'’-]+))*)\b"
)
# Places introduced by a locative preposition or verb.
_LOCATIVE_RE = re.compile(
    r"\b(?:in|at|to|near|from|visit|explore|go to|head to|check out)\s+"
    r"([A-Z][a-zA-Z'’-]+(?:\s+[A-Z][a-zA-Z'’-]+){0,3})"
)

# Words that should never start/stand as a place name.
_STOPWORDS = {
    "I", "You", "We", "They", "He", "She", "It", "The", "This", "That",
    "These", "Those", "My", "Your", "Our", "Their", "A", "An", "And", "But",
    "So", "If", "When", "Then", "Now", "Here", "There", "Today", "Tomorrow",
    "Okay", "Ok", "Yeah", "Yes", "No", "TikTok", "Instagram", "YouTube",
    "Guys", "Hey", "Let", "Let's", "Don", "Well", "First", "Second", "Third",
    "Number", "One", "Two", "Three", "Also", "Because", "Really", "Just",
    "In", "At", "To", "Near", "From", "Visit", "Explore", "Go", "Head",
    "Check", "Make", "Take", "Get", "Bring", "Wear", "Book", "Try", "See",
    "Do", "Don't", "Next", "Number", "Finally", "Lastly", "Morning",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
    "Sunday",
}

# Lowercased tokens stripped from the trailing edge of a candidate name.
_TRAILING_CONNECTORS = {
    "of", "the", "de", "la", "el", "del", "and", "in", "at", "to", "from",
    "near", "a", "an", "or", "with",
}


@dataclass
class _Buckets:
    places: List[str] = field(default_factory=list)
    food: List[str] = field(default_factory=list)
    do: List[str] = field(default_factory=list)
    tips: List[str] = field(default_factory=list)


def _split_sentences(text: str) -> List[str]:
    # Transcripts are often unpunctuated; split on punctuation AND newlines,
    # then fall back to chunking very long runs by conjunctions.
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    sentences: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > 240:
            sentences.extend(s.strip() for s in re.split(r"\s+(?:and|but|then|so)\s+", p) if s.strip())
        else:
            sentences.append(p)
    return sentences


def _clean_place(candidate: str) -> Optional[str]:
    candidate = candidate.strip(" .,'\u2019-")
    if not candidate:
        return None
    words = candidate.split()
    # Drop leading stopwords like "The", "In", "Visit".
    while words and words[0] in _STOPWORDS:
        words = words[1:]
    # Drop trailing connectors like "and", "of", "the".
    while words and words[-1].lower() in _TRAILING_CONNECTORS:
        words = words[:-1]
    if not words:
        return None
    # Reject if nothing but stopwords remain.
    if all(w in _STOPWORDS for w in words):
        return None
    candidate = " ".join(words)
    if len(candidate) < 3:
        return None
    return candidate


def _extract_places(text: str) -> List[str]:
    found: List[str] = []
    for m in _LOCATIVE_RE.finditer(text):
        c = _clean_place(m.group(1))
        if c:
            found.append(c)
    for m in _PLACE_RE.finditer(text):
        c = _clean_place(m.group(1))
        # Only keep multi-word capitalized names here to reduce noise.
        if c and (" " in c):
            found.append(c)
    return _dedupe_keep_order(found)


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        key = it.lower()
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _classify(sentences: List[str]) -> _Buckets:
    b = _Buckets()
    for s in sentences:
        low = s.lower()
        if any(w in low for w in _TIP_WORDS):
            b.tips.append(s)
        if any(w in low for w in _FOOD_WORDS):
            b.food.append(s)
        if any(w in low for w in _DO_WORDS):
            b.do.append(s)
    b.tips = _dedupe_keep_order(b.tips)[:8]
    b.food = _dedupe_keep_order(b.food)[:8]
    b.do = _dedupe_keep_order(b.do)[:10]
    return b


def _summarize_heuristic(
    transcript: str, title: str, country: str, url: str
) -> str:
    sentences = _split_sentences(transcript)
    places = _extract_places(transcript)[:12]
    buckets = _classify(sentences)

    lines: List[str] = [f"## {title}".rstrip(), ""]

    where = places[0] if places else country
    lines.append(f"**Where to go:** {where} — see details below.")
    lines.append("")
    lines.append("> _Auto-extracted with the heuristic summarizer. Set "
                 "`OPENAI_API_KEY` for richer notes._")
    lines.append("")

    if places:
        lines.append("### Places / neighborhoods")
        lines.extend(f"- {p}" for p in places)
        lines.append("")

    if buckets.do:
        lines.append("### Things to do")
        lines.extend(f"- {_trim(s)}" for s in buckets.do)
        lines.append("")

    if buckets.food:
        lines.append("### Food & drink")
        lines.extend(f"- {_trim(s)}" for s in buckets.food)
        lines.append("")

    if buckets.tips:
        lines.append("### Tips")
        lines.extend(f"- {_trim(s)}" for s in buckets.tips)
        lines.append("")

    body = "\n".join(lines).rstrip()
    return _with_footer(body, url)


def _trim(sentence: str, max_len: int = 200) -> str:
    s = sentence.strip()
    if len(s) > max_len:
        s = s[:max_len].rsplit(" ", 1)[0] + "…"
    return s


def _with_footer(body: str, url: str) -> str:
    footer = ""
    if url:
        footer = f"\n\n---\nSource: {url}\n"
    return body.rstrip() + footer


def _empty_summary(title: str, url: str) -> str:
    body = (
        f"## {title}\n\n"
        "_No transcript was available for this video, so no summary could "
        "be generated._"
    )
    return _with_footer(body, url)
