import tempfile,unittest,os
from datetime import date,timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from app_catch.cloud import create_app
from app_catch.scoring import score,growth,economics,WEIGHTS
from app_catch.product import tick

class LabTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app('sqlite:///'+self.tmp.name+'/db','a'*40,'w'*40);self.c=TestClient(self.app);self.h={'Authorization':'Bearer '+'a'*40};self.today=date.today().isoformat()
 def tearDown(self):self.c.close();self.app.state.queue.engine.dispose();self.tmp.cleanup()
 def post(self,path,data):return self.c.post('/api/'+path,headers=self.h,json=data)
 def get(self,path):return self.c.get('/api/'+path,headers=self.h).json()
 def evidence(self,**extra):
  d=dict(title='实际访谈样本',claim_type='demand',source='interview',text='受访者描述近期任务；测试数据不进入生产',observed_at=self.today,country='US',store='appstore',rights='测试夹具',quality=1,**extra)
  return self.post('evidence',d).json()['id']
 def opportunity(self,eid):
  return dict(title='自由职业者附件整理',who='自由职业者',task='整理附件',context='每月报销',country='US',store='appstore',evidence_ids=[eid],feature_facts='离线整理文件，无医疗金融功能',mvp='仅整理文件，投入10人日',entity_confidence=1,local_evidence=1,factors={k:dict(value=75,quality=1,observed_at=self.today,evidence_ids=[eid],reason='经人工核验的适用证据',signal_family=k) for k in WEIGHTS if k!='S'})
 def test_auth_and_contracts(self):
  for path in ('/api/evidence','/api/opportunities','/api/backlog','/api/experiments','/api/lab/schemas'):self.assertEqual(self.c.get(path).status_code,401)
  self.assertIn('observation',self.get('lab/schemas'))
 def test_opportunity_review_gate_version_and_revalidation(self):
  eid=self.evidence();d=self.opportunity(eid);r=self.post('opportunities',d);self.assertEqual(r.status_code,200,r.text);identity=r.json()['id'];self.assertEqual(self.get('opportunities/'+identity)['score']['cohort'],'exploration')
  rule=self.post('qualification-rules',dict(title='测试范围限定规则',jurisdiction='US',device='phone',operator_type='测试主体',feature_predicate='限定离线文件工具',qualification_type='测试规则',decision='ELIGIBLE',source_url='https://example.com/rule',evidence_ids=[eid],effective_at=self.today,checked_at=self.today,next_review_at=(date.today()+timedelta(days=20)).isoformat(),reviewer='测试核验人')).json()['id']
  decision=dict(expected_version=1,industry='ELIGIBLE',channel='READY',rule_ids=[rule],evidence_ids=[eid],reasons='限定功能核验',reviewer='tester',baseline_path='账号与发行路径核验')
  self.assertEqual(self.post('opportunities/'+identity+'/review',decision).status_code,200)
  self.assertEqual(self.post('opportunities/'+identity+'/review',decision).status_code,409)
  self.assertEqual(self.get('opportunities/'+identity)['score']['cohort'],'validation')
  self.assertEqual(self.post('opportunities/'+identity+'/status',dict(expected_version=2,status='BUILD_CANDIDATE',reason='仅分数不能立项',reviewer='test')).status_code,422)
  self.assertEqual(self.c.put('/api/opportunities/'+identity,headers=self.h,json=dict(d,expected_version=2)).status_code,200)
  self.assertEqual(self.get('opportunities/'+identity)['score']['cohort'],'exploration')
  self.assertEqual(len(self.get('opportunities/'+identity+'/history')),3)
 def test_import_idempotent_and_revision_growth(self):
  eid=self.evidence();row=dict(listing_key='appstore:1',country='US',store='appstore',device='iphone',metric='revenue',date=self.today,value=10,unit='money',currency='USD',basis='net',scope='IAP',source='test',period='daily',evidence_ids=[eid])
  p=self.post('imports/preview',dict(kind='observations',rows=[row])).json();self.assertTrue(p['can_commit'])
  self.assertEqual(self.post('imports',dict(preview_id=p['id'])).json()['imported'],1)
  p2=self.post('imports/preview',dict(kind='observations',rows=[row])).json();self.assertEqual(self.post('imports',dict(preview_id=p2['id'])).json()['imported'],0)
  row['value']=None;row['missing_reason']='修订为空';p3=self.post('imports/preview',dict(kind='observations',rows=[row])).json();self.post('imports',dict(preview_id=p3['id']))
  self.assertEqual(len(self.get('observations')),2);self.assertIsNone(self.get('growth')[0]['windows']['7']['log_growth'])
  broken=self.post('imports/preview',dict(kind='observations',rows=[dict(row,evidence_ids=['unknown'])])).json();self.assertFalse(broken['can_commit']);self.assertEqual(self.post('imports',dict(preview_id=broken['id'])).status_code,422)
 def test_sources_and_extra_evidence_frozen_without_model_call(self):
  eid=self.evidence();v=dict(source_ids=[],evidence_record_ids=[eid],use_model=True)
  preview=self.post('research-preview',v);self.assertEqual(preview.status_code,200,preview.text);self.assertEqual(len(preview.json()['model_inputs']),1)
  with patch.dict(os.environ,{'AC_LLM_ENDPOINT':'https://example.com/v1','AC_LLM_MODEL':'test','AC_LLM_API_KEY':'test'}):
   created=self.post('analyses',v);self.assertEqual(created.status_code,200,created.text);captured=[]
   def model(e,*args,**kw):captured.extend(e);return {'result':{'candidates':[]}}
   tick(self.app.state.queue,model)
  r=self.get('analyses/'+created.json()['id']);self.assertEqual(r['state'],'SUCCEEDED');self.assertEqual(len(captured),1);self.assertIn('实际访谈样本',captured[0]['text'])
 def test_frozen_score_run_no_hindsight(self):
  eid=self.evidence();oid=self.post('opportunities',self.opportunity(eid)).json()['id'];run=self.post('score-runs',dict(as_of=self.today)).json()['id'];frozen=self.get('opportunities?run_id='+run)['items'][0]
  self.post('opportunities/'+oid+'/status',dict(expected_version=1,status='PARKED',reason='暂存',reviewer='t'))
  self.assertEqual(self.get('opportunities?run_id='+run)['items'][0],frozen)
  self.assertEqual(self.post('score-runs',dict(as_of='2020-01-01')).status_code,422)
 def test_experiment_result_denominators_and_net(self):
  eid=self.evidence();oid=self.post('opportunities',self.opportunity(eid)).json()['id'];ex=self.post('experiments',dict(opportunity_id=oid,hypothesis='目标用户会为具体结果付款',method='E3',audience='目标人群',budget_cap=100,currency='USD',metrics='有效样本到真实付款',stop_rule='满30天或预算到上限',min_samples=50,end_date=self.today,owner='tester')).json()['id']
  d=dict(eligible_n=20,paid_users=2,receipts=20,income_basis='net',currency='USD',window_start=self.today,window_end=self.today,attribution='单渠道去重付款账户',evidence_ids=[eid],decision='continue',note='小样本不宣布市场成功')
  bad=self.post('experiments/'+ex+'/results',dict(d,paid_users=21));self.assertEqual(bad.status_code,422)
  self.assertEqual(self.post('experiments/'+ex+'/results',dict(d,platform_fees=2)).status_code,422)
  self.assertEqual(self.post('experiments/'+ex+'/results',d).status_code,200)
  res=self.get('experiments/'+ex)['results'][0]['data']['calculated'];self.assertTrue(res['provisional']);self.assertAlmostEqual(res['paid_conversion'],.1);self.assertIsNone(res['renewal_rate'])
 def test_incomplete_search_cannot_score_supply(self):
  eid=self.evidence();d=self.opportunity(eid);d['factors']['S']=dict(value=90,quality=1,observed_at=self.today,evidence_ids=[eid],reason='并没有搜索',signal_family='supply')
  self.assertEqual(self.post('opportunities',d).status_code,422)
 def test_report_candidate_capture_idempotent(self):
  from app_catch.product import analyses,build_report
  from test_pipeline import sample
  r=build_report([('source-batch',sample())]);ref=r['evidence'][0]['id'];r['model']={'result':{'candidates':[dict(task='具体人群任务',hypothesis='待验证假设',evidence_ids=[ref],unknowns=['需补证'])]}}
  with self.app.state.queue.engine.begin() as c:c.execute(analyses.insert().values(id='report-capture',state='SUCCEEDED',use_model=1,result=r,filters={}))
  value=dict(report_id='report-capture',candidate_index=0,country='US',store='appstore')
  first=self.post('opportunities/from-report',value);self.assertEqual(first.status_code,200,first.text)
  second=self.post('opportunities/from-report',value);self.assertEqual(first.json()['id'],second.json()['id']);self.assertTrue(second.json()['duplicate'])
  captured=self.get('opportunities/'+first.json()['id']);self.assertEqual(captured['score']['cohort'],'exploration');self.assertEqual(len(captured['data']['evidence_ids']),1)
 def test_stale_rule_and_missing_baseline(self):
  eid=self.evidence();oid=self.post('opportunities',self.opportunity(eid)).json()['id']
  decision=dict(expected_version=1,industry='ELIGIBLE',channel='READY',rule_ids=[],evidence_ids=[eid],reasons='缺规则不放行',reviewer='tester',baseline_path='')
  self.assertEqual(self.post('opportunities/'+oid+'/review',decision).status_code,422)
  op=self.opportunity(eid);op['decision']=dict(industry='ELIGIBLE',channel='READY',valid_until='2020-01-01');self.assertIsNone(score(op,self.today)['adjusted'])
 def test_empty_numeric_and_unsafe_evidence_rejected(self):
  response=self.post('evidence',dict(title='bad',claim_type='market',source='x',text='x',observed_at=self.today,country='US',store='appstore',rights='x',source_url='javascript:alert(1)'));self.assertEqual(response.status_code,422)

