#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PWD}/cli/gang${PYTHONPATH:+:$PYTHONPATH}"
echo "Studio: http://127.0.0.1:3010/"
echo "Keep this window open."
gang studio --host 127.0.0.1 --port 3010
