#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$REPO_ROOT"
  exit 0
fi

# Check if we're in a virtual environment (pip install is safe there)
if [ -n "${VIRTUAL_ENV:-}" ]; then
  python3 -m pip install --editable "$REPO_ROOT"
  exit 0
fi

echo "Error: pipx is not installed and you are not in a virtual environment."
echo ""
echo "Option 1 (recommended): Install pipx first"
echo "  brew install pipx && pipx ensurepath"
echo "  Then re-run: ./scripts/install-cli.sh"
echo ""
echo "Option 2: Use a virtual environment"
echo "  python3 -m venv .venv && source .venv/bin/activate"
echo "  pip install -e ."
exit 1