class Calculations(unittest.TestCase):
 def test_document_example(self):
  factors=dict(zip(WEIGHTS,[70,75,60,65,80,70,85]));today=date.today().isoformat()
  op=dict(factors={k:dict(value=v,quality=.75,observed_at=today,half_life=7,evidence_ids=['e']) for k,v in factors.items()},decision=dict(industry='ELIGIBLE',channel='READY',valid_until=today),entity_confidence=.95,local_evidence=.8,penalties=[dict(value=3)])
  s=score(op,today);self.assertAlmostEqual(s['raw'],71);self.assertAlmostEqual(s['C'],.91);self.assertAlmostEqual(s['adjusted'],64.805)
  op['decision']['industry']='EXCLUDED';self.assertIsNone(score(op,today)['adjusted'])
 def test_growth_missing_negative_low_base(self):
  today=date.today();data=[dict(date=(today-timedelta(days=i)).isoformat(),value=10 if i<7 else 5,collected_at=i) for i in range(14)]
  self.assertGreater(growth(data,today.isoformat())['7']['log_growth'],0)
  self.assertEqual(growth(data[:-1],today.isoformat())['7']['reason'],'INCOMPLETE_HISTORY')
  data[0]['value']=-1;self.assertEqual(growth(data,today.isoformat())['7']['reason'],'NEGATIVE_REVENUE_REVIEW')
if __name__=='__main__':unittest.main()
