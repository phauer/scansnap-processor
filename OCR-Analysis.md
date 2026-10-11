# OCR Quality Analysis: ScanSnap vs Free OCR Engines

**Date:** 2026-03-28
**Goal:** Evaluate ScanSnap's built-in OCR and compare with free alternatives to find the best re-OCR solution for ~100 scanned German documents.

> **Privacy note:** the evaluation ran on real personal documents.
> This public version describes them only by type; names, numbers, addresses and file names are omitted.

---

## 1. Test Setup

### OCR Engines Tested

| Engine | Version | Type | Language Support |
|---|---|---|---|
| **ScanSnap** (built-in) | — | Embedded text layer in PDFs | German |
| **Tesseract** | 5.5.0 | Traditional OCR (Google) | `deu+eng` |
| **EasyOCR** | 1.7.2 | Deep learning (CRAFT + CRNN) | `de+en` |
| **docTR** | 1.0.1 | Deep learning (DBNet + CRNN, PyTorch) | Pretrained (no explicit German) |
| **PaddleOCR** | 3.4.0 | Deep learning (Baidu) | Could not run — `paddlepaddle` has no macOS ARM (M-series) wheel |

### Test Samples (8 documents, diverse types)

| # | Document Type | Key Challenges |
|---|---|---|
| 1 | Medical invoice | Fine print, sidebar barcodes, handwritten date |
| 2 | Taxi receipt | Pre-printed form, **mostly handwritten** |
| 3 | Speeding fine (official letter) | Clean printed official letter, amounts table |
| 4 | Medical form (yellow) | Heavy handwriting, colored background, form fields |
| 5 | Car service receipt | Clean digital-style receipt |
| 6 | Insurance SEPA mandate | Typed form + handwritten date/signature |
| 7 | Moving company quote | Cost table with EUR amounts, handwritten name |
| 8 | Termination letter | Clean printed letter + handwritten signature |

### Methodology

1. Extracted existing ScanSnap text layer from PDFs using `pypdf`
2. Converted each PDF page to 300 DPI PNG using `pymupdf`
3. Ran each OCR engine on the same PNG images
4. Compared output against visually verified ground truth

---

## 2. ScanSnap Built-in OCR Assessment

### Overall: Mixed quality, poor on anything non-trivial

#### Errors Found

**Character confusion (l/1/i/!/parentheses):**
- `Schutzimpfung!intramuskulär` → should be `Schutzimpfung(intramuskulär`
- `vol1.4.Lebensjahr` → should be `voll.4.Lebensjahr`
- `Verkehrsordnungswldrigkeit` → should be `Verkehrsordnungswidrigkeit`
- `Genehm!gungs-Nr.` → should be `Genehmigungs-Nr.`
- `Term!nat-lD` → should be `Terminal-ID`
- `Auto-Tei1e-Unger` → should be `Auto-Teile-Unger`

**Broken/spaced-out words:**
- `T e i l b e r h ä l t`, `T age`, `V erzug`
- `K e n n z e i c h e n`, `1 9 6 8 c c m 1 0 3 K W`
- Street names and house numbers split into single letters

**Garbled text:**
- `TDiePVS` instead of `Die PVS`
- `Rü^ragenjiur` instead of `Rückfragen nur`
- `Sleuernummer` instead of `Steuernummer`
- Place and person names with single wrong letters (e.g. `c` for `d`, `e` for `c`)

**Filename generation from OCR is garbled:**
- A doctor's letterhead ("Dr. med. …, FÄ f. Kinder") became `nr med-… FÄ f. Kinder`

**Complete failures:**
- Taxi receipt: **NO TEXT LAYER AT ALL** — ScanSnap produced zero OCR
- Medical form: Missed all handwritten content (patient name, insurance numbers, diagnosis, therapy notes)
- Page 2 of medical form: Pure garbage from bleed-through text (`5(30)20« rn69)9)riBiäbniX`)

**Random garbage from sidebar elements:**
- Barcodes, QR codes, and margin numbers produce noise characters: `S<LO`, `■«rj-`, `CO`, `fN`, `K>`, etc.

---

## 3. Free OCR Engine Comparison

### Per-Document Results

#### Document 1: Medical Invoice

| Aspect | Tesseract | EasyOCR | docTR |
|---|---|---|---|
| "Die PVS" logo | ✅ correct | ✅ correct | ✅ correct |
| "RECHNUNG" | ❌ `REC HN U NG` | ✅ correct | ✅ correct |
| "Ärztliche" (umlaut) | ❌ `Arztliche` | ✅ `Ärztliche` | ❌ `Arztliche` |
| ICD-10 code (letter + digits) | ❌ letter misread as digit | ✅ correct | ✅ correct |
| Fine print paragraph | garbled | partial garble | **heavily garbled** |
| Handwritten payment note + date | ❌ garbled | ❌ missed | ❌ missed |
| Sidebar garbage | lots | minimal | minimal |

