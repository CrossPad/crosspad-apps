#!/bin/bash
# The installer from this checkout in a clean ubuntu:24.04: fresh with both
# extras, broken on purpose, an ESP-IDF 5.5 from EIM, a foreign ESP-IDF named
# by CROSSPAD_IDF_DIR, then the commands in a new terminal (scenario.sh).
# Logs in $LINUXTEST_HOME (default ~/.cache/crosspad-linuxtest). ~30 minutes.
set -e
R="$(cd "$(dirname "$0")" && pwd)"
W="${LINUXTEST_HOME:-$HOME/.cache/crosspad-linuxtest}"
mkdir -p "$W"
rm -f "$W"/[0-9]*.log "$W"/[0-9]*.txt "$W/finished"
cp "$R/../../install.sh" "$R/scenario.sh" "$W/"
docker --context default rm -f crosspad-linuxtest >/dev/null 2>&1 || true
# platform-idf is private until the OS release: the token signs gh in inside.
GH_TOKEN="${GH_TOKEN:-$(gh auth token)}" docker --context default run --rm --name crosspad-linuxtest \
    -e GH_TOKEN -v "$W:/inst" ubuntu:24.04 bash /inst/scenario.sh
for f in "$W"/[0-9]*.log; do
    printf '%-24s %s\n' "$(basename "$f")" "$(grep -hE '^(exit|doctor exit)=' "$f" | tr '\n' ' ')"
done
