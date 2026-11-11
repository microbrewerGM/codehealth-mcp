#!/usr/bin/env bash
# Thin wrapper around `codehealth install-pmd` (pinned PMD release, SHA-256 checked).
# Usage: scripts/install_pmd.sh [--dir DIR]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec uv run codehealth install-pmd "$@"
