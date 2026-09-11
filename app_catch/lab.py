"""Evidence registry, opportunity lifecycle, score snapshots and experiments."""
import csv
import io
import json
import time
import uuid
from datetime import date, timedelta
from typing import Optional, Literal
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict, model_validator
from sqlalchemy import Table, Column, String, Integer, Float, JSON, select, update
from sqlalchemy.exc import IntegrityError
from .cloud import metadata, results, jobs
from .core import digest, validate_bundle
from .scoring import score, economics, growth, WEIGHTS, VERSION

records=Table('ac_lab_records',metadata,Column('id',String,primary_key=True),Column('kind',String,index=True),Column('version',Integer,nullable=False),Column('data',JSON,nullable=False),Column('created_at',Float),Column('updated_at',Float))
history=Table('ac_lab_history',metadata,Column('id',String,primary_key=True),Column('record_id',String,index=True),Column('version',Integer),Column('data',JSON),Column('created_at',Float))

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class Evidence(Strict):
    title:str=Field(min_length=1,max_length=200)
    claim_type:Literal['market','commercial','demand','pain','acquisition','delivery','qualification','counter','interview','review','search','workflow','capability']
    source:str=Field(min_length=1,max_length=120)
    source_url:str=Field(default='',max_length=2000)
    text:str=Field(min_length=1,max_length=20000)
    observed_at:date
    country:str=Field(pattern='^[A-Z]{2}$')
    store:str=Field(min_length=1,max_length=80)
    rights:str=Field(min_length=1,max_length=500)
    quality:float=Field(default=.25,ge=0,le=1)
    provider_group:str=Field(default='',max_length=120)
    listing_key:str=Field(default='',max_length=500)
    version_label:str=Field(default='',max_length=100)
    stars:Optional[int]=Field(default=None,ge=1,le=5)
    search_query:str=Field(default='',max_length=300)
    truncated:bool=True
    result_count:Optional[int]=Field(default=None,ge=0,le=10000)
    @model_validator(mode='after')
    def safe(self):
        from urllib.parse import urlsplit
        if self.source_url:
            p=urlsplit(self.source_url)
            if p.scheme not in ('https','http') or not p.hostname or p.username or p.password:raise ValueError('无效来源链接')
        if self.observed_at>date.today():raise ValueError('证据日期不能在未来')
        return self
class Factor(Strict):
    value:float=Field(ge=0,le=100)
    quality:float=Field(ge=.01,le=1)
    observed_at:date
    evidence_ids:list[str]=Field(min_length=1,max_length=30)
    reason:str=Field(min_length=1,max_length=3000)
    half_life:int=Field(default=7,ge=1,le=365)
    normal_delay:int=Field(default=0,ge=0,le=30)
    signal_family:str=Field(min_length=1,max_length=100)
class Penalty(Strict):
    value:float=Field(ge=0,le=10)
    reason:str=Field(min_length=1,max_length=1000)
    evidence_ids:list[str]=Field(min_length=1,max_length=30)
class Opportunity(Strict):
    title:str=Field(min_length=1,max_length=200)
    who:str=Field(min_length=1,max_length=300)
    task:str=Field(min_length=1,max_length=2000)
    context:str=Field(min_length=1,max_length=2000)
    country:Literal['US','CN']
    store:Literal['appstore','googleplay','huawei','harmony']
    language:str=Field(default='',max_length=80)
    source_market:str=Field(default='',max_length=200)
    monetization:Literal['unknown','subscription','paid','usage','ads']='unknown'
    wedge:str=Field(default='',max_length=4000)
    counter_evidence:str=Field(default='',max_length=4000)
    mvp:str=Field(default='',max_length=4000)
    feature_facts:str=Field(default='',max_length=6000)
    competitors:list[str]=Field(default_factory=list,max_length=100)
    alternatives:list[str]=Field(default_factory=list,max_length=100)
    evidence_ids:list[str]=Field(default_factory=list,max_length=100)
    track:Literal['general','growth','new','cross_market','ads']='general'
    strict_baseline:bool=False
    factors:dict[str,Factor]=Field(default_factory=dict)
    entity_confidence:float=Field(default=0,ge=0,le=1)
    local_evidence:float=Field(default=0,ge=0,le=1)
    midterm_verified:bool=False
    penalties:list[Penalty]=Field(default_factory=list,max_length=2)
    impact:int=Field(default=3,ge=1,le=5)
    decision_value:int=Field(default=3,ge=1,le=5)
    validation_hours:float=Field(default=8,ge=.25,le=10000)
    @model_validator(mode='after')
    def valid_factors(self):
        if set(self.factors)-set(WEIGHTS):raise ValueError('Unknown factor')
        for k,v in self.factors.items():
            if k in ('P','A','B') and v.value not in (0,25,50,75,100):raise ValueError('P/A/B使用0/25/50/75/100锚点')
            if v.observed_at>date.today():raise ValueError('未来证据')
        families=[v.signal_family for v in self.factors.values()]
        if len(families)!=len(set(families)):raise ValueError('同一信号不得重复计分')
        if self.track=='cross_market' and 'S' in self.factors and not self.local_evidence:raise ValueError('跨市场供给分需要目标需求证据')
        return self
