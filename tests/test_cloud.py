import copy
import tempfile
import unittest
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from app_catch.cloud import create_app
from app_catch.llm import research, validate_output
from app_catch.remote_worker import execute
from app_catch.core import write_json
from test_pipeline import sample

ADMIN={'Authorization':'Bearer '+'a'*40}
WORKER={'Authorization':'Bearer '+'w'*40}

class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.t=[1000.0]
        self.url='sqlite:///'+self.temp.name+'/cloud.sqlite'
        self.app=create_app(self.url,'a'*40,'w'*40,clock=lambda:self.t[0])
        self.client=TestClient(self.app)
    def tearDown(self):
        self.client.close(); self.app.state.queue.engine.dispose(); self.temp.cleanup()
    def submit(self,key='test'):
        return self.client.post('/api/jobs',headers=ADMIN,json={'request_key':key,'recipe':'fixture','context':sample()['context']})
    def claim(self):
        return self.client.post('/worker/claim',headers=WORKER).json()['task']
    def finish(self,task,bundle=None):
        return self.client.post('/worker/jobs/'+task['id']+'/finish',headers=WORKER,
                                json={'lease':task['lease'],'bundle':bundle or sample()})
    def test_roles_and_private_results(self):
        self.assertEqual(self.client.get('/api/jobs').status_code,401)
        self.assertEqual(self.client.get('/api/jobs',headers=WORKER).status_code,401)
        self.assertEqual(self.client.post('/worker/claim',headers=ADMIN).status_code,401)
        self.assertEqual(self.client.get('/healthz').status_code,200)
    def test_idempotent_submit_and_conflict(self):
        first=self.submit().json()
        self.assertEqual(first,self.submit().json())
        x=sample()['context'];x['country']='CN'
        self.assertEqual(self.client.post('/api/jobs',headers=ADMIN,json={'request_key':'test','recipe':'fixture','context':x}).status_code,409)
    def test_expired_lease_cannot_publish(self):
        self.submit(); old=self.claim(); self.assertIsNone(self.claim())
        self.t[0]+=61; new=self.claim()
        self.assertNotEqual(old['lease'],new['lease'])
        self.assertEqual(self.finish(old).status_code,409)
        self.assertEqual(self.finish(new).status_code,200)
        self.assertTrue(self.finish(new).json()['duplicate'])
    def test_cancel_prevents_stale_submission(self):
        self.submit(); task=self.claim()
        self.client.post('/api/jobs/'+task['id']+'/cancel',headers=ADMIN)
        self.assertEqual(self.finish(task).status_code,409)
    def test_context_and_duplicate_rejection(self):
        self.submit();task=self.claim();b=sample();b['context']['country']='CN'
        self.assertEqual(self.finish(task,b).status_code,409)
        b=sample();b['rows'].append(copy.deepcopy(b['rows'][0]))
        self.assertEqual(self.finish(task,b).status_code,422)
        self.assertEqual(self.finish(task).status_code,200)
    def test_queue_survives_restart(self):
        identity=self.submit().json()['id']
        other=create_app(self.url,'a'*40,'w'*40,clock=lambda:self.t[0])
        self.assertEqual(other.state.queue.claim()['id'],identity)
        other.state.queue.engine.dispose()
    def test_attempt_limit(self):
        self.submit()
        for i in range(5):
            self.assertIsNotNone(self.claim());self.t[0]+=61
        self.assertIsNone(self.claim())
        self.assertEqual(self.client.get('/api/jobs',headers=ADMIN).json()[0]['state'],'FAILED')
    def test_worker_to_cloud_roundtrip(self):
        self.submit();task=self.claim();root=Path(self.temp.name);write_json(root/'fixture.json',{'test':True})
        client=self.client
        class Bridge:
            def post(self,path,body=None):
                r=client.post(path,headers=WORKER,json=body or {});r.raise_for_status();return r.json()
        def collector(profile,recipe,context,target,headless):
            write_json(Path(target)/'bundle.json',sample());return sample()
        execute(task,Bridge(),root,root/'runs',root/'profile',collector=collector)
        r=client.get('/api/jobs/'+task['id']+'/result',headers=ADMIN)
        self.assertEqual(r.json(),sample())
    def test_uncertain_upload_reuses_local_bundle(self):
        self.submit();task=self.claim();root=Path(self.temp.name);write_json(root/'fixture.json',{'test':True})
        client=self.client;calls=[]
        class Bridge:
            failed=False
            def post(self,path,body=None):
                if path.endswith('/finish') and not self.failed:
                    self.failed=True
                    raise RuntimeError('response unavailable')
                r=client.post(path,headers=WORKER,json=body or {});r.raise_for_status();return r.json()
        bridge=Bridge()
        def collector(profile,recipe,context,target,headless):
            calls.append(1);write_json(Path(target)/'bundle.json',sample());return sample()
        with self.assertRaises(RuntimeError):
            execute(task,bridge,root,root/'runs',root/'profile',collector=collector)
        self.t[0]+=61
        next_task=self.claim()
        execute(next_task,bridge,root,root/'runs',root/'profile',collector=collector)
        self.assertEqual(len(calls),1)

    def test_body_limit(self):
        r=self.client.post('/api/jobs',headers=ADMIN,content=b'x'*(4*1024*1024+1))
        self.assertEqual(r.status_code,413)

class ModelTests(unittest.TestCase):
    def test_dashscope_deepseek_request(self):
        import json
        def handler(req):
            body=json.loads(req.content)
            self.assertEqual(str(req.url),'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions')
            self.assertFalse(body['enable_thinking'])
            self.assertEqual(body['max_completion_tokens'],3000)
            self.assertNotIn('max_tokens',body)
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"candidates":[]}'}}]})
        with tempfile.TemporaryDirectory() as temp:
            args=([{'id':'e1','text':'TEST ONLY'}],'https://dashscope.aliyuncs.com/compatible-mode/v1','deepseek-v4-flash-0731')
            research(*args,'test-key',temp,transport=httpx.MockTransport(handler))
            with self.assertRaisesRegex(ValueError,'STANDARD_PAY_AS_YOU_GO'):
                research(*args,'sk-sp-test',temp,transport=httpx.MockTransport(handler))
    def test_unknown_evidence_rejected(self):
        with self.assertRaises(ValueError):
            validate_output({'candidates':[{'task':'t','hypothesis':'h','evidence_ids':['fake'],'unknowns':['u']}]},{'real'})
    def test_model_cache_and_usage(self):
        calls=[]
        def handler(req):
            calls.append(req)
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"candidates":[]}'}}], 'usage':{'total_tokens':12}})
        with tempfile.TemporaryDirectory() as temp:
            args=([{'id':'e1','text':'TEST ONLY'}],'https://model.example/v1','configured-model','test-key',temp)
            first=research(*args,transport=httpx.MockTransport(handler));second=research(*args,transport=httpx.MockTransport(handler))
            self.assertEqual(len(calls),1);self.assertTrue(second['cached']);self.assertEqual(first['usage']['total_tokens'],12)
    def test_no_retry_on_timeout(self):
        calls=[]
        def handler(req):
            calls.append(req);raise httpx.ReadTimeout('uncertain')
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(httpx.ReadTimeout):
                research([{'id':'e1','text':'test'}],'https://model.example/v1','m','k',temp,transport=httpx.MockTransport(handler))
            self.assertEqual(len(calls),1)

if __name__=='__main__':unittest.main()
