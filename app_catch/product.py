"""Persistent plans, evidence-led reports, feedback and bounded analysis queue."""
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Table, Column, String, Float, JSON, Integer, select, update, func
from .cloud import metadata, jobs, results, nodes
from .catalog import CATALOG, context_for
from .core import digest
from .llm import research

plans=Table('ac_plans',metadata,Column('id',String,primary_key=True),Column('name',String),Column('catalog_id',String),Column('enabled',Integer),Column('last_day',String))
analyses=Table('ac_analyses',metadata,Column('id',String,primary_key=True),Column('state',String),Column('requested_at',Float),Column('started_at',Float),Column('use_model',Integer),Column('result',JSON),Column('error',String),Column('filters',JSON))
feedback=Table('ac_feedback',metadata,Column('key',String,primary_key=True),Column('value',JSON),Column('updated_at',Float))

class PlanInput(BaseModel):
    name:str=Field(min_length=1,max_length=80)
    catalog_id:str
    enabled:bool=True
class AnalysisInput(BaseModel):
    use_model:bool=False
    country:str=''
    store:str=''
class FeedbackInput(BaseModel):
    decision:str=Field(pattern='^(watch|validate|reject|develop)$')
    qualification:str=Field(pattern='^(UNREVIEWED|REQUIRES_LICENSE|EXCLUDED|REVIEWED_ELIGIBLE)$')
    note:str=Field(max_length=4000)
    experiment:str=Field(default='',max_length=4000)
    evidence_refs:list[str]=Field(default_factory=list,max_length=30)


def build_report(bundles, filters=None):
    filters=filters or {}; history={}; evidence=[]
    for run_id,b in bundles:
        c=b['context']
        if any(filters.get(k) and filters[k]!=c[k] for k in ('country','store')):continue
        if b['status']!='SUCCEEDED':continue
        for row in b['rows']:
            key=digest({'listing':row['listing_key'],'scope':{k:v for k,v in c.items() if k!='data_date'}})
            day=c['data_date']; bucket=history.setdefault(key,{})
            if day not in bucket or b['collected_at']>bucket[day][1]['collected_at']:
                bucket[day]=(run_id,b,row)
    candidates=[]
    for key,days in history.items():
        day=max(days);run_id,b,row=days[day];c=b['context']
        def rank(r):
            m=next((x for x in r['metrics'] if x['name']=='rank'),None)
            return int(m['value']) if m and m.get('value') is not None else None
        current=rank(row)
        windows={}
        end=datetime.strptime(day,'%Y-%m-%d')
        for length in (7,28,90):
            start=(end-timedelta(days=length)).strftime('%Y-%m-%d')
            previous=rank(days[start][2]) if start in days else None
            windows[str(length)]={'rank_improvement':previous-current if previous and current else None,'baseline_date':start,'observed_days':sum((end-timedelta(days=i)).strftime('%Y-%m-%d') in days for i in range(length+1))}
        ev=run_id+':'+row['listing_key'];name=row['name'];raw=row.get('raw_columns',{})
        signal='榜单观察'
        for label,terms in [('照片与存储整理',('clean','清理','照片','photo')),('设备遥控',('remote','遥控')),('身份验证工具',('authenticator','验证器')),('文档处理',('pdf','扫描','文档'))]:
            if any(t in name.lower() for t in terms):signal=label;break
        candidates.append({'key':key,'name':name,'task':signal,'context':c,'rank':current,'windows':windows,
            'observed_days':len(days),'evidence_ids':[ev],'source_url':row.get('detail_url',b['source_url']),
            'developer':row.get('developer'),'qualification':'UNREVIEWED',
            'unknowns':['收入、付费用户数未由排名推导','跨市场需求与替代品需验证','具体功能资质待人工核验']})
        evidence.append({'id':ev,'text':json.dumps({'name':name,'context':c,'rank':current,'observed_days':len(days),'raw_columns':raw},ensure_ascii=False)[:2000]})
    candidates.sort(key=lambda x:(-(x['windows']['7']['rank_improvement'] or 0),-x['observed_days'],x['rank'] or 999999))
    evidence_by_id={item['id']:item for item in evidence}
    selected=candidates[:200]
    selected_ids=list(dict.fromkeys(ref for item in selected for ref in item['evidence_ids']))
    return {'kind':'research_priority_not_profit_prediction','generated_at':time.time(),'candidates':selected,
            'total_candidates':len(candidates),'evidence':[evidence_by_id[ref] for ref in selected_ids],
            'empty':not candidates,'warnings':['排序依据7日名次改善、观察天数、当前名次；不是收入机会分','仅比较同国家、渠道、类别和榜单；榜外未知不补零','界面最多返回前200项；模型只研究前15项证据']}


