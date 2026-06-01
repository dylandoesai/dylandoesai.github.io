#!/usr/bin/env bash
# Fetch a starter Penelope Cruz reference photo from Wikipedia (free,
# CC-BY-SA licensed) into assets/reference/ so you can run
# extract_face_mesh.py without manually hunting for photos.
#
# For best 3D depth, you should still drop 2-4 more photos manually
# (different angles). Just google her name, right-click → save image,
# put them in assets/reference/.

set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p assets/reference

# Wikipedia's REST API: get the lead image of the article.
API="https://en.wikipedia.org/api/rest_v1/page/summary/Pen%C3%A9lope_Cruz"
echo "==> querying Wikipedia for canonical photo"
JSON="$(curl -s -A "PenelopeApp/1.0" "$API")"

# Extract image URL (prefers original over thumbnail)
URL="$(printf '%s' "$JSON" | python3 -c '
import json, sys
data = json.load(sys.stdin)
img = data.get("originalimage") or data.get("thumbnail") or {}
print(img.get("source", ""))
')"

if [ -z "$URL" ]; then
  echo "could not find image URL. Drop photos in assets/reference/ manually."
  exit 1
fi

OUT="assets/reference/wikipedia_lead.jpg"
echo "==> downloading $URL -> $OUT"
curl -s -A "PenelopeApp/1.0" -L -o "$OUT" "$URL"

if [ -s "$OUT" ]; then
  echo "==> ok ($(wc -c < "$OUT") bytes)"
  echo
  echo "Drop 2-4 more photos in assets/reference/ for better 3D depth,"
  echo "then run:  python python/extract_face_mesh.py assets/reference/*"
else
  echo "download failed"; rm -f "$OUT"; exit 1
fi
