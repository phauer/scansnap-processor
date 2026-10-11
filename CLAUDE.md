# ScanSnap OCR Processor

## Project Overview

OCR pipeline for ScanSnap image-only PDFs. ScanSnap's built-in OCR was disabled because it produced garbled results for German documents. ScanSnap now outputs image-only PDFs named `yyyyMMddHHmmss.pdf` into the target folder.

This project:
1. OCRs PDFs (de+en) with a pluggable engine — Apple's Vision framework by default (fast, on-device); EasyOCR as fallback
2. Embeds a searchable invisible text layer into each PDF
3. Auto-renames new scans to `YYMMDD meaningful title.pdf`

**Target folder:** `SCANSNAP_FOLDER` (default `~/Documents/ScanSnap Home folder/`, env-overridable).
Only files matching the `yyyyMMddHHmmss.pdf` pattern are "new scans" that need processing; manually named files are left alone.

**This is a public repo that processes private documents.**
Never commit real document content, file names, people's names, birthdates, account/insurance numbers or personal paths — not in code, tests, docs or commit messages.
Use made-up data (`Mustermann`, `Musterstadt`, `12345`) in tests and examples.
Personal, machine-specific notes belong in the gitignored `CLAUDE.local.md`; benchmark checkpoints from real documents go in the gitignored `bench-checkpoints.json`.
`.gitignore` blocks `*.pdf` and `*.log` as a safety net.

## Architecture

```
scansnap_ocr/
├── config.py         # Shared settings (paths, OCR params, OCR_ENGINE, TITLE_ENGINE, patterns); env-overridable
├── ocr.py            # Core: PDF → render 300 DPI → OCR engine → invisible text layer
├── engines/          # Pluggable OCR backends (apple_vision, easyocr, qwen3vl)
├── llm_titler.py     # Local LLM titler (mlx-lm) — reads OCR text → filename title
└── title.py          # Date extraction + title generation (LLM dispatch + heuristic fallback)

scripts/ocr_bench.py          # Benchmark engines on real docs (time + accuracy checkpoints)
scripts/scansnap_inventory.py # Classify ScanSnap PDFs by processing state (read-only)
bench-checkpoints.example.json # Checkpoint format; real ones live in gitignored bench-checkpoints.json

re_ocr.py                  # CLI: batch re-OCR all existing PDFs (no rename)
process_new.py             # CLI: OCR + rename single/all new scans
watcher.py                 # Folder watch daemon (watchdog)
launchagent.plist.template # macOS LaunchAgent template (label local.scansnap-ocr)
install-watcher.sh         # Fills the template (repo path + SCANSNAP_* env), installs + loads it
```

## Background: OCR Engine Choice

See [OCR-Analysis.md](OCR-Analysis.md) for the full engine evaluation across 8 real German documents. Two rounds:
- **2026-03 (free engines):** ScanSnap built-in = mediocre; docTR = disqualified (kills umlauts); Tesseract = fast but misses cost tables/forms; **EasyOCR = best of the free batch** (umlauts, forms, numbers) but ~18s/page on CPU.
- **2026-06 (local re-eval):** **Apple Vision** (macOS-native, via `ocrmac`) matches/beats EasyOCR on the accuracy checkpoints (11/11 vs 10/11) at **~0.9s/page vs ~28s/page** — ~32× faster, on-device, no model download. Now the **default engine**. Cloud VLMs (Claude/GPT) were ruled out: these are personal documents and must stay local.
- **Apple Vision vs Apple Live Text — decided (2026-06-11), see [OCR-Analysis.md](OCR-Analysis.md) §7.** Both tie on recognition accuracy/speed. Live Text gives word-level boxes → tighter search highlights, but costs ~2× full-pipeline time and ~20% larger files (6.7× more text objects to embed). **Decision: stick with Apple Vision** — processing time + file size matter more than in-document search precision (searching within files is rare). `apple_livetext` is kept as a tested, switchable option but is NOT the default; don't change the default without being asked.

## Tech Stack & Environment

- Python 3.14, venv at `.venv/`
- OCR engines are pluggable (`scansnap_ocr/engines/`): `apple_vision` (default, via `ocrmac` + Apple Vision framework), `easyocr` (fallback), `qwen3vl` (optional local VLM via `mlx-vlm`)
- Title LLM: `mlx-lm` (Apple Silicon), default `Qwen2.5-3B-Instruct-4bit` — see Title Generation
- pymupdf (fitz), pypdf, watchdog, tqdm
- pytest for tests
- macOS (Apple Silicon)

## Key Technical Details