class EditOpportunity(Opportunity):
    expected_version:int=Field(ge=1)
class Rule(Strict):
    title:str=Field(min_length=1,max_length=200)
    jurisdiction:Literal['US','CN']
    store:str=Field(default='*',max_length=80)
    device:str=Field(min_length=1,max_length=80)
    operator_type:str=Field(min_length=1,max_length=200)
    feature_predicate:str=Field(min_length=1,max_length=4000)
    qualification_type:str=Field(min_length=1,max_length=300)
    decision:Literal['ELIGIBLE','REVIEW','EXCLUDED']
    source_url:str=Field(min_length=1,max_length=2000)
    evidence_ids:list[str]=Field(min_length=1,max_length=30)
    effective_at:date
    checked_at:date
    next_review_at:date
    reviewer:str=Field(min_length=1,max_length=100)
    @model_validator(mode='after')
    def dates(self):
        if self.checked_at>date.today() or self.effective_at>self.checked_at or not self.checked_at<=self.next_review_at<=self.checked_at+timedelta(days=30):raise ValueError('规则复核期限应在30天内')
        if not self.source_url.startswith('https://'):raise ValueError('规则需HTTPS出处')
        return self
class Decision(Strict):
    expected_version:int=Field(ge=1)
    industry:Literal['ELIGIBLE','REVIEW','EXCLUDED']
    channel:Literal['READY','NEEDS_BASELINE','UNAVAILABLE','UNKNOWN']
    rule_ids:list[str]=Field(default_factory=list,max_length=30)
    evidence_ids:list[str]=Field(min_length=1,max_length=30)
    reasons:str=Field(min_length=1,max_length=4000)
    reviewer:str=Field(min_length=1,max_length=100)
    baseline_path:str=Field(default='',max_length=2000)
class Transition(Strict):
    expected_version:int=Field(ge=1)
    status:Literal['DISCOVERED','NEEDS_EVIDENCE','QUALIFIED','VALIDATING','BUILD_CANDIDATE','REJECTED','PARKED']
    reason:str=Field(min_length=1,max_length=3000)
    reviewer:str=Field(min_length=1,max_length=100)
class Experiment(Strict):
    opportunity_id:str
    hypothesis:str=Field(min_length=1,max_length=4000)
    method:Literal['E0','E1','E2','E3','E4']
    audience:str=Field(min_length=1,max_length=2000)
    budget_cap:float=Field(ge=0,le=10000000)
    currency:Literal['USD','CNY']
    metrics:str=Field(min_length=1,max_length=2000)
    stop_rule:str=Field(min_length=1,max_length=2000)
    min_samples:int=Field(ge=1,le=100000000)
    end_date:date
    owner:str=Field(min_length=1,max_length=100)
