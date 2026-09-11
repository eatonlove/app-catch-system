"""Mac pulls jobs. Cloud never supplies executable code, selectors or filesystem paths."""
import os
import re
import time
import threading
import fcntl
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .core import read_json, digest

class Client:
    def __init__(self, origin, token, local_test=False):
        url = urlsplit(origin)
        if (url.scheme != 'https' and not (local_test and url.scheme == 'http' and url.hostname == '127.0.0.1')) or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            raise ValueError('HTTPS origin required')
        if len(token) < 32:
            raise ValueError('Dedicated worker token required')
        self.http = httpx.Client(base_url=origin.rstrip('/'), headers={'Authorization': 'Bearer '+token},
                                 timeout=30, follow_redirects=False)
    def post(self, path, body=None):
        response = self.http.post(path, json=body or {})
        if response.status_code != 200:
            raise RuntimeError('CLOUD_HTTP_'+str(response.status_code))
        return response.json()


def execute(task, client, recipe_dir, output_dir, profile, collector=None):
    from .browser import collect
    custom_collector = collector
    collector = collector or collect
    identity = task['id']
    if not re.fullmatch(r'[a-f0-9-]{36}', identity):
        raise ValueError('Invalid task ID')
    name = task['payload']['recipe']
    if not re.fullmatch(r'[a-z0-9-]{1,60}', name):
        raise ValueError('Invalid local recipe name')
    prefix = '/worker/jobs/'+identity
    lease = {'lease': task['lease']}
    stop, lost = threading.Event(), threading.Event()
    def beat():
        while not stop.wait(15):
            try:
                client.post(prefix+'/heartbeat', lease)
            except Exception:
                lost.set()
                return
    client.post(prefix+'/heartbeat', lease)
    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        recipe = read_json(Path(recipe_dir)/(name+'.json'))
        # Cache exact payload AND recipe; completed local bundle survives interrupted upload.
        fingerprint = digest({'payload': task['payload'], 'recipe': recipe})
        target = Path(output_dir)/identity/fingerprint
        bundle_file = target/'bundle.json'
        if bundle_file.exists():
            bundle = read_json(bundle_file)
        else:
            if custom_collector is None and recipe.get('adapter')=='diandian-table-v1':
                from .diandian import collect_diandian
                bundle = collect_diandian(profile, recipe, task['payload']['context'], str(target), False, cancelled=lost.is_set)
            else:
                bundle = collector(profile, recipe, task['payload']['context'], str(target), False)
        if lost.is_set():
            raise RuntimeError('LEASE_LOST')
    except Exception as error:
        code=getattr(error,"state","COLLECTION_FAILED")
        if code in ("AUTH_REQUIRED","LOGIN_OR_PAGE_REQUIRED"):
            (Path(profile).parent/"login-required").touch()
        if not lost.is_set():
            try:
                client.post(prefix+'/fail', dict(lease, code=code))
            except Exception:
                pass
        raise
    else:
        # An uncertain upload is left leased: expiry permits replay of the local bundle.
        client.post(prefix+'/finish', dict(lease, bundle=bundle))
    finally:
        stop.set()
        thread.join(timeout=35)


def main():
    base = Path(os.environ.get('AC_WORK_DIR', 'data/remote-worker')).resolve()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    client = Client(os.environ['AC_CLOUD_ORIGIN'], os.environ['AC_WORKER_TOKEN'])
    recipe_dir = Path(os.environ.get('AC_RECIPE_DIR', 'configs/recipes')).resolve()
    # One worker per profile, including local run-plan users.
    profile = base/'browser-profile'
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (profile/'collector.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                if (base/'login-required').exists():
                    time.sleep(30)
                    continue
                task = client.post('/worker/claim')['task']
                if task:
                    execute(task, client, recipe_dir, base/'runs', str(profile))
                else:
                    time.sleep(10)
            except KeyboardInterrupt:
                return
            except Exception:
                print('Worker task unavailable or interrupted; see cloud state, retrying in 30s', flush=True)
                time.sleep(30)

if __name__ == '__main__':
    main()