- **Engine contract:** Every engine (`scansnap_ocr/engines/`) implements `recognize(image) -> list[(bbox, text, confidence)]`, where `bbox` is a 4-point **pixel polygon** at `OCR_DPI`, origin top-left — identical to EasyOCR's native output. This keeps the text-layer embedding engine-agnostic. `get_engine(name)` is the factory (lazy singleton per engine); `OCR_ENGINE` in config selects the default.
- **Apple Vision bbox conversion:** Vision returns **normalized** (0–1), **bottom-left-origin** boxes. `apple_vision_engine.vision_bbox_to_polygon()` scales by image pixel size and **flips Y** to the canonical polygon. This is the main correctness risk and is unit-tested in `tests/test_engines.py`.
- **pymupdf save quirk:** Cannot `doc.save()` to the same filename non-incrementally. `ocr.py` saves to a temp file then `os.replace()`. This was a bug we fixed.
- **Save with `garbage=4, deflate=True`:** Each text block is written via its own `TextWriter` (for per-block horizontal scaling), which creates many duplicate font/resource objects — thousands for word-level engines like Live Text. Plain `doc.save()` doesn't dedup or compress, so files balloon (Live Text 18-page doc was 13.6 MB; with garbage+deflate 8.6 MB) and re-OCR accumulates orphans. `garbage=4` dedups identical objects + drops orphans; `deflate` compresses streams. Regression-tested by `TestSaveHygiene`.
- **Word-level vs line-level file size:** Even after garbage collection, word-level engines (Live Text token mode, ~1 text object per word) produce somewhat larger files than line-level (Vision, ~1 per line) — inherent to the finer granularity, the cost of tighter highlight alignment.
- **Validating copy/search behavior — use PDFKit, not pymupdf.** How text *copies* and *searches* depends on the extractor. `pymupdf.get_text()` infers inter-word spaces from gaps; **macOS Preview/Spotlight use PDFKit**, which only emits spaces from explicit space chars. To check what the user actually experiences, extract via `Quartz.PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(p)).pageAtIndex_(i).string()` (pyobjc, `Quartz` available). This is how the word-level copy-spacing bug was found and verified; the regression test is Quartz-guarded (`pytest.importorskip("Quartz")`).
- **Big-file behavior (Apple Vision):** ~1.15 s/page, peak RAM ~1.3 GB even at 165 pages (pages are rendered one at a time, so memory is bounded by page size, not document length). The text layer adds only ~4% to image-heavy scans. The old `--max-pages` skip limit is obsolete.
- **Text layer embedding:** Uses `fitz.TextWriter` with `render_mode=3` (invisible) and `opacity=0`. Text is positioned at the engine's bbox coordinates, scaled by `72/300` (PDF points / DPI).
- **Re-OCR flow:** Render page to image FIRST (captures visual content), THEN remove existing text layer with redactions (`images=fitz.PDF_REDACT_IMAGE_NONE`), THEN insert new OCR text. Order matters.
- **OCR speed:** ~0.9s/page (Apple Vision, default). EasyOCR fallback ~18–30s/page on CPU (model load ~5–10s on first call).

## Title Generation

Title (sender + type + subject) and date are produced **separately**. `generate_title()`
in `title.py` is a dispatcher on `TITLE_ENGINE`:

