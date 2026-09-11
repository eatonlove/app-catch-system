"""Observed table DOM adapter. No private APIs or browser storage access."""
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from .browser import session, CollectionError
from .catalog import CATALOG, CONTEXT_KEYS
from .core import now, write_json, safe_url, number, validate_bundle, digest

TABLE_JS = '''root => {
 const head=root.querySelector('.dd-table-head');
 const headers=[...head.children].filter(e=>e.classList.contains('el-col')).map(e=>e.innerText.trim());
 return {headers,rows:[...root.querySelectorAll('.dd-hover-row')].map(row=>({
  cells:[...row.children].filter(e=>e.classList.contains('el-col')).map(e=>e.innerText.trim()),
  name:row.querySelector('.dd-app-info .name a')?.innerText.trim(),
  url:row.querySelector('.dd-app-info .name a')?.href,
  developer:row.querySelector('.develop-info')?.innerText.trim()
 }))};}'''

def parse_table(table, context):
    headers = table['headers']
    if not {'应用','最后更新'}.issubset(headers) or not ({'排名','分类排名','总榜'} & set(headers)):
        raise CollectionError('SCHEMA_CHANGED','Unexpected table headers')
    output=[]
    for raw in table['rows']:
        if len(raw['cells']) != len(headers) or not raw.get('name') or not raw.get('url'):
            raise CollectionError('SCHEMA_CHANGED','Incomplete table row')
        cells=dict(zip(headers,raw['cells']))
        # Overall charts use overall rank; category charts use category rank.
        label='排名' if '排名' in cells else '总榜' if context['category']=='总榜' else '分类排名'
        text=cells.get(label,'').split('\n')[0].strip()
        if not re.fullmatch(r'\d+',text):
            raise CollectionError('SCHEMA_CHANGED','Rank is not a positive integer')
        rank=int(text)
        if rank<1:raise CollectionError('SCHEMA_CHANGED','Invalid rank')
        url=safe_url(raw['url'])
        app_id=urlsplit(url).path.split('/')[2]
        metrics=[{'name':'rank','value':str(rank),'raw':text,'unit':'position','basis':'observed','scope':context['chart'],'period':'snapshot','is_estimate':False}]
        for col,metric in [('综合评分','rating'),('评分数','rating_count')]:
            if col in cells:
                metrics.append({'name':metric,'value':number(cells[col]),'raw':cells[col],'unit':'score' if metric=='rating' else 'count','basis':'observed','scope':'store','period':'snapshot','is_estimate':False})
        output.append({'listing_key':context['store']+':'+app_id,'name':raw['name'],'detail_url':url,
                       'developer':raw.get('developer'),'raw_columns':cells,'metrics':metrics})
    return output

def collect_diandian(profile, recipe, params, output, headless=False, cancelled=lambda:False):
    name=recipe['catalog_id']; spec=CATALOG[name]
    if any(params[k]!=spec[k] for k in CONTEXT_KEYS):
        raise CollectionError('CONTEXT_MISMATCH','Catalog context mismatch')
    day=datetime.strptime(params['data_date'],'%Y-%m-%d').replace(tzinfo=timezone(timedelta(hours=8)))
    stamp=int(day.timestamp()*1000)
    url='https://app.diandian.com'+spec['path']+'?time='+str(stamp)+'&timetype=custom'
    if params['market']=='appstore':url+='&device=1'
    top=int(recipe.get('top_k',100))
    if not 1<=top<=500:raise ValueError('Top K must be 1..500')
    target=Path(output);target.mkdir(parents=True,exist_ok=True)
    started=now(); collected={}; state='PARTIAL'
    with session(profile,headless) as browser:
        page=browser.pages[0] if browser.pages else browser.new_page()
        page.goto(url,wait_until='domcontentloaded')
        root=page.locator('.dd-table-wrap').filter(has=page.locator('.dd-table-head'))
        try:root.wait_for(state='visible',timeout=30000)
        except Exception as exc:raise CollectionError('LOGIN_OR_PAGE_REQUIRED','Login, permission or page requires attention') from exc
        def guard():
            if cancelled():raise CollectionError('CANCELLED','Lease or task cancelled')
            if urlsplit(page.url).path != spec['path']:raise CollectionError('CONTEXT_MISMATCH','Unexpected route')
            if not all(x in page.title() for x in spec['title']):raise CollectionError('CONTEXT_MISMATCH','Unexpected title')
            value=page.get_by_placeholder('自定义',exact=True).input_value()
            expected=day.strftime('%m月%d日')
            if expected not in value:raise CollectionError('CONTEXT_MISMATCH','Unexpected data date')
            if root.count()!=1:raise CollectionError('SCHEMA_CHANGED','Ambiguous chart')
        guard(); stagnant=0
        for batch in range(35):
            guard();before=len(collected)
            for row in parse_table(root.evaluate(TABLE_JS),params):collected[row['listing_key']]=row
            write_json(target/'checkpoint.json',{'state':'RUNNING','rows':len(collected),'batch':batch,'context':params})
            if len(collected)>=top:state='SUCCEEDED';break
            stagnant=stagnant+1 if before==len(collected) else 0
            if stagnant>=4:break
            root.locator('.dd-hover-row').last.scroll_into_view_if_needed()
            row_locator=root.locator('.dd-hover-row').last
            row_locator.hover()
            if stagnant:
                page.mouse.wheel(0,-350)
                page.wait_for_timeout(200)
            page.mouse.wheel(0,1000)
            page.wait_for_timeout(1400)
        guard()
        rows=sorted(collected.values(),key=lambda r:int(r['metrics'][0]['value']))[:top]
        if not rows:raise CollectionError('SCHEMA_CHANGED','No rows')
        ranks=[int(r['metrics'][0]['value']) for r in rows]
        if state=='SUCCEEDED' and ranks != list(range(1,top+1)):
            state='PARTIAL'
        bundle={'schema_version':1,'source':'diandian','source_url':safe_url(page.url),'collected_at':started,
                'finished_at':now(),'context':params,'context_verified':True,'status':state,'rows':rows,
                'coverage':{'requested_top_k':top,'observed_rows':len(rows),'rank_contiguous':ranks==list(range(1,len(rows)+1))},
                'recipe_hash':digest(recipe),'completeness_note':'Top K scope, not whole-market coverage'}
        validate_bundle(bundle);write_json(target/'bundle.json',bundle)
        write_json(target/'checkpoint.json',{'state':state,'rows':len(rows)})
        return bundle
