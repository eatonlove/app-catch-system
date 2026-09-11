#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
.venv/bin/python - <<'PY'
import importlib.util,sys
from pathlib import Path
print('Python:',sys.version.split()[0])
print('Playwright:',bool(importlib.util.find_spec('playwright')))
print('worker.env:',Path('deploy/mac/worker.env').exists())
print('Recipe files:',len(list(Path('configs/recipes').glob('*.json'))))
print('登录要求：正常桌面会话；浏览器profile只允许一个节点占用。')
PY