class ExperimentResult(Strict):
    eligible_n:int=Field(ge=0,le=100000000)
    paid_users:int=Field(ge=0,le=100000000)
    refunded_users:int=Field(default=0,ge=0)
    renewal_eligible:int=Field(default=0,ge=0)
    renewals:int=Field(default=0,ge=0)
    receipts:float=Field(ge=0)
    income_basis:Literal['gross','net']
    refund_amount:float=Field(default=0,ge=0)
    platform_fees:float=Field(default=0,ge=0)
    taxes:float=Field(default=0,ge=0)
    delivery_cost:float=Field(default=0,ge=0)
    support_cost:float=Field(default=0,ge=0)
    acquisition_cost:float=Field(default=0,ge=0)
    fixed_cost:float=Field(default=0,ge=0)
    currency:Literal['USD','CNY']
    window_start:date
    window_end:date
    window_mature:bool=False
    attribution:str=Field(min_length=1,max_length=2000)
    evidence_ids:list[str]=Field(min_length=1,max_length=30)
    decision:Literal['continue','stop','iterate','pass']
    note:str=Field(min_length=1,max_length=3000)
    @model_validator(mode='after')
    def counts(self):
        if self.paid_users>self.eligible_n or self.refunded_users>self.paid_users or self.renewals>self.renewal_eligible or self.renewal_eligible>self.paid_users:raise ValueError('分子不能超过对应分母')
        if self.window_end<self.window_start or self.window_end>date.today():raise ValueError('观察窗无效')
        if self.income_basis=='net' and any((self.refund_amount,self.platform_fees,self.taxes)):raise ValueError('已净收入不得再扣退款/税费/平台费')
        return self
class Observation(Strict):
    listing_key:str=Field(min_length=1,max_length=500)
    country:str=Field(pattern='^[A-Z]{2}$')
    store:str=Field(min_length=1,max_length=80)
    device:str=Field(min_length=1,max_length=80)
    metric:Literal['revenue','downloads','price','rating_count']
    date:date
    value:Optional[float]=None
    unit:str=Field(min_length=1,max_length=80)
    currency:str=Field(min_length=1,max_length=20)
    basis:str=Field(min_length=1,max_length=100)
    scope:str=Field(min_length=1,max_length=200)
    source:str=Field(min_length=1,max_length=100)
    period:Literal['daily','snapshot']
    is_estimate:bool=True
    source_revision:str=Field(default='',max_length=200)
    missing_reason:str=Field(default='',max_length=500)
    evidence_ids:list[str]=Field(min_length=1,max_length=30)
    @model_validator(mode='after')
    def values(self):
        if self.value is None and not self.missing_reason:raise ValueError('null需缺失原因')
        if self.value is not None and self.value<0 and self.metric!='revenue':raise ValueError('非收入指标不能为负')
        if self.date>date.today():raise ValueError('数据日期不能在未来')
        return self
class ImportInput(Strict):
    kind:Literal['evidence','observations','bundle']
    rows:list[dict]=Field(default_factory=list,max_length=1000)
    csv_text:str=Field(default='',max_length=1000000)
    mapping:dict[str,str]=Field(default_factory=dict)
    defaults:dict=Field(default_factory=dict)
class CommitImport(Strict):
    preview_id:str
class ScoreRun(Strict):
    as_of:date
class FromReport(Strict):
    report_id:str
    candidate_index:int=Field(ge=0)
    country:Literal['CN','US']
    store:str=Field(min_length=1,max_length=80)
class Capability(Strict):
    title:str=Field(min_length=1,max_length=200)
    source:str=Field(min_length=1,max_length=100)
    country:str=Field(min_length=1,max_length=20)
    store:str=Field(min_length=1,max_length=80)
    metric:str=Field(min_length=1,max_length=100)
    status:Literal['VERIFIED','NOT_ENTITLED','UNSUPPORTED','UNVERIFIED','PARTIAL']
    limitation:str=Field(min_length=1,max_length=4000)
    next_action:str=Field(min_length=1,max_length=4000)
    evidence_ids:list[str]=Field(default_factory=list,max_length=30)
    checked_at:date
class EntityMapping(Strict):
    product_name:str=Field(min_length=1,max_length=200)
    listings:list[str]=Field(min_length=2,max_length=30)
    reason:str=Field(min_length=1,max_length=2000)
    reviewer:str=Field(min_length=1,max_length=100)
    evidence_ids:list[str]=Field(min_length=1,max_length=30)


