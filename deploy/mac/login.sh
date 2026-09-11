#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a
source deploy/mac/worker.env
set +a
.venv/bin/python - <<'PY'
import os,fcntl
from pathlib import Path
from app_catch.browser import session
p=Path(os.environ['AC_WORK_DIR'])/'browser-profile';p.mkdir(parents=True,exist_ok=True)
with (p/'collector.lock').open('a') as lock:
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise SystemExit('节点正在运行，请先停止本项目节点，再登录；不要删除资料锁。')
 with session(p) as browser:
  page=browser.pages[0] if browser.pages else browser.new_page()
  page.goto('https://app.diandian.com/rank/ios/')
  input('请在官方页面完成登录，看到榜单后回此处按回车保存退出：')
  (p.parent/'login-required').unlink(missing_ok=True)
PY
