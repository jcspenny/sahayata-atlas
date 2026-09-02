#!/usr/bin/env bash
# Runs at deploy time on the static site host. Rewrites config.js so the
# frontend points at wherever this deploy's backend actually landed, without
# needing a rebuild of the app itself. API_BASE_URL is provided as an env var
# by the hosting platform (see render.yaml) or set manually.
set -euo pipefail

if [ -z "${API_BASE_URL:-}" ]; then
  echo "API_BASE_URL is not set — leaving static/config.js untouched." >&2
  exit 0
fi

cat > static/config.js <<EOF
window.SAHAYATA_CONFIG = Object.freeze({
  apiBaseUrl: "${API_BASE_URL}",
  requestTimeoutMs: 20000,
});
EOF

echo "Wrote static/config.js with apiBaseUrl=${API_BASE_URL}"
