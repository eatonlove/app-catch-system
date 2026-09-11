import os,time
from contextlib import contextmanager
from sqlalchemy import text
from .cloud import Queue
from .product import metadata,tick

@contextmanager
def singleton(queue):
    """One analyst per database also serializes the daily model call budget."""
    if queue.engine.dialect.name=='postgresql':
        with queue.engine.connect() as connection:
            if not connection.scalar(text('SELECT pg_try_advisory_lock(817341209)')):
                raise RuntimeError('An analyst already owns this database')
            try:yield lambda:connection.execute(text('SELECT 1'))
            finally:connection.execute(text('SELECT pg_advisory_unlock(817341209)'))
    else:
        import fcntl,hashlib,tempfile
        from pathlib import Path
        path=Path(tempfile.gettempdir())/('appcatch-analyst-'+hashlib.sha256(str(queue.engine.url).encode()).hexdigest()+'.lock')
        with path.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield lambda:None

def main():
    queue=Queue(os.environ['AC_DATABASE_URL'])
    metadata.create_all(queue.engine)
    with singleton(queue) as check:
        while True:
            check() # A lost database lock must terminate, not silently reconnect.
            try:tick(queue)
            except KeyboardInterrupt:return
            except Exception:print('Scheduler error; retrying next cycle',flush=True)
            time.sleep(5)
if __name__=='__main__':main()