- **`llm` (default) — `scansnap_ocr/llm_titler.py`.** A small local LLM (`mlx-lm`,
  Apple Silicon; default `Qwen2.5-3B-Instruct-4bit`, ~2 GB, ~3s/doc) reads the OCR
  text and returns a German title in *sender → type → subject* order — the way
  people name files manually. Runs fully on-device (privacy: cloud APIs are ruled out).
  Model downloaded on first use; lazy-loaded and kept resident via a process-wide
  singleton (`get_titler()`). Larger model via `SCANSNAP_TITLE_MODEL` (e.g.
  `Qwen2.5-7B-Instruct-4bit`, ~4.5 GB — heavy for the 24/7 watcher on 16 GB, so
  **not** the default).
  - **RAM release (16 GB machines):** the watcher sets `SCANSNAP_TITLE_RELEASE=1` (in
    the plist's `EnvironmentVariables`) so `generate_llm_title()` calls `LlmTitler.unload()`
    after each scan — frees the ~1.7 GB, reloads in ~0.9s next time (files stay in OS
    cache). CLI runs leave it off so the model stays resident across a batch. **Changing
    the watcher's env vars needs a reinstall** (`./install-watcher.sh`, which unloads and
    reloads), not just `restart-watcher.sh` (stop/start doesn't re-read the plist).
  - **Why the LLM:** the keyword heuristic (below) can't comprehend documents — on
    the manual-name corpus it picks noise lines as the "sender" and force-appends
    "Rechnung" + a random context word. The LLM identifies the real sender, type,
    and subject. This was the fix for "I have to correct the name most of the time."
  - **Prompt/cleaning are pure & unit-tested** (`build_messages`, `clean_llm_title`)
    without loading a model. Cleaning strips label prefixes/quotes, turns underscores
    → spaces, splits *long* CamelCase (>12 chars, so `GmbH`/`AG` survive), removes
    unsafe chars, caps words. Few-shot examples avoid rare product nouns (an early
    draft leaked "Kallax" into unrelated titles). Cleaning also collapses adjacent
    duplicate words and strips `TITLE_DROP_WORDS` (default empty; set via
    `SCANSNAP_TITLE_DROP_WORDS`, typically the user's surname — the recipient is on
    nearly every doc and is noise). The 3B ignores the prompt's "nenne den Absender,
    nicht den Empfänger", so the drop-list is the reliable fix.
  - **Graceful fallback:** `generate_llm_title()` never raises — returns `None` on
    any failure (mlx-lm missing, non-macOS, download error) → dispatcher uses the
    heuristic. So `TITLE_ENGINE=llm` is safe even without the model.
- **`heuristic` — `heuristic_title()` in `title.py`.** Keyword fallback:
  1. **Document type** — keyword matching (Rechnung, Quittung, Bußgeldbescheid, Mitteilung, Vertrag, etc.)
  2. **Sender** — regex for company suffixes (GmbH, AG, e.V.) in top ~20% of page 1
  3. **Context** — optional distinctive keyword (Mandatsreferenz, Impfung, Miete, etc.)

**Date** — prefers dates near top of document, falls back to scan date from filename. The LLM is **not** used for the date.
**Filename:** `YYMMDD Title.pdf`, conflicts resolved with `_001` suffix.

### Naming Convention (the Target)

The titler aims to reproduce how files are named by hand:
- Order: **sender/vendor → document type → subject/topic**.
- The recipient's surname is on nearly every document and is noise → strip it via `TITLE_DROP_WORDS`.
- Hand-picked names often add **context that isn't in the document** (where, why, a personal note).
  The titler will never produce these; the goal is to get sender/type/subject right so corrections are rare.

The maintainer's personal conventions (with real examples) live in the gitignored `CLAUDE.local.md`.

### Evaluating Title Quality

The manually-named files **are the ground-truth corpus**. To measure a title change: extract each PDF's existing OCR text layer (`fitz` → `page.get_text()`), run the candidate titler, and compare against the manual name (strip the date prefix). A token-overlap (Jaccard) score is a *weak* proxy — it penalizes the LLM for adding useful words the terse manual name omits — so **read the qualitative before/after, don't just trust the number**. ~110 docs at ~3-5s each ≈ 6-8 min; run it in the background. (This is how the LLM-vs-heuristic decision was validated.)

## Known Limitations

- OCR engines may misread stylized logos (e.g., "DSL|Bank" → "DSLI Bank"). Body text is usually correct.
- No engine handles handwriting reliably; `qwen3vl` has the highest ceiling there but is slow and its grounding boxes are the least robust part of the integration.
- Apple Vision is the default but is **macOS-only**; on other platforms set `OCR_ENGINE=easyocr`.
- Titles are LLM-generated by default (`mlx-lm`, macOS/Apple Silicon only). On other platforms or without the model, set `TITLE_ENGINE=heuristic`. The LLM can still miss personal context people add by hand (people's names not in the text, private notes like "delete after reimbursement") and occasionally mis-reads a logo/sender; multi-document bundles ("… Alle") are inherently hard.

## Development Rules

- **Always add tests** for every code change. Don't wait to be asked.
- **Always update README.md** when changing CLI behavior, parameters, or usage of any script.
- **Keep personal data out of the repo** (see the warning at the top). Before committing, check the diff for real names, numbers, paths or document content.

## Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

Embedding-contract tests are parametrized across every installed engine. With the default Apple Vision engine they run in seconds; the EasyOCR-parametrized variants add a few minutes (model load + ~18–30s/page). Non-OCR tests run in <2s.

The `apple_livetext` engine is **excluded from the parametrized suite by default**: its VisionKit LiveText path aborts the whole pytest process (a C-level crash in `VisionKitCore`, not a catchable exception) on some macOS versions. Opt in with `SCANSNAP_TEST_LIVETEXT=1 python -m pytest tests/test_ocr.py` when you specifically want to exercise it. It remains a fully supported, switchable production engine.

The LLM titler's model-backed test is opt-in: `SCANSNAP_TEST_LLM=1 python -m pytest tests/test_llm_titler.py` (loads/downloads the model). Its pure helpers (prompt building, output cleaning) and the `generate_title` dispatch/fallback are always tested without a model.

**OCR tests need a Metal GPU.** Apple Vision returns no text in headless/sandboxed macOS sessions ("No Metal device available"); run the OCR-touching tests in a normal (non-sandboxed) session.
They are marked `@pytest.mark.ocr`; CI runs `pytest -m "not ocr"`.

## Deployment

The watcher is a long-running LaunchAgent (`local.scansnap-ocr`) that imports the code at startup.
**After changing any `scansnap_ocr`/`watcher.py`/`process_new.py` code, restart it:** `./restart-watcher.sh`.
To change its environment variables, re-run `./install-watcher.sh` (with the `SCANSNAP_*` vars set).
