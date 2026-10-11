# ScanSnap OCR Processor

**Turns image-only ScanSnap scans into searchable PDFs with meaningful file names — fully on-device.**

ScanSnap's built-in OCR is weak on German documents (garbled umlauts, missed forms and handwriting).
This tool takes over: you switch ScanSnap's OCR off, and every new scan is OCR'd locally, gets an invisible searchable text layer, and is renamed from `20260328111052.pdf` to something like `260317 Stadtwerke Rechnung Strom.pdf`.

- **Searchable text layer** — Spotlight, Raycast and Preview can find and copy the text.
- **Smart file names** — a small local LLM reads the document and names it *date + sender + document type + subject*.
- **Hands-off** — a folder watcher processes new scans as they arrive and sends a macOS notification.
- **Pluggable OCR** — Apple's native **Vision** framework by default (~0.9 s/page, Neural-Engine accelerated), **EasyOCR** as a cross-platform fallback. See [OCR-Analysis.md](OCR-Analysis.md) for the engine comparison.

## Privacy

Everything runs on your Mac.
OCR uses Apple's on-device frameworks, and the title LLM runs locally via [MLX](https://github.com/ml-explore/mlx).
No document content is sent to any cloud service.
Model weights are downloaded once from Hugging Face on first use.

## Who It's For

