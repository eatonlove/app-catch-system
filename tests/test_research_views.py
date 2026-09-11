import json,os,tempfile,unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import select
from app_catch.cloud import create_app
from app_catch.product import tick,analyses
from app_catch.prompts import snapshot
from app_catch.llm import research
import httpx
from test_pipeline import sample

class ResearchViews(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app('sqlite:///'+self.tmp.name+'/db','a'*40,'w'*40)
  self.c=TestClient(self.app);self.h={'Authorization':'Bearer '+'a'*40}
 def tearDown(self):self.c.close();self.app.state.queue.engine.dispose();self.tmp.cleanup()
 def test_routes_auth_and_job_details(self):
  for path in ['/collections/unknown','/reports/unknown']:self.assertEqual(self.c.get(path).status_code,200)
  self.assertEqual(self.c.get('/api/research-directions').status_code,401)
  self.assertEqual(self.c.get('/api/jobs/unknown',headers=self.h).status_code,404)
  q=self.app.state.queue;j=q.submit({'request_key':'test','recipe':'fixture','context':sample()['context']});task=q.claim()
  r=self.c.get('/api/jobs/'+task['id'],headers=self.h).json()
  self.assertNotIn('lease',r);self.assertEqual(r['state'],'RUNNING')
  q.finish(task['id'],task['lease'],sample())
  self.assertEqual(self.c.get('/api/jobs/'+task['id']+'/result',headers=self.h).json(),sample())
 def test_prompt_snapshot_and_execution(self):
  q=self.app.state.queue;q.submit({'request_key':'test','recipe':'fixture','context':sample()['context']});task=q.claim();q.finish(task['id'],task['lease'],sample())
  with patch.dict(os.environ,{'AC_LLM_ENDPOINT':'https://test.example/v1','AC_LLM_MODEL':'test','AC_LLM_API_KEY':'test'}):
   r=self.c.post('/api/analyses',headers=self.h,json={'use_model':True,'direction':'search','guidance':'关注自由职业者'})
   self.assertEqual(r.status_code,200);identity=r.json()['id']
   captured=[]
   def model(*args,**kwargs):captured.append(kwargs['system_prompt']);return {'result':{'candidates':[]},'model':'test','cached':False}
   tick(q,model_fn=model)
  result=self.c.get('/api/analyses/'+identity,headers=self.h).json()
  self.assertEqual(result['state'],'SUCCEEDED')
  self.assertEqual(result['result']['prompt_snapshot'],result['filters']['prompt_snapshot'])
  self.assertIn('关注自由职业者',captured[0]);self.assertIn('SEO / ASO',captured[0])
  self.assertEqual(captured[0],result['filters']['prompt_snapshot']['system_prompt'])
  self.assertEqual(len(result['result']['model_evidence_ids']),1)
 def test_bad_direction_and_oversized_guidance(self):
  self.assertEqual(self.c.post('/api/analyses',headers=self.h,json={'direction':'invented'}).status_code,422)
  self.assertEqual(self.c.post('/api/analyses',headers=self.h,json={'guidance':'x'*6001}).status_code,422)
  d=self.c.get('/api/research-directions',headers=self.h).json();self.assertEqual(len(d),13)
  self.assertEqual(len({x['prompt'] for x in d}),13)
 def test_prompt_separates_cache(self):
  calls=[]
  def transport(req):calls.append(json.loads(req.content));return httpx.Response(200,json={'choices':[{'message':{'content':'{"candidates":[]}'}}]})
  args=([{'id':'test','text':'TEST ONLY'}],'https://model.example/v1','m','k',self.tmp.name)
  for direction in ['search','cross-market','search']:
   research(*args,transport=httpx.MockTransport(transport),system_prompt=snapshot(direction)['system_prompt'])
  self.assertEqual(len(calls),2);self.assertNotEqual(calls[0]['messages'][0]['content'],calls[1]['messages'][0]['content'])
if __name__=='__main__':unittest.main()