#### Document 2: Taxi Receipt (Mostly Handwritten)

Note: ScanSnap produced **zero text** for this document.

| Aspect | Tesseract | EasyOCR | docTR |
|---|---|---|---|
| Company name header | ❌ missing "Taxi" | ❌ missing "Taxi" | ⚠️ partial |
| Operator stamp (name) | ❌ missed | ✅ partially read | ✅ correct |
| Taxi number (4 digits) | ❌ | ❌ | ❌ |
| Serial number (6 digits) | ❌ | ❌ | ✅ correct |
| Handwritten fare | ❌ | ❌ | ⚠️ misread |
| Route handwriting | ❌ | ❌ | partial attempt |
| Sidebar stamp | garbage chars | garbage chars | clean |

#### Document 3: Speeding Fine (Clean Printed Official Letter)

| Aspect | Tesseract | EasyOCR | docTR |
|---|---|---|---|
| City name (with umlaut) | ✅ correct | ✅ correct | ❌ umlaut dropped |
| "Bußgeldbescheid" | ✅ correct | ✅ correct | ❌ `BuBgeldbescheid` |
| Birthdate | ❌ missed (`..09.`) | ✅ correct | ✅ correct |
| All EUR amounts | ✅ correct | ✅ correct | ✅ correct |
| IBAN | ✅ correct | ✅ correct | ✅ correct |

#### Document 4: Medical Form (Yellow, Heavy Handwriting)

| Aspect | Tesseract | EasyOCR | docTR |
|---|---|---|---|
| Health insurer name | ❌ missed | ✅ correct | ✅ correct |
| Patient name | ❌ missed | ⚠️ one letter wrong | ✅ correct |
| Birthdate | ❌ missed | ⚠️ partial | ⚠️ partial |
| Insurer number (7 digits) | ❌ missed | ✅ correct | ✅ correct |
| Insured-person number (letter + 9 digits) | ❌ missed | ⚠️ partial | ✅ correct |
| Doctor's name ("Dr. med. …") | ❌ missed | ⚠️ garbled | ⚠️ `ß` → `B` |
| Handwritten therapy notes | ❌ nothing | ❌ fragments | ⚠️ fragments |

#### Document 5: Car Service Receipt (Clean Digital Receipt)

All three engines performed well on this clean, high-contrast receipt. Minor differences only in umlaut handling (docTR drops them).

#### Document 6: Insurance SEPA Mandate (Form + Handwritten Date/Signature)

| Aspect | Tesseract | EasyOCR | docTR |
|---|---|---|---|
| Insurer name (all caps, umlaut) | ✅ correct | ✅ correct | ❌ umlaut dropped |
| Street name with "ß" | ⚠️ inconsistent | ✅ correct | ❌ `ß` → `B` |
| IBAN | ✅ correct | ✅ correct | ✅ correct |
| Handwritten date | ❌ garbled | ❌ missed | ❌ missed |

#### Document 7: Moving Quote (Cost Table)

| Aspect | Tesseract | EasyOCR | docTR |
|---|---|---|---|
| All EUR amounts | ❌ **completely missing** | ✅ all correct | ✅ all correct |
| "Kostenübersicht" (umlaut) | ✅ correct | ⚠️ `Kostenubersicht` | ❌ `Kostenubersicht` |
| Total amount | ❌ missing | ✅ correct | ✅ correct |
| Handwritten surname | ❌ garbled | ⚠️ garbled | ⚠️ one letter wrong |

#### Document 8: Termination Letter (Clean Printed Letter + Signature)

| Aspect | Tesseract | EasyOCR | docTR |
|---|---|---|---|
| "Kündigung" | ✅ correct | ✅ correct | ❌ `Kundigung` |
| "Grüßen" | ✅ correct | ✅ correct | ❌ `GruBen` |
| City name (with umlaut) | ✅ correct | ✅ correct | ❌ umlaut dropped |
| Signature (surname) | ⚠️ split + wrong | ⚠️ one letter wrong | ⚠️ one letter wrong |
| Body text accuracy | ✅ perfect | ✅ perfect | ✅ perfect |

---

### Performance

| Engine | Avg. Time/Page | Notes |
|---|---|---|
| Tesseract | ~1.3s | Fastest by far |
| docTR | ~2.8s | Fast, GPU would help |
| EasyOCR | ~18s | Slowest (CPU mode, no GPU) |

---

## 4. Summary Scorecard

