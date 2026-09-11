import os,tempfile,unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app_catch.cloud import create_app
from app_catch.product import tick,build_report
from app_catch.diandian import parse_table
from test_pipeline import sample

class ProductTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app('sqlite:///'+self.tmp.name+'/db','a'*40,'w'*40)
  self.c=TestClient(self.app);self.h={'Authorization':'Bearer '+'a'*40}
 def tearDown(self):self.c.close();self.app.state.queue.engine.dispose();self.tmp.cleanup()
 def test_login_csrf_logout(self):
  with patch.dict(os.environ,{'AC_ADMIN_PASSWORD':'test-password-123'}):
   self.assertEqual(self.c.post('/auth/login',json={'password':'test-password-123'}).status_code,200)
  self.assertEqual(self.c.get('/api/catalog').status_code,200)
  self.assertEqual(self.c.post('/api/analyses',json={}).status_code,403)
  self.assertEqual(self.c.post('/auth/logout',headers={'X-Requested-With':'appcatch'}).status_code,200)
  self.assertEqual(self.c.get('/api/catalog').status_code,401)
 def test_plan_daily_idempotence(self):
  r=self.c.post('/api/plans',headers=self.h,json={'name':'test','catalog_id':'ios-us-tools-grossing'})
  self.assertEqual(r.status_code,200)
  tick(self.app.state.queue);tick(self.app.state.queue)
  self.assertEqual(len(self.app.state.queue.list_jobs()),1)
 def test_empty_analysis_is_honest(self):
  a=self.c.post('/api/analyses',headers=self.h,json={}).json()['id'];tick(self.app.state.queue)
  report=self.c.get('/api/analyses/'+a,headers=self.h).json()
  self.assertEqual(report['state'],'SUCCEEDED');self.assertTrue(report['result']['empty'])
 def test_model_requires_configuration(self):
  with patch.dict(os.environ,{'AC_LLM_API_KEY':''}):
   self.assertEqual(self.c.post('/api/analyses',headers=self.h,json={'use_model':True}).status_code,409)
 def test_qualification_gate(self):
  data={'decision':'develop','qualification':'UNREVIEWED','note':'test'}
  self.assertEqual(self.c.put('/api/feedback/'+'e'*64,headers=self.h,json=data).status_code,422)
  data.update(qualification='REVIEWED_ELIGIBLE',evidence_refs=['review-record'])
  self.assertEqual(self.c.put('/api/feedback/'+'e'*64,headers=self.h,json=data).status_code,200)
 def test_assets_real(self):
  self.assertEqual(self.c.get('/').status_code,200)
  self.assertEqual(self.c.get('/assets/app.js').status_code,200)
  self.assertEqual(self.c.get('/assets/cloud.py').status_code,404)
 def test_rank_report_never_income(self):
  b=sample();b['rows'][0]['metrics'][0].update(name='rank',value='5')
  result=build_report([('r1',b)])
  self.assertEqual(result['candidates'][0]['rank'],5)
  self.assertIsNone(result['candidates'][0]['windows']['7']['rank_improvement'])
 def test_table_headers_map(self):
  b=sample();t={'headers':['#','应用','分类排名','综合评分','评分数','最后更新'], 'rows':[{'name':'TEST ONLY','url':'https://app.diandian.com/app/fixture/ios','developer':'test','cells':['','TEST ONLY','1\n工具','4.7','123','2026-09-01']}]}
  rows=parse_table(t,b['context']);self.assertEqual(rows[0]['metrics'][0]['value'],'1')
  t['rows'][0]['cells']=[]
  with self.assertRaises(Exception):parse_table(t,b['context'])
if __name__=='__main__':unittest.main()
