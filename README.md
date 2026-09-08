# TripCollector

Turn TikTok travel collections into organized, per-country trip notes.

TripCollector takes a **TikTok collection URL** or a **list of TikTok video
URLs**, and for each video it:

1. **Downloads** the audio (via `yt-dlp` + `ffmpeg`).
2. **Transcribes** the speech to text (Whisper — local or OpenAI API).
3. **Summarizes** the transcript into travel notes — *where to go, what to
   see, what to eat, and tips* — using an LLM when available, or a built-in
   heuristic extractor as a fallback.

Everything is organized on disk by **country**, because each collection
represents places you want to visit in a particular country.

```
trips/
  Japan/
    7xxxxxxxxxxxxxxxxx/
      metadata.json      # title, uploader, url, description
      audio.mp3          # extracted audio
      transcript.txt     # speech-to-text
      summary.md         # "where to go" travel notes
    _Japan_summary.md    # aggregate of every TikTok in this country
```

---

## Install

Requires **Python 3.9+**, **ffmpeg**, and **yt-dlp** on your PATH.

```powershell
# From the repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`ffmpeg` and `yt-dlp` are external tools:

```powershell
pip install yt-dlp                 # also in requirements.txt
winget install Gyan.FFmpeg         # ffmpeg on Windows
```

### Transcription backends (pick one)

| Backend            | Install                                   | Notes                              |
|--------------------|-------------------------------------------|------------------------------------|
| `faster-whisper`   | `pip install faster-whisper`              | Fast, local, recommended (default) |
| `openai-whisper`   | `pip install openai-whisper`              | Local, pure PyTorch                |
| `openai` (API)     | `pip install openai` + `OPENAI_API_KEY`   | Cloud `whisper-1`, no local model  |

TripCollector auto-detects whichever is installed. Force one with
`--whisper-backend`.

### Summarization backends (auto-detected, in this order)

1. **OpenAI API** — set `OPENAI_API_KEY` (best quality). Model via
   `TRIPCOLLECTOR_OPENAI_MODEL` (default `gpt-4o-mini`).
2. **Heuristic extractor** — always available, no dependencies. Pulls place
   names, food, activities, and tips straight from the transcript.

---

## Usage

Process a text file of TikTok URLs into the `Japan` folder:

```powershell
python -m tripcollector --country Japan --input examples/tiktoks.txt
```

Process a whole TikTok **collection / playlist** URL:

```powershell
python -m tripcollector --country Italy --collection "https://www.tiktok.com/@user/collection/Italy-7xxxxxxxx"
```

Pass URLs directly on the command line:

```powershell
python -m tripcollector --country Thailand --url https://www.tiktok.com/@user/video/123 --url https://www.tiktok.com/@user/video/456
```

### Options

```
--country NAME        Country folder to write into (required).
--input FILE          Text file with one TikTok URL per line (# comments ok).
--collection URL      A TikTok collection/playlist URL to expand.
--url URL             A single TikTok URL (repeatable).
--out DIR             Output root (default: ./trips).
--whisper-backend     auto | faster-whisper | openai-whisper | openai.
--whisper-model       Whisper model size (default: small).
--language CODE       Force transcription language, e.g. en, ja (default: auto).
--force               Re-run every stage even if outputs already exist.
--keep-video          Keep the downloaded mp4 (default: audio only).
--no-summary-index    Do not (re)write the aggregate country summary.
-v, --verbose         More logging.
```

Each stage is idempotent: re-running skips work whose output already exists
(unless `--force`).

---

## Notes & limitations

- Respect TikTok's Terms of Service and only download content you're permitted
  to. This tool is for personal trip planning.
- Downloaded media and generated notes under `trips/` are **git-ignored** so you
  don't commit large/binary files.
- Transcription quality depends on the chosen Whisper model and the audio.
