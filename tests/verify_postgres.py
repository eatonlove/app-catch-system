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
        from app_catch.cloud import create_app
        from fastapi.testclient import TestClient
        app=create_app(url,'a'*40,'w'*40)
        with TestClient(app) as client:
            h={'Authorization':'Bearer '+'a'*40}
            from datetime import date
            ev=client.post('/api/evidence',headers=h,json=dict(title='PG integration evidence',claim_type='market',source='test',text='Test only',observed_at=date.today().isoformat(),country='US',store='appstore',rights='test')).json()['id']
            op=client.post('/api/opportunities',headers=h,json=dict(title='Test opportunity',who='test',task='test',context='test',country='US',store='appstore',evidence_ids=[ev]))
            assert op.status_code==200,op.text
            snap=client.post('/api/score-runs',headers=h,json={'as_of':date.today().isoformat()})
            assert snap.status_code==200,snap.text
        dump=subprocess.check_output(['docker','exec',name,'pg_dump','-U','postgres','-d','appcatch_test','-Fc'])
        assert len(dump)>1000
        subprocess.run(['docker','exec',name,'createdb','-U','postgres','appcatch_restore'],check=True,capture_output=True)
        subprocess.run(['docker','exec','-i',name,'pg_restore','-U','postgres','-d','appcatch_restore','--exit-on-error'],input=dump,check=True,capture_output=True)
        restored=subprocess.check_output(['docker','exec',name,'psql','-U','postgres','-d','appcatch_restore','-Atc',"select count(*) from ac_lab_records where kind='score_run'"],text=True).strip()
        assert restored=='1'
        app.state.queue.engine.dispose()
        print('PostgreSQL17: queue uniqueness, lab evidence/opportunity/snapshot persisted; pg_dump restored into separate disposable DB with complete score report.')
    finally:
        if queue:queue.engine.dispose()
        subprocess.run(['docker','rm','-f',name],capture_output=True)

if __name__=='__main__':main()
