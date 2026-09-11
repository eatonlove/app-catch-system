import os,tempfile,unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app_catch.cloud import create_app
from app_catch.product import tick
from app_catch.llm import validate_output
from test_pipeline import sample

class ResearchScopeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app('sqlite:///'+self.tmp.name+'/db','a'*40,'w'*40);self.c=TestClient(self.app);self.h={'Authorization':'Bearer '+'a'*40}
 def tearDown(self):self.c.close();self.app.state.queue.engine.dispose();self.tmp.cleanup()
 def add(self,key,status='SUCCEEDED'):
  q=self.app.state.queue;b=sample();b['status']=status;q.submit({'request_key':key,'recipe':'fixture','context':b['context']});t=q.claim();q.finish(t['id'],t['lease'],b);return t['id']
 def test_sources_and_explicit_selection(self):
  first=self.add('one');partial=self.add('two','PARTIAL')
  sources=self.c.get('/api/research-sources',headers=self.h).json();self.assertEqual(len(sources),2)
  self.assertFalse(next(s for s in sources if s['id']==partial)['eligible'])
  self.assertEqual(self.c.post('/api/research-preview',headers=self.h,json={'source_ids':[partial]}).status_code,422)
  self.assertEqual(self.c.post('/api/analyses',headers=self.h,json={'source_ids':[]}).status_code,422)
  preview=self.c.post('/api/research-preview',headers=self.h,json={'source_ids':[first],'use_model':True}).json()
  self.assertEqual(len(preview['sources']),1);self.assertEqual(preview['comparable']['7'],0);self.assertEqual(len(preview['model_inputs']),1)
 def test_create_freezes_sources_and_preview_matches(self):
  first=self.add('first');q=self.app.state.queue
  with patch.dict(os.environ,{'AC_LLM_ENDPOINT':'https://test.example/v1','AC_LLM_MODEL':'test','AC_LLM_API_KEY':'test'}):
   data={'use_model':True,'direction':'momentum','source_ids':[first]}
   preview=self.c.post('/api/research-preview',headers=self.h,json=data).json()
   identity=self.c.post('/api/analyses',headers=self.h,json=data).json()['id']
   self.add('later')
   captured=[]
   def model(e,*args,**kwargs):captured.extend(e);return {'result':{'candidates':[]}}
   tick(q,model_fn=model)
  result=self.c.get('/api/analyses/'+identity,headers=self.h).json()
  self.assertEqual(result['state'],'SUCCEEDED')
  self.assertEqual([s['id'] for s in result['result']['source_overview']['sources']],[first])
  self.assertEqual([e['id'] for e in captured],[e['id'] for e in preview['model_inputs']])
 def test_omitted_sources_freeze_even_without_explicit_selection(self):
  first=self.add('first')
  identity=self.c.post('/api/analyses',headers=self.h,json={}).json()['id'];self.add('later');tick(self.app.state.queue)
  r=self.c.get('/api/analyses/'+identity,headers=self.h).json()
  self.assertEqual(r['filters']['source_ids'],[first])
 def test_explanatory_empty_output(self):
  result={'summary':'只有单日快照，无法验证增长。','candidates':[],'data_gaps':['缺少基准日'],'next_steps':['补采同榜单历史日期']}
  self.assertEqual(validate_output(result,set()),result)
  with self.assertRaises(ValueError):validate_output(dict(result,next_steps=[]),set())
if __name__=='__main__':unittest.main()
