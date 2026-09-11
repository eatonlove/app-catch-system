#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
PYTHON="${AC_PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,9), "Python 3.9+ required"'
"$PYTHON" -m venv .venv
.venv/bin/pip install '.[cloud,browser]'
.venv/bin/python -m playwright install chromium
mkdir -p data/remote-worker
chmod 700 data/remote-worker
if [ ! -f deploy/mac/worker.env ]; then cp deploy/mac/worker.env.example deploy/mac/worker.env; chmod 600 deploy/mac/worker.env; fi
printf '%s\n' '依赖已安装。配置 deploy/mac/worker.env，然后运行 login.sh 和 start.sh。'