def tick(queue, model_fn=research):
    now=time.time();day=(datetime.now(timezone(timedelta(hours=8)))-timedelta(days=1)).date().isoformat()
    with queue.engine.connect() as c:active=list(c.execute(select(plans).where(plans.c.enabled==1)).mappings())
    for p in active:
        if p['last_day']==day:continue
        queue.submit({'request_key':'plan:'+p['id']+':'+day,'recipe':p['catalog_id'],'context':context_for(p['catalog_id'],day)})
        with queue.engine.begin() as c:c.execute(update(plans).where(plans.c.id==p['id']).values(last_day=day))
    with queue.engine.begin() as c:
        # Interrupted paid calls are not retried automatically; they may have been billed.
        c.execute(update(analyses).where(analyses.c.state=='RUNNING',analyses.c.started_at<now-300).values(state='UNKNOWN',error='INTERRUPTED_REVIEW_BEFORE_RETRY'))
        row=c.execute(select(analyses).where(analyses.c.state=='PENDING').order_by(analyses.c.requested_at).limit(1).with_for_update(skip_locked=True)).mappings().first()
        if not row:return
        if not c.execute(update(analyses).where(analyses.c.id==row['id'],analyses.c.state=='PENDING').values(state='RUNNING',started_at=now)).rowcount:return
    try:
        with queue.engine.connect() as c:
            source=[(r['job_id'],r['bundle']) for r in c.execute(select(results)).mappings()]
        report=build_report(source,row['filters'])
        if row['use_model']:
            if not report['evidence']:raise ValueError('NO_EVIDENCE')
            limit=int(os.getenv('AC_MODEL_DAILY_LIMIT','10'))
            midnight=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
            with queue.engine.connect() as c:
                count=c.scalar(select(func.count()).select_from(analyses).where(analyses.c.use_model==1,analyses.c.started_at>=midnight))
            if count>limit:raise ValueError('DAILY_CALL_BUDGET_EXCEEDED')
            report['model']=model_fn(report['evidence'][:15],os.environ['AC_LLM_ENDPOINT'],os.environ['AC_LLM_MODEL'],os.environ['AC_LLM_API_KEY'],os.getenv('AC_MODEL_CACHE','data/model-cache'))
        with queue.engine.begin() as c:c.execute(update(analyses).where(analyses.c.id==row['id'],analyses.c.state=='RUNNING').values(state='SUCCEEDED',result=report))
    except Exception as e:
        import httpx
        code='MODEL_RESPONSE_UNCERTAIN' if isinstance(e,httpx.TransportError) else str(e) if isinstance(e,(ValueError,KeyError)) else 'ANALYSIS_FAILED'
        with queue.engine.begin() as c:c.execute(update(analyses).where(analyses.c.id==row['id']).values(state='UNKNOWN' if isinstance(e,httpx.TransportError) else 'FAILED',error=code[:120]))