| Criterion | Tesseract | EasyOCR | docTR |
|---|---|---|---|
| **German umlauts (ä,ö,ü,ß)** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ (converts all → a,o,u,B) |
| **Printed text accuracy** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Handwriting recognition** | ⭐ | ⭐⭐ | ⭐⭐⭐ |
| **Number/amount extraction** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Form field reading** | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Document structure** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Speed** | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ |

---

## 5. Conclusions

### Key Findings

1. **ScanSnap OCR is mediocre**: Acceptable for simple printed documents but fails on forms, handwriting, and produces many character-confusion errors. One document (taxi receipt) had zero OCR. The filename auto-generation from OCR is often garbled.

2. **docTR is disqualified for German**: Despite excellent structure recognition and the best handwriting capabilities, it **cannot render German umlauts** — every ü→u, ö→o, ä→a, ß→B. This makes it unsuitable as a primary OCR for German documents.

3. **Tesseract has critical blind spots**: It completely missed the entire cost table in the moving quote (zero EUR amounts extracted). It also fails on form fields and handwriting. Its strength is speed and good umlaut support.

4. **EasyOCR is the best overall for German scanned documents**:
   - Preserves umlauts (critical for German)
   - Best at reading form fields and structured data
   - Best at extracting numbers and amounts
   - Reasonable handwriting attempts
   - Main downside: ~18 seconds per page on CPU

5. **No free engine handles handwriting well**: All engines struggle with handwritten content. This is the area where paid vision AI (Claude, GPT-4V) has the biggest advantage.

### Recommendation

**Use EasyOCR as the primary re-OCR engine.** At ~18s/page, processing ~100 PDFs would take approximately 30 minutes — acceptable for a one-time batch job.

A potential **hybrid approach** could combine:
- EasyOCR for form fields, amounts, and structured data
- docTR for handwriting detection (when umlaut-correctness is not needed for that part)
- Post-processing to fix known docTR umlaut issues (regex replacement using context)

### Not Tested (Future Options)

- **PaddleOCR**: Could not install on macOS ARM (Apple Silicon). Might be worth testing on a Linux machine — it's reportedly strong on structured documents.
- **Surya OCR**: A newer open-source OCR engine focused on multilingual support. Worth evaluating.
- **kraken**: Another open-source OCR engine with trainable models.

---

## 6. Re-Evaluation — 2026-06 (local engines, speed + accuracy)

**Why revisit:** EasyOCR's ~18s/page (often slower in practice) and merely-okay quality
prompted a second look. Constraint: **stay local** — these are personal documents (tax,
medical, invoices, contracts), so cloud VLMs (Claude/GPT/Gemini) were ruled out on
privacy grounds despite their strong document-OCR accuracy.

### Candidates (local, Apple Silicon, must emit bounding boxes)

- **Apple Vision framework** (`ocrmac` → `VNRecognizeTextRequest`) — macOS-native,
  Neural-Engine accelerated, returns text + confidence + bounding box, German via
  `de-DE`. No model download.
- **Qwen3-VL via `mlx-vlm`** — local VLM; highest ceiling on hard/handwritten docs,
  but heavy and its grounding-box output is the least robust part. Implemented and
  available (`OCR_ENGINE=qwen3vl`) but not the default.

### Benchmark (same corpus + methodology, via `scripts/ocr_bench.py`)

7 of the original documents (19 pages total), checkpoints = the per-document accuracy
criteria from §3 (umlauts, EUR amounts, IBANs, form fields):

| Engine | Total pages | Avg s/page | Accuracy checkpoints |
|---|---|---|---|
| EasyOCR | 19 | **27.9s** | 10/11 |
| **Apple Vision** | 19 | **0.87s** | **11/11** |

- **~32× faster** (0.87s vs 27.9s per page).
- **At least as accurate** — Apple Vision hit every checkpoint, including the moving-quote
  total + `Kostenübersicht` that EasyOCR missed (1/2 → 2/2).
- Reproduces German umlauts, `€`, amounts, and IBANs cleanly.

### Recommendation (supersedes §5)

**Use Apple Vision as the default engine** (`OCR_ENGINE=apple_vision`). It is faster *and*
at least as accurate on this corpus, fully on-device, and needs no model download.
**EasyOCR remains the cross-platform fallback** (`OCR_ENGINE=easyocr`); **Qwen3-VL**
(`OCR_ENGINE=qwen3vl`) is available for handwriting-heavy work where its higher ceiling
justifies the slower per-page cost. Handwriting is still the universal weak spot — the one
area where (ruled-out) cloud vision AI would help most.

## 7. Apple Vision vs Apple Live Text — Evaluation & Decision (2026-06-11)

