#!/usr/bin/env bash
# Render the slideshow to a PDF, one slide per page, using the deck's own
# stylesheet so the document matches the site's theme exactly.
#
# The deck is authored as separate scene compositions with no master root, so
# `hyperframes render` would resolve only the first slide. This builds a static
# print sheet from the same slide markup instead, which is also why nothing
# needs a timeline: the reveal animations are authored with
# immediateRender:false, so every element's natural state is its final state.
set -euo pipefail
cd "$(dirname "$0")"

CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[ -x "$CHROME" ] || { echo "Chrome not found. Set CHROME=/path/to/chrome"; exit 1; }

python3 build-print-sheet.py
"$CHROME" --headless --disable-gpu --no-sandbox \
  --run-all-compositor-stages-before-draw --virtual-time-budget=6000 \
  --no-pdf-header-footer \
  --print-to-pdf="$(pwd)/precedent-deck.pdf" \
  "file://$(pwd)/print.html"
echo "wrote $(pwd)/precedent-deck.pdf"
