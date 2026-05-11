#!/usr/bin/env bash
# Launch Penelope in dev mode.
set -euo pipefail
cd "$(dirname "$0")/.."
exec npm start