def register(app,queue,admin):
    metadata.create_all(queue.engine)
    @app.get('/api/catalog',dependencies=[Depends(admin)])
    def catalog():return CATALOG
    @app.get('/api/status',dependencies=[Depends(admin)])
    def status():
        with queue.engine.connect() as c:
            ns=[dict(x) for x in c.execute(select(nodes)).mappings()]
            counts={r[0]:r[1] for r in c.execute(select(jobs.c.state,func.count()).group_by(jobs.c.state))}
        return {'nodes':ns,'counts':counts,'model_configured':all(os.getenv(k) for k in ['AC_LLM_ENDPOINT','AC_LLM_MODEL','AC_LLM_API_KEY']), 'model':os.getenv('AC_LLM_MODEL','未配置'),'daily_call_limit':int(os.getenv('AC_MODEL_DAILY_LIMIT','10'))}
    @app.get('/api/plans',dependencies=[Depends(admin)])
    def get_plans():
        with queue.engine.connect() as c:return [dict(x) for x in c.execute(select(plans)).mappings()]
    @app.post('/api/plans',dependencies=[Depends(admin)])
    def add_plan(value:PlanInput):
        if value.catalog_id not in CATALOG:raise HTTPException(422,'UNKNOWN_CATALOG')
        identity=str(uuid.uuid4())
        with queue.engine.begin() as c:c.execute(plans.insert().values(id=identity,name=value.name,catalog_id=value.catalog_id,enabled=int(value.enabled)))
        return {'id':identity}
    @app.post('/api/plans/{identity}/toggle',dependencies=[Depends(admin)])
    def toggle(identity:str):
        with queue.engine.begin() as c:
            row=c.execute(select(plans).where(plans.c.id==identity).with_for_update()).mappings().first()
            if not row:raise HTTPException(404,'NOT_FOUND')
            c.execute(update(plans).where(plans.c.id==identity).values(enabled=1-row['enabled']))
        return {'ok':True}
    @app.post('/api/analyses',dependencies=[Depends(admin)])
    def analyze(value:AnalysisInput):
        if value.use_model and not all(os.getenv(k) for k in ['AC_LLM_ENDPOINT','AC_LLM_MODEL','AC_LLM_API_KEY']):raise HTTPException(409,'MODEL_CONFIG_REQUIRED')
        identity=str(uuid.uuid4())
        with queue.engine.begin() as c:c.execute(analyses.insert().values(id=identity,state='PENDING',requested_at=time.time(),use_model=int(value.use_model),filters={'country':value.country,'store':value.store}))
        return {'id':identity}
    @app.get('/api/analyses',dependencies=[Depends(admin)])
    def analysis_list():
        with queue.engine.connect() as c:return [dict(r) for r in c.execute(select(analyses.c.id,analyses.c.state,analyses.c.requested_at,analyses.c.use_model,analyses.c.error).order_by(analyses.c.requested_at.desc()).limit(100)).mappings()]
    @app.get('/api/analyses/{identity}',dependencies=[Depends(admin)])
    def report(identity:str):
        with queue.engine.connect() as c:row=c.execute(select(analyses).where(analyses.c.id==identity)).mappings().first()
        if not row:raise HTTPException(404,'NOT_FOUND')
        return dict(row)
    @app.get('/api/feedback',dependencies=[Depends(admin)])
    def notes():
        with queue.engine.connect() as c:return {r['key']:r['value'] for r in c.execute(select(feedback)).mappings()}
    @app.put('/api/feedback/{key}',dependencies=[Depends(admin)])
    def save_note(key:str,value:FeedbackInput):
        if len(key)!=64:raise HTTPException(422,'INVALID_KEY')
        if value.decision=='develop' and (value.qualification!='REVIEWED_ELIGIBLE' or not value.note.strip() or not value.evidence_refs):raise HTTPException(422,'QUALIFICATION_REVIEW_REQUIRED')
        with queue.engine.begin() as c:
            if not c.execute(update(feedback).where(feedback.c.key==key).values(value=value.model_dump(),updated_at=time.time())).rowcount:c.execute(feedback.insert().values(key=key,value=value.model_dump(),updated_at=time.time()))
        return {'ok':True}
