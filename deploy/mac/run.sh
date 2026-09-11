#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a
source deploy/mac/worker.env
set +a
exec .venv/bin/python -m app_catch.remote_worker
