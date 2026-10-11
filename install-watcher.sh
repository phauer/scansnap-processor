#!/bin/bash
# Install (or reinstall) the watcher as a macOS LaunchAgent.
#
# Any SCANSNAP_* environment variables set when running this script are baked into
# the agent, e.g.:
#   SCANSNAP_TITLE_DROP_WORDS="Mustermann" ./install-watcher.sh
# Re-run the script to change them (a plain restart doesn't re-read the plist).
#
#   --dry-run   print the generated plist and exit without installing
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
LABEL="local.scansnap-ocr"
GENERATED="$REPO/launchagent.plist"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"

xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

extra_env=""
while IFS='=' read -r name value; do
    [[ "$name" == "SCANSNAP_TITLE_RELEASE" ]] && continue  # already in the template
    extra_env+="        <key>$name</key>"$'\n'
    extra_env+="        <string>$(printf '%s' "$value" | xml_escape)</string>"$'\n'
done < <(env | grep '^SCANSNAP_' | sort || true)

repo_escaped="$(printf '%s' "$REPO" | xml_escape | sed 's/[&|\\]/\\&/g')"
EXTRA_ENV="$extra_env" awk '{ if ($0 ~ /__EXTRA_ENV__/) { sub(/__EXTRA_ENV__/, ""); printf "%s", ENVIRON["EXTRA_ENV"] } print }' \
    "$REPO/launchagent.plist.template" \
    | sed -e "s|__REPO__|$repo_escaped|g" -e "s|__LABEL__|$LABEL|g" > "$GENERATED"
plutil -lint "$GENERATED" > /dev/null

if [[ "${1:-}" == "--dry-run" ]]; then
    cat "$GENERATED"
    exit 0
fi

mkdir -p "$REPO/logs" "$HOME/Library/LaunchAgents"
launchctl unload "$TARGET" 2>/dev/null || true
cp "$GENERATED" "$TARGET"
launchctl load "$TARGET"
echo "Watcher installed and started ($LABEL)."
