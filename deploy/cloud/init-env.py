"""Create only this project's private env; no existing config is overwritten."""
import getpass,secrets,shlex
from pathlib import Path
p=Path(__file__).parent/'production.env'
if p.exists():raise SystemExit('production.env already exists; edit it without printing secrets')
port=input('确认空闲的本项目回环端口：').strip()
if not port.isdigit() or not 1024<=int(port)<=65535:raise SystemExit('Invalid port')
password=getpass.getpass('设置工作台管理员密码（至少12字符）：')
if len(password)<12:raise SystemExit('Password too short')
db=secrets.token_hex(32)
values={'AC_DB_PASSWORD':db,'AC_DATABASE_URL':'postgresql+psycopg://appcatch:'+db+'@db:5432/appcatch','AC_ADMIN_TOKEN':secrets.token_hex(32),'AC_WORKER_TOKEN':secrets.token_hex(32),'AC_ADMIN_PASSWORD':password,'AC_HOST_PORT':port,'AC_RELEASE':'unreleased','AC_LLM_ENDPOINT':'https://dashscope.aliyuncs.com/compatible-mode/v1','AC_LLM_MODEL':'deepseek-v4-flash-0731','AC_LLM_API_KEY':'','AC_MODEL_DAILY_LIMIT':'10'}
# dotenv single-quoted values. Disallow quote/newline to keep Compose parsing unambiguous.
if any(any(c in v for c in "'\n\r") for v in values.values()):raise SystemExit('Values cannot contain quotes or newlines')
with p.open('x') as f:f.write('\n'.join(k+"='"+v+"'" for k,v in values.items())+'\n')
p.chmod(0o600)
print('Created private production.env; securely transfer only AC_WORKER_TOKEN to Mac.')
