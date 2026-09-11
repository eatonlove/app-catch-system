#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
TARGET="${1:?Pass tested full commit SHA}"
[[ "$TARGET" =~ ^[0-9a-f]{40}$ ]] || { echo 'Require full commit SHA'; exit 1; }
[ "$(git rev-parse HEAD)" = "$TARGET" ] || { echo 'Checkout tested commit first'; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo 'Working tree is dirty'; exit 1; }
[ -f deploy/cloud/production.env ] || { echo 'Run init-env.py first'; exit 1; }
export AC_RELEASE="$TARGET"
docker compose --env-file deploy/cloud/production.env -f deploy/cloud/compose.yml -p appcatch config --quiet
docker compose --env-file deploy/cloud/production.env -f deploy/cloud/compose.yml -p appcatch up -d --build
docker compose --env-file deploy/cloud/production.env -f deploy/cloud/compose.yml -p appcatch ps
