#!/bin/bash
# pipefail: propagate re_ocr.py's exit code through the `| tee` pipe so a failed
# batch run doesn't look like success to callers/cron.
set -o pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
echo "Running re_ocr.py with caffeinate (Mac will stay awake)..."
echo "Output is logged to re_ocr.log"
echo ""
caffeinate -i python re_ocr.py -n 300 2>&1 | tee re_ocr.log