> **Decision: keep Apple Vision as the default engine.** Apple Live Text was implemented,
> benchmarked, and kept as a selectable option (`OCR_ENGINE=apple_livetext`), but is **not**
> the default. Rationale below.

Both are local, macOS-native, Neural-Engine-accelerated, and need no model download. The
difference is *granularity*: Vision (`VNRecognizeTextRequest`) returns **one box per line**;
Live Text (VisionKit / `VKCImageAnalyzer`, via ocrmac's LiveText path in `token` mode)
returns **one box per word**. Everything below flows from that one structural difference.

### How they were evaluated

1. **Recognition accuracy** — the 7-doc / 19-page German corpus from §3, scored on the
   per-document checkpoints (umlauts, EUR amounts, IBANs, form fields) via `scripts/ocr_bench.py`.
2. **Recognition speed** — per-page OCR time only, same harness.
3. **Full-pipeline speed** — wall-clock for `embed_text_layer` (render → OCR → embed text
   layer → save) on an 18-page loan contract. This is the time the user
   actually waits.
4. **Copy/search fidelity** — extracted with **PDFKit** (`Quartz.PDFDocument.string()`), the
   *same* engine Preview's Copy and Spotlight use — not just pymupdf, which infers spaces
   differently.
5. **File size** — output bytes + internal object counts (`doc.xref_length()`).

### Side-by-side

| Dimension | Apple Vision (default) | Apple Live Text |
|---|---|---|
| Box granularity | One per **line** | One per **word** |
| Recognition accuracy | 11/11 checkpoints | 11/11 checkpoints — **tied** |
| Recognition speed | ~0.53 s/page | ~0.48 s/page — **tied** (within noise) |
| **Full-pipeline speed** (18p doc) | **25.3 s** (1.40 s/page) | **48.8 s** (2.71 s/page) — **~2× slower** |
| Text blocks embedded (18p doc) | 1,030 | 6,901 (~6.7×) |
| **Output file size** (18p doc) | **~7.1 MB** | ~8.6 MB (~20% larger) |
| Search-highlight alignment | Good (line scaled to box; word positions interpolated) | **Tighter** — each word placed at its own box |
| Copy a paragraph | Clean (line text has real spaces) | Clean **after fix** (see below) |

**Key insight — recognition is tied; the cost is in embedding.** On raw reading speed the two
engines are identical. The full-pipeline gap (25 s vs 49 s) comes *entirely* from embedding
6.7× more text objects and garbage-collecting them on save. Likewise the larger file: more
text objects = more bytes, even after `garbage=4 + deflate`. Both costs are inherent to
word-level granularity, not a bug.

**Copy-paste fix (kept).** Word-level runs initially copied without spaces between words
(`DerDarlehensnehmer…`) because PDFKit/Preview only emit spaces from *explicit* space
characters between separate text runs, not from horizontal gaps. Fixed for all engines by
appending a trailing space to every embedded run (`ocr.py:_insert_invisible_text`); the scale
is computed on the word alone, so the space lands in the inter-word gap and alignment is
unaffected. Verified via PDFKit; regression-tested by
`tests/test_ocr.py::TestTextPositioning::test_adjacent_words_keep_a_space_when_copied`.

### The trade-off, stated plainly

Live Text's *only* win is **tighter search-highlight alignment** (a search for "zins" boxes
the exact word rather than a slightly-off region). For that it costs **~2× processing time**
and **~20% larger files**. Vision's highlights are merely "good" (the line is scaled to its
box, so within-line word positions are interpolated and can sit a little off), but it is
faster and smaller.

### Why Apple Vision was chosen

Decision (2026-06-11): **processing time and file size matter more than precise
search highlights for this workflow.** Searching *within* a document is rare — finding the
right file (by name) is the common operation, and full-text search is a backstop that is
seldom used. Given that, paying ~2× the time and ~20% more disk on every scan to improve a feature
that is rarely exercised is a bad trade. Vision is the better default; the searchable layer it
produces is still fully functional (Spotlight-indexable, copyable) — just with line-level
rather than word-level highlight precision.

### What we kept / when to reconsider

- The `apple_livetext` engine stays in the codebase, fully tested, switchable per-run with
  `SCANSNAP_OCR_ENGINE=apple_livetext` or by setting `OCR_ENGINE` in `config.py` (then
  `./restart-watcher.sh`).
- **Reconsider Live Text** only if precise in-document search/highlight becomes important for
  a specific set of documents — then OCR just those with `apple_livetext`. For everything
  else, Vision is the default and is not expected to change.
- Handwriting remains the universal weak spot of *both* Apple engines; that's the domain for
  the optional `qwen3vl` VLM (or, if the privacy constraint ever relaxes, cloud vision).
