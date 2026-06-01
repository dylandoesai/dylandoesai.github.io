#!/usr/bin/env bash
# Penelope one-shot setup. Run from penelope/ root:  ./scripts/setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# --- prerequisites ------------------------------------------------------
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1"; exit 1; }; }

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Install from https://brew.sh and retry."
  exit 1
fi

echo "==> installing system deps via brew"
brew install --quiet node@20 python@3.11 portaudio ffmpeg cmake || true

# Claude Code (your Max plan)
if ! command -v claude >/dev/null 2>&1; then
  echo "==> installing claude code"
  brew install anthropic/claude/claude || true
fi

echo "==> npm install"
npm install --silent

echo "==> creating Python venv"
python3.11 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> pip install"
pip install --upgrade pip
pip install -r python/requirements.txt

# vendor three.js as a single ES module so the renderer can import it
# offline (we use importmap -> ./vendor/three.module.js).
echo "==> vendoring three.module.js"
mkdir -p renderer/vendor
cp node_modules/three/build/three.module.js renderer/vendor/three.module.js

# Required directories
mkdir -p assets/reference assets/owner_faces assets/songs

# Local config (gitignored). Seed from the example template on first run
# so the app has something to read; the user fills in real keys after.
for c in config/config.json config/revenue.json; do
  if [ ! -f "$c" ] && [ -f "${c%.json}.example.json" ]; then
    cp "${c%.json}.example.json" "$c"
    echo "==> seeded $c from $(basename "${c%.json}.example.json")"
  fi
done

# Suggest the user log into claude
if command -v claude >/dev/null 2>&1; then
  if ! claude --version >/dev/null 2>&1; then
    echo "==> claude installed but not logged in. Run:  claude login"
  fi
fi

cat <<EOF

Setup complete.

Next steps:
  1) Drop Penelope Cruz reference photos in assets/reference/   (1+ jpg/png)
     Then run:
        python python/extract_face_mesh.py assets/reference/*.jpg
  2) Drop the Drake song at assets/songs/papis_home.mp3
  3) (optional) put 5-20 photos of yourself in assets/owner_faces/
  4) Edit config/config.json with API keys when ready
  5) ./scripts/run.sh

EOF
