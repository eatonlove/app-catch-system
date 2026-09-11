"""Versioned, deterministic decision support; never a success probability."""
import math
from datetime import date

VERSION = 'opportunity-v1.0'
WEIGHTS = dict(M=.20, D=.15, G=.15, S=.15, P=.10, A=.15, B=.10)

def score(op, as_of, weights=None):
    weights = weights or WEIGHTS
    factors = op.get('factors', {})
    valid = {k: v for k, v in factors.items() if k in weights and v.get('value') is not None and v.get('quality', 0)>0 and v.get('evidence_ids')}
    c = sum(weights[k] for k in valid)
    reasons = []
    decision = op.get('decision', {})
    industry, channel = decision.get('industry', 'REVIEW'), decision.get('channel', 'UNKNOWN')
    if op.get('country')=='US' and op.get('store')=='harmony':channel='UNAVAILABLE';reasons.append('本期不支持美国手机原生鸿蒙发行')
    if industry != 'ELIGIBLE': reasons.append('行业可进入性尚未确认' if industry != 'EXCLUDED' else '专项许可/业务约束排除')
    if channel in ('UNAVAILABLE', 'UNKNOWN'): reasons.append('渠道不可发行或条件未知')
    if not decision.get('valid_until') or decision['valid_until'] < as_of: reasons.append('资质复核缺失或已过期')
    if c < .70: reasons.append('有效因子权重不足70%')
    for k in ('M','D','A'):
        if k not in valid: reasons.append(k+'关键证据缺失')
    if op.get('track') == 'growth' and not op.get('midterm_verified'): reasons.append('增长轨缺少可比28日数据')
    if op.get('strict_baseline') and channel != 'READY': reasons.append('严格模式要求基础手续已完成')
    ages = {k:max(0,(date.fromisoformat(as_of)-date.fromisoformat(v['observed_at'])).days-v.get('normal_delay',0)) for k,v in valid.items()}
    if any(ages[k]>30 for k in ('M','D','A') if k in ages): reasons.append('关键证据超过30天未更新')
    q=sum(weights[k]*v['quality'] for k,v in valid.items())/c if c else 0
    f=sum(weights[k]*2**(-ages[k]/v.get('half_life',7)) for k,v in valid.items())/c if c else 0
    confidence=.30*c+.25*q+.20*f+.15*op.get('entity_confidence',0)+.10*op.get('local_evidence',0)
    raw=sum(weights[k]*v['value'] for k,v in valid.items())/c if c else None
    if confidence < .65: reasons.append('证据可信度低于65%')
    penalty=min(20,sum(p['value'] for p in op.get('penalties',[])))
    adjusted=max(0,raw*(.5+.5*confidence)-penalty) if raw is not None and not reasons else None
    blocked=industry=='EXCLUDED' or channel=='UNAVAILABLE' or op.get('status')=='REJECTED'
    cohort='excluded' if blocked else 'validation' if adjusted is not None else 'exploration'
    if op.get('status')=='PARKED':cohort='parked';adjusted=None
    if blocked:adjusted=None
    if cohort=='validation' and op.get('status')=='BUILD_CANDIDATE':cohort='build'
    return dict(version=VERSION,as_of=as_of,cohort=cohort,factors=valid,missing=[k for k in weights if k not in valid],coverage=c,Q=q,F=f,C=confidence,raw=raw,penalty=penalty,adjusted=adjusted,reasons=reasons,exploration_priority=op.get('impact',3)*op.get('decision_value',3)/op.get('validation_hours',8),contributions={k:weights[k]*v['value']/c for k,v in valid.items()})

def wilson(events, n):
    if not n:return None
    z=1.959963984540054;p=events/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den
    delta=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0,center-delta),min(1,center+delta)]

def economics(value):
    n=value['eligible_n'];paid=value['paid_users'];refunds=value['refunded_users']
    from decimal import Decimal
    money=lambda k:Decimal(str(value[k]))
    net=money('receipts') if value['income_basis']=='net' else money('receipts')-money('refund_amount')-money('platform_fees')-money('taxes')
    contribution=net-money('delivery_cost')-money('support_cost')-money('acquisition_cost')
    amount=lambda x:float(x.quantize(Decimal('.01')))
    return dict(paid_conversion=paid/n if n else None,paid_wilson95=wilson(paid,n),refund_rate=refunds/paid if paid else None,net_income=amount(net),contribution=amount(contribution),after_fixed=amount(contribution-money('fixed_cost')),currency=value['currency'],provisional=not value['window_mature'],renewal_rate=(value['renewals']/value['renewal_eligible'] if value['window_mature'] and value['renewal_eligible'] else None))


def growth(observations, as_of, epsilon=1):
    from datetime import timedelta
    end=date.fromisoformat(as_of);series={}
    for r in sorted(observations,key=lambda x:x['collected_at']):
        if r['date']<=as_of:series[r['date']]=r.get('value')
    output={}
    for w in (7,28,90):
        groups=[[series.get((end-timedelta(days=i)).isoformat()) for i in range(start,start+w)] for start in (0,w)]
        values=[[float(v) for v in g if v is not None] for g in groups]
        coverage=[len(v)/w for v in values];item=dict(coverage=coverage,log_growth=None,absolute_change=None,low_base=None)
        if min(coverage)<.9:item['reason']='INCOMPLETE_HISTORY'
        elif any(v<0 for g in values for v in g):item['reason']='NEGATIVE_REVENUE_REVIEW'
        else:
            a,b=[sum(v)/len(v) for v in values];item.update(current_mean=a,previous_mean=b,log_growth=math.log((a+epsilon)/(b+epsilon)),absolute_change=a-b,low_base=b<epsilon,reason='LOW_BASELINE' if b<epsilon else None)
        output[str(w)]=item
    return output
