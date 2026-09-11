"""Disposable local Docker PostgreSQL integration; never points at production."""
import concurrent.futures
import secrets
import subprocess
import time
import uuid
from app_catch.cloud import Queue
from test_pipeline import sample

def main():
    name='appcatch-test-'+uuid.uuid4().hex[:10]
    password=secrets.token_hex(24)
    subprocess.run(['docker','run','-d','--name',name,'-e','POSTGRES_PASSWORD='+password,
        '-e','POSTGRES_DB=appcatch_test','--tmpfs','/var/lib/postgresql/data:rw,size=256m','-p','127.0.0.1::5432','postgres:17'],check=True,capture_output=True)
    queue=None
    try:
        for _ in range(15):
            if subprocess.run(['docker','exec',name,'pg_isready','-U','postgres'],capture_output=True).returncode==0:break
            state=subprocess.check_output(['docker','inspect','--format','{{.State.Status}}',name],text=True).strip()
            if state=='exited':
                print(subprocess.check_output(['docker','logs',name],text=True))
                raise RuntimeError('Test database exited during startup')
            time.sleep(1)
        port=subprocess.check_output(['docker','port',name,'5432/tcp'],text=True).strip().split(':')[-1]
        url='postgresql+psycopg://postgres:'+password+'@127.0.0.1:'+port+'/appcatch_test'
        queue=Queue(url)
        for i in range(10):queue.submit({'request_key':str(i),'recipe':'fixture','context':sample()['context']})
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            tasks=list(executor.map(lambda _:queue.claim(),range(10)))
        assert len({t['id'] for t in tasks})==10
        for task in tasks:queue.finish(task['id'],task['lease'],sample())
        from app_catch.product import metadata, analyses, tick
        metadata.create_all(queue.engine)
        with queue.engine.begin() as c:c.execute(analyses.insert().values(id='analysis-test',state='PENDING',requested_at=time.time(),use_model=0,filters={}))
        tick(queue)
        from sqlalchemy import select
        with queue.engine.connect() as c:assert c.execute(select(analyses.c.state).where(analyses.c.id=='analysis-test')).scalar()=='SUCCEEDED'
        assert queue.claim() is None
        assert all(r['state']=='SUCCEEDED' for r in queue.list_jobs())
        print('PostgreSQL17: 10 concurrent claims unique, 10 bundles committed, no duplicate delivery.')
    finally:
        if queue:queue.engine.dispose()
        subprocess.run(['docker','rm','-f',name],capture_output=True)

if __name__=='__main__':main()
