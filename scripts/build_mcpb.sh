#!/usr/bin/env bash
# Build dist/codehealth-mcp-<version>.mcpb (MCP Bundle) for Claude Desktop.
#
# Uses the official MCPB CLI (@anthropic-ai/mcpb) through npx. The bundle is
# the "uv" server type (manifest_version 0.4): it ships pyproject.toml, uv.lock
# and src/ only, and the host installs dependencies with uv.
# Usage: scripts/build_mcpb.sh
set -euo pipefail

MCPB_VERSION="2.1.2"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "${root}/pyproject.toml" | head -n1)"
stage="${root}/mcpb-build"
out="${root}/dist/codehealth-mcp-${version}.mcpb"

rm -rf "${stage}"
mkdir -p "${stage}" "${root}/dist"
cp "${root}/manifest.json" "${root}/pyproject.toml" "${root}/uv.lock" "${root}/README.md" \
   "${root}/LICENSE" "${root}/THIRD_PARTY_NOTICES.md" "${stage}/"
rsync -a --exclude '__pycache__' "${root}/src" "${stage}/"

npx -y "@anthropic-ai/mcpb@${MCPB_VERSION}" validate "${stage}/manifest.json"
npx -y "@anthropic-ai/mcpb@${MCPB_VERSION}" pack "${stage}" "${out}"
rm -rf "${stage}"
echo "Built ${out}"
