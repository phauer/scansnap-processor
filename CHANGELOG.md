# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
`VERSION` is written into every processed PDF's `producer` metadata, so bump it when OCR output changes.

## [Unreleased]

### Added
- Local LLM titler (`mlx-lm`, Qwen2.5-3B) as the default title engine, with the keyword heuristic as automatic fallback.
- MIT license, CI (lint + non-OCR tests on macOS), `pyproject.toml` with pytest and ruff config.
- `SCANSNAP_FOLDER` and `SCANSNAP_DOCS_DIR` environment variables (defaults under `~/Documents`).
- `install-watcher.sh` generates the LaunchAgent from `launchagent.plist.template`, bakes in any `SCANSNAP_*` variables, and supports `--dry-run`.
- `scripts/ocr_bench.py --checkpoints`: accuracy checkpoints are read from a local, gitignored JSON file (see `bench-checkpoints.example.json`).
- `ocr` pytest marker for tests that run a real OCR engine.

### Changed
- LaunchAgent label is now `local.scansnap-ocr`. Reinstall with `./install-watcher.sh` after removing an agent installed under the old label.
- `TITLE_DROP_WORDS` is empty by default; set `SCANSNAP_TITLE_DROP_WORDS` (e.g. your surname).

## [1.1.0] - 2026-06-10

### Added
- Pluggable OCR engines: Apple Vision (new default, ~32× faster than EasyOCR), Apple Live Text, EasyOCR, Qwen3-VL.
- Benchmark and inventory scripts.

### Fixed
- Copy-paste spacing for word-level OCR, file-size bloat on re-OCR (`garbage=4, deflate=True`).

## [1.0.0] - 2026-03-28

### Added
- Initial pipeline: EasyOCR text layer, date extraction, heuristic titles, folder watcher, batch re-OCR.