- macOS on **Apple Silicon** (Apple Vision and MLX are macOS/Apple Silicon only; see [Configuration](#configuration) for the cross-platform fallbacks).
- A ScanSnap scanner (tested with the iX1600 and ScanSnap Home), but any image-only PDFs named `yyyyMMddHHmmss.pdf` work.
- **Tuned for German documents:** OCR languages are German + English, and titles are generated in German with German document types (Rechnung, Bescheid, Vertrag …).
  Other languages need small code changes (see [Configuration](#configuration)).

> **Heads-up:** the tool modifies PDFs in place and renames them.
> Try it on a copy of a few scans first, and keep a backup of your documents.

## Setup

### Prerequisites

- **Python 3.14** (with `venv`)
- **Homebrew** — for installing `terminal-notifier`
- **terminal-notifier** — for macOS desktop notifications from the watcher

```bash
brew install terminal-notifier
```

After installing, send a test notification so macOS registers the app:

```bash
terminal-notifier -title "Test" -message "Hello"
```

Then go to **System Settings > Notifications > terminal-notifier** and make sure notifications are **allowed**. Without this, the watcher's notifications will be silently dropped.

### ScanSnap Settings

In your ScanSnap Home scan profile, turn off text recognition (searchable PDF) and keep the default date-time file name (`yyyyMMddHHmmss.pdf`), saving into one folder.
Option names vary between ScanSnap Home versions.
The default folder is `~/Documents/ScanSnap Home folder/`; set `SCANSNAP_FOLDER` if yours differs.

### Python Environment

```bash
git clone https://github.com/phauer/scansnap-processor.git
cd scansnap-processor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The default Apple Vision engine needs no model download (it ships with macOS). If you switch to the EasyOCR fallback, the first run downloads its models (~100 MB) and caches them.
The title LLM (~2 GB) is downloaded on the first scan.

### Quick Start

```bash
# Try it on a copy of one scan
cp "$HOME/Documents/ScanSnap Home folder/20260328111052.pdf" /tmp/
python process_new.py /tmp/20260328111052.pdf

# Then install the watcher so new scans are processed automatically
SCANSNAP_TITLE_DROP_WORDS="Mustermann" ./install-watcher.sh
```

## Scripts

### `re_ocr.py` — Batch Re-OCR

Re-OCR ScanSnap PDFs listed in `scansnap-pdfs.md`. Uses the markdown file as both input and progress tracker — each processed file is marked `[x]`, so the script can be aborted and resumed at any time.

#### Generating the file list

`scansnap-pdfs.md` is gitignored (contains personal file names). Paths in it are relative to `SCANSNAP_DOCS_DIR` (default `~/Documents`). To regenerate it, run:

```bash
python -c "
import fitz, os
from pathlib import Path

docs = Path(os.path.expanduser('~/Documents'))
files = []
for root, dirs, filenames in os.walk(docs):
    dirs[:] = [d for d in dirs if not d.startswith('.')]
    for f in sorted(filenames):
        if f.lower().endswith('.pdf'):
            path = os.path.join(root, f)
            try:
                doc = fitz.open(path)
                creator = doc.metadata.get('creator', '')
                pages = doc.page_count
                doc.close()
                if 'ScanSnap' in creator:
                    rel = './' + os.path.relpath(path, docs)
                    files.append((rel, pages))
            except: pass

with open('scansnap-pdfs.md', 'w') as out:
    out.write('# ScanSnap PDFs in ~/Documents\n\n')
    out.write(f'**Total: {len(files)} files**\n\n')
    total_pages = sum(p for _, p in files)
    for rel, pages in files:
        out.write(f'- [ ] {rel} ({pages}p)\n')
    out.write(f'\n**Total pages: {total_pages}**\n')
print(f'Found {len(files)} files, {total_pages} pages')
"
```

This scans `~/Documents` for PDFs with `ScanSnap` in the `creator` metadata field.

#### Running

```bash
# Process all pending files (skips PDFs with >8 pages by default)
python re_ocr.py

# Process only the next 5 files (then stop)
python re_ocr.py -n 5

# Include large PDFs up to 50 pages
python re_ocr.py --max-pages 50

# Use a different list file
python re_ocr.py /path/to/list.md -n 10
```

#### Overnight runs

Use the convenience wrapper that prevents macOS from sleeping:

```bash
./run-re-ocr.sh
```

This uses `caffeinate -i` to keep the Mac awake for the duration of the script. Output is logged to `re_ocr.log`. You can pass arguments through, e.g. `./run-re-ocr.sh --max-pages 50`.

Progress is tracked in the markdown file itself:
```markdown
- [x] ./folder/done.pdf (3p)
- [x] ./folder/also_done.pdf (1p)
- ./folder/still_pending.pdf (2p)    ← resumes here
```

**Estimated time:** ~0.9s per page with Apple Vision (the default). The EasyOCR fallback is ~18–30s per page on CPU.

**Exit code:** `re_ocr.py` exits `1` if any file failed to process (so `run-re-ocr.sh` and cron can detect it — the wrapper uses `set -o pipefail` to preserve it through `tee`). Files listed but no longer on disk are a soft skip and do **not** trigger a non-zero exit. `process_new.py` in batch mode likewise exits `1` if any scan failed.

### `process_new.py` — OCR + Rename

OCR a new ScanSnap scan and rename it to `YYMMDD Title.pdf`.

```bash
# Process a specific file
python process_new.py "$HOME/Documents/ScanSnap Home folder/20260328111052.pdf"

# Process all unprocessed scans in the default folder
# (files matching the yyyyMMddHHmmss.pdf pattern)
python process_new.py
```

**Pipeline:**
1. Embeds searchable text layer via the configured OCR engine (Apple Vision by default)
2. Extracts the document date from OCR text (falls back to scan date from filename)
3. Generates a title from the OCR text — by default a local on-device LLM reads the document (sender → type → subject), with a keyword heuristic as automatic fallback (see [How Title Generation Works](#how-title-generation-works))
4. Renames to `YYMMDD Title.pdf` (handles filename conflicts with `_001` suffix)

**Example:** `20260328111052.pdf` → `260317 Deutsche Bank Mitteilung Mandatsreferenz.pdf`

### `watcher.py` — Folder Watch Daemon

Monitors the ScanSnap folder and auto-processes new scans as they appear. Sends macOS notifications when processing starts and finishes — clicking the "Done" notification reveals the file in Finder.

```bash
# Run manually
python watcher.py
```

#### Installing as LaunchAgent

Use the included helper script to install the watcher as a macOS LaunchAgent (starts on login, auto-restarts on crash):

```bash
./install-watcher.sh

# With settings baked into the agent (any SCANSNAP_* variable, see Configuration):
SCANSNAP_TITLE_DROP_WORDS="Mustermann" SCANSNAP_FOLDER="$HOME/Scans" ./install-watcher.sh

# Preview the generated plist without installing:
./install-watcher.sh --dry-run
```

This generates `launchagent.plist` from `launchagent.plist.template` (filling in the repo path and any `SCANSNAP_*` environment variables), copies it to `~/Library/LaunchAgents/local.scansnap-ocr.plist`, and loads the agent.
Re-run it whenever you want to change the watcher's settings.

#### Managing the watcher

```bash
# Restart (picks up code changes; NOT env var changes — re-run install-watcher.sh for those)
./restart-watcher.sh

# Check status
launchctl list | grep scansnap

# Stop
launchctl stop local.scansnap-ocr

# Uninstall
launchctl unload ~/Library/LaunchAgents/local.scansnap-ocr.plist
rm ~/Library/LaunchAgents/local.scansnap-ocr.plist
```

The watcher:
- Triggers only on new `yyyyMMddHHmmss.pdf` files in the root folder
- Waits for the file to finish writing before processing
- Ignores non-PDFs, subdirectories, and already-renamed files
- Shows macOS notifications on start/finish of processing
- Logs to `logs/` in the repo directory

### Utility scripts (`scripts/`)

```bash
# Inventory all ScanSnap PDFs under ~/Documents and classify each by processing
# state (never / easyocr / apple_vision / apple_livetext). Read-only; writes a
# reviewable overview to scansnap-inventory.md. Use before a re-OCR batch.
python scripts/scansnap_inventory.py

# Benchmark OCR engines on real documents (per-page time + accuracy checkpoints).
python scripts/ocr_bench.py DOC1.pdf DOC2.pdf ... --engines apple_vision apple_livetext
```

Accuracy checkpoints are strings that must appear in a correct transcription, keyed by a substring of the file name.
They come from your own documents, so they live in the gitignored `bench-checkpoints.json`.
Copy `bench-checkpoints.example.json` to start; without the file the benchmark measures speed only.

To re-OCR a set of files, generate `scansnap-pdfs.md` (a `- [ ] ./rel (Np)` checklist —
see *Generating the file list* above, or filter `scansnap_inventory.py`'s scan to the
stale states), then run `re_ocr.py --max-pages <N>` (resumable).

## PDF Metadata

Processed PDFs are tagged with metadata to identify them:

- **`producer`** is set to `scansnap-processor v<VERSION> (<engine>)` (e.g. `... (AppleVision)`). This identifies the file as processed by this pipeline, which version, and which OCR engine was used. Useful for detecting files that need re-processing after an OCR logic or engine update.
- **`creator`** is preserved from the original PDF. ScanSnap sets this to `ScanSnap Home #iX1600 (W)`, which can be used to find all ScanSnap-scanned PDFs across your filesystem.

The version is defined in `scansnap_ocr/config.py` (`VERSION`). Bump it when OCR logic changes.

## Spotlight / Raycast Search

The embedded OCR text layer makes PDFs searchable via **Spotlight** and tools that use it (e.g. **Raycast File Search**). Spotlight's PDF importer reads the text from our invisible layer — you can verify with:

```bash
mdimport -t -d3 "/path/to/file.pdf" 2>&1 | grep kMDItemTextContent
```

### Troubleshooting: Search returns no results

If Raycast/Spotlight stops finding PDFs by content, the Spotlight index may be broken. Check with:

```bash
mdutil -as                    # Check indexing state for all volumes
mdfind -onlyin ~/Documents "search term"   # Test if Spotlight finds anything
```

If the state shows "unknown" or `mdfind` returns nothing, rebuild the index:

```bash
sudo mdutil -Eai off          # Erase index and disable indexing
sudo mdutil -Eai on           # Re-enable indexing (triggers full rebuild)
mdutil -as                    # Monitor progress
```

Re-indexing runs in the background and takes 30–60 minutes depending on file count.

## Testing

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

Tests use generated synthetic PDFs. OCR-touching tests need a Metal GPU (Apple Vision returns nothing in headless/sandboxed sessions).
They are marked `ocr`; run everything else with `python -m pytest -m "not ocr"` (this is what CI does).

Two engine/model tests are opt-in via environment variables:

```bash
# Exercise the Apple Live Text engine (excluded by default — it can crash the
# pytest process on some macOS versions):
SCANSNAP_TEST_LIVETEXT=1 python -m pytest tests/test_ocr.py

# Exercise the LLM titler against the real model (downloads it on first run):
SCANSNAP_TEST_LLM=1 python -m pytest tests/test_llm_titler.py
```

## Configuration

Most settings can be changed with environment variables (for the watcher, pass them to `./install-watcher.sh`).
The rest live in `scansnap_ocr/config.py`.

| Setting | Env Var | Default | Description |
|---|---|---|---|
| `SCANSNAP_FOLDER` | `SCANSNAP_FOLDER` | `~/Documents/ScanSnap Home folder/` | Folder ScanSnap saves new scans to (watched folder) |
| `DOCS_DIR` | `SCANSNAP_DOCS_DIR` | `~/Documents` | Root for the relative paths in `scansnap-pdfs.md` (`re_ocr.py`) |
| `OCR_ENGINE` | `SCANSNAP_OCR_ENGINE` | `"apple_vision"` | OCR backend: `apple_vision`, `apple_livetext`, `easyocr`, or `qwen3vl` |
| `TITLE_ENGINE` | `SCANSNAP_TITLE_ENGINE` | `"llm"` | Title backend: `llm` (local LLM, falls back to heuristic) or `heuristic` |
| `TITLE_LLM_MODEL` | `SCANSNAP_TITLE_MODEL` | `Qwen2.5-3B-Instruct-4bit` | MLX model for the LLM titler |
| `TITLE_LLM_MAX_CHARS` | `SCANSNAP_TITLE_MAX_CHARS` | `2500` | OCR characters sent to the LLM |
| `TITLE_DROP_WORDS` | `SCANSNAP_TITLE_DROP_WORDS` | empty | Comma-separated words stripped from titles — typically your surname, which appears as the recipient on nearly every document |
| `TITLE_LLM_RELEASE_AFTER_USE` | `SCANSNAP_TITLE_RELEASE` | off (`1` in the watcher) | Free the model from RAM after each title; off for CLI so batch runs stay resident |

Only in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `OCR_LANGUAGES` | `["de", "en"]` | EasyOCR languages. Apple Vision/Live Text use `VISION_LANGUAGES` (`de-DE`, `en-US`) in `engines/apple_vision_engine.py`. |
| `OCR_DPI` | `300` | Render resolution for OCR |
| `MAX_TITLE_WORDS` | `6` | Max words in a heuristic-generated title |
| `FALLBACK_TITLE` | `"Scan"` | Title when generation fails |

**Other languages:** besides the OCR languages above, the LLM prompt and few-shot examples (`llm_titler.py`) and the heuristic keywords (`title.py`) are German.
Translating those is the main work for another language.

**Not on Apple Silicon:** set `SCANSNAP_OCR_ENGINE=easyocr` and `SCANSNAP_TITLE_ENGINE=heuristic`.
The watcher's notifications and LaunchAgent remain macOS-only.

## OCR Engines

The OCR backend is pluggable (`scansnap_ocr/engines/`). Every engine returns the same
`(bbox, text, confidence)` shape, so the searchable-text-layer embedding is engine-agnostic.

| Engine | Key | Notes |
|---|---|---|
| **Apple Vision** (default) | `apple_vision` | macOS-native (`ocrmac` + Vision framework), Neural-Engine accelerated, ~0.5–0.9s/page, no model download. One box per line. |
| **Apple Live Text** | `apple_livetext` | macOS Sonoma+ (`ocrmac` LiveText path). Same speed/accuracy as Vision on the benchmark, but returns **word-level** boxes → tighter search-highlight alignment. |
| **EasyOCR** | `easyocr` | Cross-platform fallback (deep learning, CPU), ~18–30s/page. |
| **Qwen3-VL** | `qwen3vl` | Local vision-language model via `mlx-vlm` (optional, large download). Highest ceiling on hard/handwritten docs; slower. |

Switch engines without code changes via the environment variable (default is `apple_vision`):

```bash
SCANSNAP_OCR_ENGINE=apple_livetext python process_new.py "/path/to/scan.pdf"
```

or change `OCR_ENGINE` in `scansnap_ocr/config.py`. See [OCR-Analysis.md](OCR-Analysis.md)
for the full engine comparison and benchmark.

## How Title Generation Works

The **title** (sender + document type + subject) and the **date** are generated separately.

### Title — Local LLM (Default)

`TITLE_ENGINE=llm` (the default) sends the OCR text of the first pages to a small
**on-device LLM** (`mlx-lm`, Apple Silicon) that reads the document and returns a
concise German title in the form *sender → document type → subject*, matching the
way files are named by hand. It runs fully locally — personal documents never leave
the machine — and downloads a quantized model (~2 GB) on first use.

- **Default model:** `mlx-community/Qwen2.5-3B-Instruct-4bit` (~1.7 GB RAM, ~3s/doc) —
  a good balance of quality, speed, and memory for the 24/7 watcher. The watcher frees
  the model after each scan (`SCANSNAP_TITLE_RELEASE=1`), reloading in ~0.9s next time,
  so idle RAM stays at baseline; CLI batch runs keep it resident across files.
- **Higher quality:** set `SCANSNAP_TITLE_MODEL=mlx-community/Qwen2.5-7B-Instruct-4bit`
  (~4.5 GB RAM, ~8s/doc) for noticeably better comprehension.
- The raw model output is cleaned (label prefixes, quotes, underscores, mashed
  CamelCase, unsafe characters, adjacent duplicate words) and capped in length. Words
  in `TITLE_DROP_WORDS` (e.g. your surname — it appears as the recipient on nearly
  every document and is noise) are stripped.

If the LLM is unavailable (not installed, non-macOS, download fails) or returns
nothing, title generation **falls back automatically to the keyword heuristic** —
no configuration needed. To skip the LLM entirely, set `TITLE_ENGINE=heuristic`.

### Title — Keyword Heuristic (Fallback)

1. **Document type** — keyword matching: Rechnung, Quittung, Bußgeldbescheid, Mitteilung, Vertrag, etc.
2. **Sender** — looks for company suffixes (GmbH, AG, e.V.) in the top ~20% of page 1, falls back to first prominent text line
3. **Context** — optional keyword that adds meaning (Mandatsreferenz, Impfung, Miete, Strom, etc.)

### Date

**Date** — prefers dates found near the top of the document (`DD.MM.YYYY`, `DD.MM.YY`, `D. Monat YYYY`), falls back to scan date from the original filename. (The LLM is not used for the date.)

## License

[MIT](LICENSE) © 2026 Philipp Hauer
