# TripTokSummarizer

Turn TikTok travel collections into organized, per-country trip notes.

TripTokSummarizer takes a **TikTok collection URL** or a **list of TikTok video
URLs**, and for each video it:

1. **Fetches the transcript** — by default it grabs the video's own **caption
   track** as text (via `yt-dlp`), so there's *no media download and no API
   key*. Optionally (`--source audio`) it downloads the audio and runs Whisper.
2. **Summarizes** the transcript into travel notes — *where to go, what to
   see, what to eat, and tips* — using an LLM when available, or a built-in
   heuristic extractor as a fallback.

Everything is organized on disk by **country**, because each collection
represents places you want to visit in a particular country.

```
trips/
  Japan/
    7xxxxxxxxxxxxxxxxx/
      metadata.json      # title, uploader, url, description
      transcript.txt     # caption text (or Whisper output with --source audio)
      summary.md         # "where to go" travel notes
    _Japan_summary.md    # aggregate of every TikTok in this country
```

---

## Install

Requires **Python 3.9+** and **yt-dlp** on your PATH. (`ffmpeg` is only needed
for the optional `--source audio` path.)

```powershell
# From the repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`requirements.txt` installs `yt-dlp` plus **`curl_cffi`**, which lets yt-dlp
**impersonate a real browser** (`--impersonate chrome`). TikTok now blocks plain
HTTP clients, so this is required for both captions and audio — without it,
yt-dlp requests fail with *"Unexpected response from webpage request."*

## Transcript sources

Choose how each transcript is obtained with `--source`:

| Source              | Default | What it does                                                        | Needs                          |
|---------------------|:-------:|---------------------------------------------------------------------|--------------------------------|
| `captions`          |   ✅    | Fetches the TikTok's caption track as text — **no media download**  | `yt-dlp` + `curl_cffi`         |
| `audio`             |         | Downloads audio and transcribes with local/API Whisper             | `ffmpeg` + a Whisper backend   |

`captions` needs no Whisper backend or ffmpeg and works out of the box. Not
every video has a caption track; those are skipped with a warning.

### Whisper backends — only for `--source audio`

These are **not** installed by default. If you use `--source audio`, install
`ffmpeg` plus one backend:

| Backend            | Install                                   | Notes                              |
|--------------------|-------------------------------------------|------------------------------------|
| `faster-whisper`   | `pip install faster-whisper`              | Fast, local, recommended           |
| `openai-whisper`   | `pip install openai-whisper`              | Local, pure PyTorch                |
| `openai` (API)     | `pip install openai` + `OPENAI_API_KEY`   | Cloud `whisper-1`, no local model  |

TripTokSummarizer auto-detects whichever is installed. Force one with
`--whisper-backend`.

### Summarization backends (auto-detected, in this order)

1. **OpenAI API** — set `OPENAI_API_KEY` (best quality). Model via
   `TRIPTOKSUMMARIZER_OPENAI_MODEL` (default `gpt-4o-mini`).
2. **Heuristic extractor** — always available, no dependencies. Pulls place
   names, food, activities, and tips straight from the transcript.

---

## Getting a collection's video URLs

yt-dlp **cannot expand** a TikTok `/collection/` URL — the collection loads its
items lazily via a *signed* API call, so `--collection` often returns nothing.
The reliable workaround is to grab the URLs from the browser:

1. Open the collection page in your browser and press **F12 → Console**.
2. Paste this snippet — it auto-scrolls to the end and copies every video URL to
   your clipboard:

   ```js
   (async () => {
     const seen = new Set();
     const collect = () =>
       document.querySelectorAll('a[href*="/video/"]').forEach(a => {
         if (a.href.match(/\/video\/\d+/)) seen.add(a.href.split('?')[0]);
       });
     let last = -1, stable = 0;
     while (stable < 6) {
       collect();
       window.scrollTo(0, document.body.scrollHeight);
       await new Promise(r => setTimeout(r, 1300));
       if (seen.size === last) stable++; else { stable = 0; last = seen.size; }
     }
     const urls = [...seen].sort();
     console.log(urls.join('\n') + '\nTOTAL: ' + urls.length);
     copy(urls.join('\n'));   // now on your clipboard
   })();
   ```

3. Paste the URLs into a text file (one per line) and feed it with `--input`.
   See `examples/peru.txt` for a real example.

---

## Usage

Process a text file of TikTok URLs into the `Japan` folder (captions, the
default source):

```powershell
python -m triptoksummarizer --country Japan --input examples/tiktoks.txt
```

Try to expand a TikTok **collection / playlist** URL directly. This is
best-effort — TikTok usually blocks it, so if you get no videos, use the
[console snippet](#getting-a-collections-video-urls) to build an `--input` file
instead:

```powershell
python -m triptoksummarizer --country Italy --collection "https://www.tiktok.com/@user/collection/Italy-7xxxxxxxx"
```

Prefer downloaded audio + Whisper instead of captions:

```powershell
python -m triptoksummarizer --country Japan --input examples/tiktoks.txt --source audio
```

Pass URLs directly on the command line:

```powershell
python -m triptoksummarizer --country Thailand --url https://www.tiktok.com/@user/video/123 --url https://www.tiktok.com/@user/video/456
```

### Options

```
--country NAME        Country folder to write into (required).
--input FILE          Text file with one TikTok URL per line (# comments ok).
--collection URL      A TikTok collection/playlist URL to expand (best-effort;
                      TikTok usually blocks this — see the console snippet).
--url URL             A single TikTok URL (repeatable).
--out DIR             Output root (default: ./trips).
--source SOURCE       captions (default, no download) | audio (download+Whisper).
--whisper-backend     auto | faster-whisper | openai-whisper | openai (audio only).
--whisper-model       Whisper model size (default: small; audio only).
--language CODE       Preferred transcript language, e.g. en, ja (default: auto).
--force               Re-run every stage even if outputs already exist.
--keep-video          Keep the downloaded mp4 (audio source only).
--no-summary-index    Do not (re)write the aggregate country summary.
-v, --verbose         More logging.
```

Each stage is idempotent: re-running skips work whose output already exists
(unless `--force`).

### Re-running a collection that has grown

You can safely re-run TripTokSummarizer on the same `--collection` after adding more
TikToks to it. Videos that were already fully processed are short-circuited
**with no network calls** — TripTokSummarizer derives each video's ID from its URL
and, if that video's `transcript.txt` and `summary.md` already exist on disk,
skips it entirely. So only the newly-added videos are downloaded, transcribed,
and summarized.

Videos whose transcript came back **empty** (the TikTok had no caption track, or
speech-to-text produced no text) are treated as done and are **not** retried on
subsequent runs. They are listed in the run's final summary with the likely
reason, so you can decide whether to re-run those with `--force`.

---

## Notes & limitations

- Respect TikTok's Terms of Service and only use content you're permitted to.
  This tool is for personal trip planning.
- Generated notes under `trips/` are **git-ignored** so you don't commit
  large/binary files.
- The default `captions` source depends on the video having a caption track;
  videos without one are skipped with a warning. Auto-generated captions are
  good but imperfect — set `OPENAI_API_KEY` for cleaner summaries.
- With `--source audio`, transcription quality depends on the chosen Whisper
  model and the audio.
- yt-dlp needs `curl_cffi` for browser impersonation; TikTok requests fail
  without it.
