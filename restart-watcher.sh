#!/bin/bash
# Restart the watcher to pick up code changes. To change its environment
# variables, re-run ./install-watcher.sh instead (stop/start doesn't re-read the plist).
launchctl stop local.scansnap-ocr
launchctl start local.scansnap-ocr
echo "Watcher restarted."
