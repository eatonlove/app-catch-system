#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
DEST="${1:?Pass a dedicated backup directory}"
mkdir -p "$DEST"; chmod 700 "$DEST"
FILE="$DEST/appcatch-$(date +%Y%m%d-%H%M%S).dump"
docker compose --env-file deploy/cloud/production.env -f deploy/cloud/compose.yml -p appcatch exec -T db pg_dump -U appcatch -d appcatch -Fc > "$FILE"
chmod 600 "$FILE"; test -s "$FILE"
echo "Backup saved: $FILE"
