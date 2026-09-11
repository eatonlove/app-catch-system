"""Pure helpers for visible input selection and evidence provenance."""
import json

def choose_evidence(report,limit=30):
    lookup={e['id']:e for e in report['evidence']};groups={}
    for c in report['candidates']:
        key=tuple(c['context'][k] for k in ('country','store','category','chart'))
        groups.setdefault(key,[]).append(lookup[c['evidence_ids'][0]])
    selected=[]
    while any(groups.values()) and len(selected)<limit:
        for group in groups.values():
            if group and len(selected)<limit:
                item=group.pop(0)
                if len(json.dumps(selected+[item],ensure_ascii=False))<=40000:selected.append(item)
    return selected

def overview(report,selected=None,sources=None):
    candidates=report.get('candidates',[]);by_id={ref:c for c in candidates for ref in c['evidence_ids']}
    reconstructed=sources is None
    if reconstructed:
        groups={}
        for e in report.get('evidence',[]):
            c=by_id.get(e['id']);job=e['id'].split(':')[0]
            if c:
                row=groups.setdefault(job,{'id':job,'context':c['context'],'row_count':0,'status':'报告已存证据'})
                row['row_count']+=1
        sources=list(groups.values())
    dates=sorted({s['context']['data_date'] for s in sources})
    comparable={str(n):sum(c['windows'][str(n)]['rank_improvement'] is not None for c in candidates) for n in (7,28,90)}
    gaps=[];steps=[]
    if not any(comparable.values()):
        gaps.append('没有可计算7/28/90日名次变化的基准日，当前不能验证增长。')
        steps.append('为同一国家、商店、类别与榜单补采基准日，并连续观察；不要混算不同渠道名次。')
    else:gaps.append('基准日名次差只反映榜单变化，不代表持续增长或收入增长。')
    fields=set()
    for e in report.get('evidence',[]):
        try:fields.update(json.loads(e['text']).keys())
        except (ValueError,TypeError):pass
    if not {'revenue','paying_users','payment_rate'} & fields:
        gaps.append('榜单没有收入、付费人数或付费率；补充证据中的商业支持需逐条核验口径，系统不从文本自动推算收益。' if any(s.get('evidence_id') for s in sources) else '输入没有收入、付费人数或付费率，无法验证商业回报。')
        steps.append('补充可访问的收入/付费证据与口径；平台估算需标明估算。')
    gaps.append('补充证据已纳入；仍需逐条核对评论、功能、关键词及商业口径，不能仅凭证据标题认定已验证。' if any(s.get('evidence_id') for s in sources) else '榜单字段不包含评论原文、功能流程或关键词搜索量，痛点与搜索机会仍需调研。')
    steps.append('先用综合选品或MVP方向寻找待验证线索，再补竞品功能、差评和目标市场搜索结果。')
    if len({s['context']['country'] for s in sources})<2:gaps.append('只有一个国家的来源，不能据此确认中美市场空白。')
    model_inputs=None if selected is None else [{'id':e['id'],'name':by_id.get(e['id'],{}).get('name',e['id']), 'context':by_id.get(e['id'],{}).get('context',{}),'rank':by_id.get(e['id'],{}).get('rank')} for e in selected]
    return {'sources':sources,'source_record_count':sum(s['row_count'] for s in sources),'candidate_count':report.get('total_candidates',len(candidates)),'displayed_count':len(candidates),'dates':dates,'comparable':comparable,'model_inputs':model_inputs,'gaps':gaps,'next_steps':steps,'reconstructed':reconstructed,'sampling':'旧报告只还原已保存的输入名单，不以当前抽样规则推断历史行为。' if reconstructed else '按国家、商店、类别和榜单轮流取样，各组优先取排名变化/名次靠前的记录；受所选条数及40000字符上限约束。不是全市场研究。'}