def register(app,queue,admin):
    metadata.create_all(queue.engine)
    def rows(kind):
        with queue.engine.connect() as c:return [dict(r) for r in c.execute(select(records).where(records.c.kind==kind).order_by(records.c.created_at.desc())).mappings()]
    def get(identity,kind=None,c=None):
        if c is None:
            with queue.engine.connect() as con:return get(identity,kind,con)
        r=c.execute(select(records).where(records.c.id==identity)).mappings().first()
        if not r or (kind and r['kind']!=kind):raise HTTPException(404,'记录不存在')
        return dict(r)
    def save(kind,data,identity=None,c=None):
        identity=identity or str(uuid.uuid4());now=time.time()
        if c is None:
            with queue.engine.begin() as con:return save(kind,data,identity,con)
        c.execute(records.insert().values(id=identity,kind=kind,version=1,data=data,created_at=now,updated_at=now))
        c.execute(history.insert().values(id=str(uuid.uuid4()),record_id=identity,version=1,data=data,created_at=now))
        return {'id':identity,'version':1}
    def change(identity,expected,data,c):
        n=c.execute(update(records).where(records.c.id==identity,records.c.version==expected).values(data=data,version=expected+1,updated_at=time.time())).rowcount
        if not n:raise HTTPException(409,'记录已更新，请刷新后重试')
        c.execute(history.insert().values(id=str(uuid.uuid4()),record_id=identity,version=expected+1,data=data,created_at=time.time()))
        return {'id':identity,'version':expected+1}
    def refs(ids,c=None):
        for identity in set(ids):get(identity,'evidence',c)
    def validate_op(data):
        ids=list(data['evidence_ids'])
        for v in data['factors'].values():ids+=v['evidence_ids']
        for v in data['penalties']:ids+=v['evidence_ids']
        refs(ids)
        for k,v in data['factors'].items():
            evidence=[get(x,'evidence')['data'] for x in v['evidence_ids']]
            if v['observed_at']>max(e['observed_at'] for e in evidence):raise HTTPException(422,'因子日期不能晚于引用事实日期')
            if v['quality']>max(e['quality'] for e in evidence):raise HTTPException(422,'因子可信度不能超过引用证据')
            if k in ('D','S','A') and not any(e['country']==data['country'] for e in evidence):raise HTTPException(422,'需求/供给/获客因子须有目标国家证据')
            if k=='S' and not any(e['claim_type']=='search' and not e['truncated'] for e in evidence):raise HTTPException(422,'供给评分需完整检索证据，搜索失败不能加分')
    @app.get('/api/evidence',dependencies=[Depends(admin)])
    def list_evidence():return rows('evidence')
    @app.get('/api/evidence/{identity}',dependencies=[Depends(admin)])
    def evidence_detail(identity:str):return get(identity,'evidence')
    @app.post('/api/evidence',dependencies=[Depends(admin)])
    def add_evidence(value:Evidence):
        data=value.model_dump(mode='json');data.update(content_hash=digest(data),collected_at=time.time());return save('evidence',data)
    @app.get('/api/capabilities',dependencies=[Depends(admin)])
    def capabilities():
        with queue.engine.connect() as c:
            batches=list(c.execute(select(results.c.job_id,results.c.bundle)).mappings())
        return {'registered':rows('capability'),'observed_batches':[dict(id=r['job_id'],context=r['bundle']['context'],status=r['bundle']['status'],rows=len(r['bundle']['rows']),metrics=sorted({m['name'] for v in r['bundle']['rows'] for m in v.get('metrics',[]) if m.get('value') is not None})) for r in batches], 'missing_document':'/api/backlog'}
    @app.post('/api/capabilities',dependencies=[Depends(admin)])
    def add_capability(value:Capability):
        refs(value.evidence_ids)
        if value.status=='VERIFIED' and not value.evidence_ids:raise HTTPException(422,'验证通过需证据')
        return save('capability',value.model_dump(mode='json'))
    @app.get('/api/entities',dependencies=[Depends(admin)])
    def entities():return rows('entity')
    @app.post('/api/entities',dependencies=[Depends(admin)])
    def add_entity(value:EntityMapping):
        refs(value.evidence_ids);return save('entity',value.model_dump(mode='json'))
    @app.get('/api/qualification-rules',dependencies=[Depends(admin)])
    def rules():return rows('rule')
    @app.post('/api/qualification-rules',dependencies=[Depends(admin)])
    def add_rule(value:Rule):
        refs(value.evidence_ids);return save('rule',value.model_dump(mode='json'))
    @app.get('/api/opportunities',dependencies=[Depends(admin)])
    def opportunities(country:str='',store:str='',track:str='',run_id:str='',offset:int=0,limit:int=50):
        if offset<0 or not 1<=limit<=200:raise HTTPException(422,'分页参数无效')
        if run_id:
            run=get(run_id,'score_run');items=run['data']['items'];as_of=run['data']['as_of']
        else:
            as_of=date.today().isoformat();items=[dict(r,score=score(r['data'],as_of)) for r in rows('opportunity')]
        items=[r for r in items if (not country or r['data']['country']==country) and (not store or r['data']['store']==store) and (not track or r['score']['cohort']==track)]
        items.sort(key=lambda r:(-(r['score']['adjusted'] if r['score']['adjusted'] is not None else -1),-r['score']['C'],-r['score']['exploration_priority'],r['id']))
        return dict(items=items[offset:offset+limit],total=len(items),run_id=run_id or None,as_of=as_of,score_version=VERSION,is_partial=any(r['score']['missing'] for r in items),source_coverage=sorted({e for r in items for e in r['data']['evidence_ids']}))
    @app.post('/api/opportunities',dependencies=[Depends(admin)])
    def create_op(value:Opportunity):
        d=value.model_dump(mode='json');validate_op(d);d['status']='NEEDS_EVIDENCE';return save('opportunity',d)
    @app.post('/api/opportunities/from-report',dependencies=[Depends(admin)])
    def from_report(value:FromReport):
        from .product import analyses
        with queue.engine.begin() as c:
            row=c.execute(select(analyses).where(analyses.c.id==value.report_id)).mappings().first()
            if not row or row['state']!='SUCCEEDED':raise HTTPException(422,'报告尚未完成')
            r=row['result'];candidates=r.get('model',{}).get('result',{}).get('candidates',[])
            if value.candidate_index>=len(candidates):raise HTTPException(422,'候选不存在')
            candidate=candidates[value.candidate_index];identity=digest({'report':value.report_id,'index':value.candidate_index,'country':value.country,'store':value.store})
            old=c.execute(select(records.c.id).where(records.c.id==identity)).first()
            if old:return {'id':identity,'duplicate':True}
            ids=[]
            for ev in r.get('evidence',[]):
                if ev['id'] not in candidate['evidence_ids']:continue
                eid=digest({'report':value.report_id,'evidence':ev['id']})
                if not c.execute(select(records.c.id).where(records.c.id==eid)).first():
                    try:raw=json.loads(ev['text']);ctx=raw['context']
                    except (ValueError,KeyError):
                        original=next((x for x in r.get('candidates',[]) if ev['id'] in x['evidence_ids']),None)
                        if not original:raise HTTPException(422,'原报告证据上下文无法还原')
                        raw={'name':original['name']};ctx=original['context']
                    data=Evidence(title=raw['name'],claim_type='market',source='diandian',source_url='',text=ev['text'],observed_at=ctx['data_date'],country=ctx['country'],store=ctx['store'],rights='已有账号采集，内部研究',quality=.5).model_dump(mode='json');data.update(report_id=value.report_id,original_evidence_id=ev['id'],collected_at=time.time(),content_hash=digest(data));save('evidence',data,eid,c)
                ids.append(eid)
            d=Opportunity(title=candidate['task'],who='待核验目标用户',task=candidate['task'],context=candidate['hypothesis'],country=value.country,store=value.store,evidence_ids=ids,counter_evidence='\n'.join(candidate['unknowns'])).model_dump(mode='json');d.update(status='NEEDS_EVIDENCE',report_id=value.report_id);return save('opportunity',d,identity,c)
    @app.get('/api/opportunities/{identity}',dependencies=[Depends(admin)])
    def op_detail(identity:str):
        r=get(identity,'opportunity');return dict(r,score=score(r['data'],date.today().isoformat()),experiments=[e for e in rows('experiment') if e['data']['opportunity_id']==identity])
    @app.put('/api/opportunities/{identity}',dependencies=[Depends(admin)])
    def edit_op(identity:str,value:EditOpportunity):
        d=value.model_dump(mode='json');expected=d.pop('expected_version');validate_op(d)
        with queue.engine.begin() as c:
            old=get(identity,'opportunity',c);d.update(status='NEEDS_EVIDENCE',decision={},last_edit_reason='功能或证据更新，重新核验资格和立项条件')
            if old['data'].get('report_id'):d['report_id']=old['data']['report_id']
            return change(identity,expected,d,c)
    @app.get('/api/opportunities/{identity}/history',dependencies=[Depends(admin)])
    def op_history(identity:str):
        get(identity,'opportunity')
        with queue.engine.connect() as c:return [dict(r) for r in c.execute(select(history).where(history.c.record_id==identity).order_by(history.c.version.desc())).mappings()]
    @app.post('/api/opportunities/{identity}/review',dependencies=[Depends(admin)])
    def review(identity:str,value:Decision):
        refs(value.evidence_ids)
        with queue.engine.begin() as c:
            old=get(identity,'opportunity',c);d=dict(old['data']);rs=[get(i,'rule',c) for i in value.rule_ids]
            if value.industry=='ELIGIBLE':
                if not d['feature_facts'].strip() or not rs:raise HTTPException(422,'可进入需具体功能事实和有效规则')
                for r in rs:
                    rule=r['data']
                    if rule['decision']!='ELIGIBLE' or rule['jurisdiction']!=d['country'] or rule['store'] not in ('*',d['store']) or rule['next_review_at']<date.today().isoformat():raise HTTPException(422,'规则过期、冲突或不适用于目标市场')
            if value.channel=='READY' and not value.baseline_path.strip():raise HTTPException(422,'READY需基础上架路径和材料依据')
            decision=value.model_dump(mode='json');decision.pop('expected_version');decision['rule_versions']={r['id']:r['version'] for r in rs};decision['valid_until']=min([r['data']['next_review_at'] for r in rs]+[(date.today()+timedelta(days=30)).isoformat()]);d['decision']=decision;d['status']='REJECTED' if value.industry=='EXCLUDED' or value.channel=='UNAVAILABLE' else 'NEEDS_EVIDENCE';return change(identity,value.expected_version,d,c)
    @app.post('/api/opportunities/{identity}/status',dependencies=[Depends(admin)])
    def transition(identity:str,value:Transition):
        with queue.engine.begin() as c:
            old=get(identity,'opportunity',c);d=dict(old['data']);s=score(d,date.today().isoformat())
            if value.status in ('QUALIFIED','VALIDATING','BUILD_CANDIDATE') and s['adjusted'] is None:raise HTTPException(422,'未通过主榜证据和资质门槛：'+'；'.join(s['reasons']))
            if value.status=='BUILD_CANDIDATE':
                experiments=[r['id'] for r in c.execute(select(records).where(records.c.kind=='experiment')).mappings() if r['data']['opportunity_id']==identity]
                outcomes_by_experiment={}
                for result in c.execute(select(records).where(records.c.kind=='experiment_result').order_by(records.c.created_at)).mappings():
                    if result['data']['experiment_id'] in experiments:outcomes_by_experiment[result['data']['experiment_id']]=result['data']
                outcomes=list(outcomes_by_experiment.values())
                if d['decision']['channel']!='READY' or not d['mvp'].strip() or not any(x['paid_users']>0 and x['window_mature'] and x['calculated']['contribution']>=0 and x['decision']=='pass' for x in outcomes):raise HTTPException(422,'立项需READY、MVP范围、成熟观察窗的真实付费与非负贡献结果')
            d.update(status=value.status,status_reason=value.reason,reviewer=value.reviewer);return change(identity,value.expected_version,d,c)
    @app.post('/api/score-runs',dependencies=[Depends(admin)])
    def score_run(value:ScoreRun):
        if value.as_of!=date.today():raise HTTPException(422,'历史时点请打开已保存快照，不能用今天数据伪造历史回测')
        as_of=value.as_of.isoformat();items=[]
        for r in rows('opportunity'):
            s=score(r['data'],as_of);sensitivity=[]
            for k in WEIGHTS:
                for scale in (.8,1.2):
                    w=dict(WEIGHTS);w[k]*=scale;t=sum(w.values());w={a:b/t for a,b in w.items()};sensitivity.append(score(r['data'],as_of,w)['adjusted'])
            items.append(dict(r,score=s,sensitivity=sensitivity))
        return save('score_run',dict(as_of=as_of,version=VERSION,weights=WEIGHTS,items=items,input_hash=digest(items),note='权重±20%敏感性情景，不是统计置信区间；未校准成功概率'))
    @app.get('/api/score-runs',dependencies=[Depends(admin)])
    def runs():return [dict(id=r['id'],created_at=r['created_at'],as_of=r['data']['as_of'],count=len(r['data']['items'])) for r in rows('score_run')]
    @app.get('/api/score-runs/{identity}',dependencies=[Depends(admin)])
    def run_detail(identity:str):return get(identity,'score_run')
    @app.get('/api/experiments',dependencies=[Depends(admin)])
    def experiments():return rows('experiment')
    @app.post('/api/experiments',dependencies=[Depends(admin)])
    def create_experiment(value:Experiment):
        get(value.opportunity_id,'opportunity');return save('experiment',value.model_dump(mode='json'))
    @app.get('/api/experiments/{identity}',dependencies=[Depends(admin)])
    def experiment_detail(identity:str):return dict(get(identity,'experiment'),results=[r for r in rows('experiment_result') if r['data']['experiment_id']==identity])
    @app.post('/api/experiments/{identity}/results',dependencies=[Depends(admin)])
    def add_result(identity:str,value:ExperimentResult):
        ex=get(identity,'experiment');refs(value.evidence_ids)
        if value.currency!=ex['data']['currency']:raise HTTPException(422,'币种须与实验一致')
        d=value.model_dump(mode='json');d.update(experiment_id=identity,calculated=economics(d))
        with queue.engine.begin() as c:
            result=save('experiment_result',d,c=c)
            op=get(ex['data']['opportunity_id'],'opportunity',c)
            if op['data']['status']=='BUILD_CANDIDATE' and (d['decision']!='pass' or d['paid_users']==0 or not d['window_mature'] or d['calculated']['contribution']<0):
                changed=dict(op['data'],status='VALIDATING',status_reason='新增实验结果未维持立项证据，需重新复核')
                change(op['id'],op['version'],changed,c)
            return result
    @app.get('/api/observations',dependencies=[Depends(admin)])
    def observations():return rows('observation')
    @app.get('/api/growth',dependencies=[Depends(admin)])
    def growth_view(as_of:str=''):
        as_of=as_of or date.today().isoformat();date.fromisoformat(as_of);groups={}
        for r in rows('observation'):
            d=r['data']
            if d['metric'] not in ('revenue','downloads') or d['period']!='daily' or any(d[k].lower() in ('unknown','未知') for k in ('basis','scope','currency')):continue
            key=digest({k:d[k] for k in ('listing_key','country','store','device','metric','unit','currency','basis','scope','source','period')});groups.setdefault(key,[]).append(d)
        return [dict(id=key,as_of=as_of,context={k:v for k,v in ds[0].items() if k not in ('value','date','evidence_ids','collected_at')},windows=growth(ds,as_of),evidence_ids=sorted({e for d in ds for e in d['evidence_ids']})) for key,ds in groups.items()]
    @app.post('/api/growth/{identity}/evidence',dependencies=[Depends(admin)])
    def capture_growth(identity:str,as_of:str=''):
        items=growth_view(as_of);item=next((x for x in items if x['id']==identity),None)
        if not item:raise HTTPException(404,'可比指标组不存在')
        ctx=item['context'];d=Evidence(title=ctx['listing_key'][:130]+' '+ctx['metric']+'窗口分析',claim_type='commercial' if ctx['metric']=='revenue' else 'demand',source='系统计算 / '+ctx['source'],text=json.dumps(item,ensure_ascii=False),observed_at=item['as_of'],country=ctx['country'],store=ctx['store'],rights='由已导入的有来源指标计算，仅内部研究',quality=.5).model_dump(mode='json');d.update(parent_evidence_ids=item['evidence_ids'],collected_at=time.time(),content_hash=digest(item));return save('evidence',d)
    @app.post('/api/imports/preview',dependencies=[Depends(admin)])
    def preview_import(value:ImportInput):
        incoming=value.rows
        if value.csv_text:
            incoming=list(csv.DictReader(io.StringIO(value.csv_text.lstrip('\ufeff'))))
            if len(incoming)>1000:raise HTTPException(422,'每批最多1000行')
        if not incoming:raise HTTPException(422,'文件没有数据')
        clean=[];errors=[]
        for i,row in enumerate(incoming):
            try:
                d=dict(value.defaults);d.update({value.mapping.get(k,k):v for k,v in row.items()})
                if value.kind=='bundle':validate_bundle(d)
                else:
                    if isinstance(d.get('evidence_ids'),str):d['evidence_ids']=[x.strip() for x in d['evidence_ids'].split('|') if x.strip()]
                    if d.get('value')=='':d['value']=None
                    cls=Evidence if value.kind=='evidence' else Observation;d=cls.model_validate(d).model_dump(mode='json')
                    if value.kind=='observations':refs(d['evidence_ids'])
                clean.append(d)
            except (ValueError,HTTPException,KeyError,TypeError):errors.append({'row':i+1,'reason':'字段、日期、口径或证据引用无效；请核对模板'})
        identity=save('import_preview',dict(kind=value.kind,rows=clean,errors=errors,source_hash=digest(incoming)))['id']
        return dict(id=identity,valid_rows=len(clean),errors=errors,sample=clean[:5],can_commit=not errors)
    @app.post('/api/imports',dependencies=[Depends(admin)])
    def commit_import(value:CommitImport):
        with queue.engine.begin() as c:
            c.execute(select(records.c.id).where(records.c.id==value.preview_id).with_for_update()).first()
            r=get(value.preview_id,'import_preview',c);d=r['data']
            if d['errors']:raise HTTPException(422,'存在错误，请修复后重新预览')
            if d.get('committed'):return d['committed']
            count=0
            for item in d['rows']:
                kind={'evidence':'evidence','observations':'observation','bundle':'imported_bundle'}[d['kind']];identity=digest({'kind':kind,'data':item})
                if c.execute(select(records.c.id).where(records.c.id==identity)).first():continue
                if kind=='imported_bundle':
                    jid='import-'+identity;c.execute(jobs.insert().values(id=jid,request_key=jid,payload={'recipe':'manual-import','context':item['context']},state=item['status'],attempts=0,created_at=time.time(),result_hash=digest(item)));c.execute(results.insert().values(job_id=jid,hash=digest(item),bundle=item))
                data=dict(item,collected_at=time.time(),content_hash=digest(item));save(kind,data,identity,c);count+=1
            result={'imported':count,'preview_id':value.preview_id};d=dict(d,committed=result);change(r['id'],r['version'],d,c);return result
    @app.get('/api/backlog',dependencies=[Depends(admin)])
    def backlog():
        from pathlib import Path
        return {'markdown':(Path(__file__).parent/'static'/'backlog.md').read_text()}
    @app.get('/api/lab/schemas',dependencies=[Depends(admin)])
    def schemas():return {k:v.model_json_schema() for k,v in dict(evidence=Evidence,opportunity=Opportunity,rule=Rule,decision=Decision,experiment=Experiment,result=ExperimentResult,capability=Capability,entity=EntityMapping,observation=Observation).items()}
    @app.post('/api/jobs/{identity}/retry',dependencies=[Depends(admin)])
    def retry(identity:str):
        with queue.engine.connect() as c:r=c.execute(select(jobs).where(jobs.c.id==identity)).mappings().first()
        if not r:raise HTTPException(404,'任务不存在')
        if r['state'] not in ('FAILED','PARTIAL','CANCELLED'):raise HTTPException(409,'此状态不可重试')
        if r['payload']['recipe']=='manual-import':raise HTTPException(422,'人工导入请重新上传')
        return queue.submit(dict(request_key='retry:'+identity+':'+str(uuid.uuid4()),**r['payload']))
