#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f deploy/mac/worker.env ] || { echo '先配置 worker.env'; exit 1; }
.venv/bin/python - <<'PY'
from pathlib import Path
import plistlib
root=Path.cwd();logs=root/'data/remote-worker/logs';logs.mkdir(parents=True,exist_ok=True)
plist=Path.home()/'Library/LaunchAgents/com.appcatch.worker.plist';plist.parent.mkdir(parents=True,exist_ok=True)
with plist.open('wb') as f:plistlib.dump({'Label':'com.appcatch.worker','ProgramArguments':['/bin/bash',str(root/'deploy/mac/run.sh')],'WorkingDirectory':str(root),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,'StandardOutPath':str(logs/'worker.log'),'StandardErrorPath':str(logs/'error.log')},f)
PY
launchctl bootout "gui/$(id -u)/com.appcatch.worker" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.appcatch.worker.plist"
launchctl print "gui/$(id -u)/com.appcatch.worker"
