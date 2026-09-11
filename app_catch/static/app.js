'use strict';
const $=id=>document.getElementById(id);
let catalog={},directions=[],currentReport=null,notes={},detailFinished=false,refreshing=false;
let researchSources=[],previewSequence=0;
const route=location.pathname.match(/^\/(collections|reports)\/([^/]+)$/);
const stateLabel=s=>({PENDING:'排队中',RUNNING:'处理中',SUCCEEDED:'已完成',PARTIAL:'部分完成',FAILED:'失败',UNKNOWN:'结果待确认',CANCELLED:'已取消'}[s]||s);
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function notice(text){$('notice').textContent=text||''}
async function api(path,method='GET',body){const r=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'appcatch'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok){if(r.status===401)locked();throw new Error(typeof data.detail==='string'?data.detail:'请求参数不符合接口要求')}return data}
function locked(){$('workspace').hidden=true;$('login').hidden=false;$('logout').hidden=true}
function empty(root,text){root.replaceChildren(el('div',text,'empty'))}
function table(root,headers,rows){const wrap=el('div',undefined,'table-wrap'),t=el('table'),head=el('tr');headers.forEach(x=>head.append(el('th',x)));t.append(head);rows.forEach(values=>{const tr=el('tr');values.forEach(x=>{const td=el('td');td.append(x instanceof Node?x:document.createTextNode(String(x??'未知')));tr.append(td)});t.append(tr)});wrap.append(t);root.replaceChildren(wrap)}
function button(text,fn){const b=el('button',text);b.type='button';b.onclick=()=>Promise.resolve().then(fn).catch(e=>notice(e.message));return b}
function link(text,url,newTab=false){const a=el('a',text,'action-link');a.href=url;if(newTab){a.target='_blank';a.rel='noopener noreferrer'}return a}
function actions(...items){const d=el('div',undefined,'actions');d.append(...items);return d}
function date(t){return new Date(typeof t==='number'?t*1000:t).toLocaleString()}
function scope(c){return [({US:'美国',CN:'中国'}[c.country]||c.country),({appstore:'App Store',googleplay:'Google Play',huawei:'华为',harmony:'鸿蒙'}[c.store]||c.store),c.category,({grossing:'畅销榜',free:'免费/应用榜',paid:'付费榜'}[c.chart]||c.chart),c.data_date].filter(Boolean).join(' / ')}
function showPage(id,title){document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==id);$('breadcrumb').textContent=title}
function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
async function refresh(){
 if(refreshing)return;refreshing=true;
 try{
  if(route){if(!detailFinished)await renderDetail();return}
  const [s,j,p,r,n]=await Promise.all(['/api/status','/api/jobs','/api/plans','/api/analyses','/api/feedback'].map(x=>api(x)));notes=n;
  $('stats').replaceChildren();[[s.nodes.some(n=>Date.now()/1000-n.last_seen<90)?'在线':'离线','Mac 采集节点'],[j.filter(x=>['RUNNING','PENDING'].includes(x.state)).length,'待处理 / 运行中'],[j.filter(x=>x.state==='SUCCEEDED').length,'最近成功任务']].forEach(([v,k])=>{const d=el('div',undefined,'stat');d.append(el('span',k),el('strong',v));$('stats').append(d)});
  if(j.length)table($('jobs'),['入口 / 日期','状态','尝试','操作'],j.map(x=>[x.payload.recipe+' · '+x.payload.context.data_date,stateLabel(x.state)+(x.error_code?' / '+x.error_code:''),x.attempts,actions(link('查看数据','/collections/'+x.id),...(['PENDING','RUNNING'].includes(x.state)?[button('取消',async()=>{await api('/api/jobs/'+x.id+'/cancel','POST');await refreshLater()})]:[]))]));else empty($('jobs'),'还没有采集任务。先在「采集计划」选择一个入口。');
  if(p.length)table($('plans'),['每日计划','状态','操作'],p.map(x=>[x.name,x.enabled?'启用':'暂停',button(x.enabled?'暂停':'启用',async()=>{await api('/api/plans/'+x.id+'/toggle','POST');await refreshLater()})]));else empty($('plans'),'暂无每日计划');
  if(r.length)table($('reports'),['研究时间','分析方向','状态','报告'],r.map(x=>[date(x.requested_at),x.use_model?(x.filters?.prompt_snapshot?.title||'综合选品'):'榜单趋势',stateLabel(x.state)+(x.error?' / '+x.error:''),link('新页面查看','/reports/'+x.id,true)]));else empty($('reports'),'采集完成后，选择方向生成第一份研究报告。');
  $('configuration').replaceChildren(el('h2','模型：'+s.model),el('p',s.model_configured?'模型配置完整；选择AI研究将调用第三方 API。':'未配置模型；仍可使用榜单趋势分析。'),el('p','每日最多 '+s.daily_call_limit+' 次模型任务；每份报告会说明实际输入的证据范围。'),el('p','精确收入受账号权限限制时不会补造数值。'));
 }finally{refreshing=false}
}
async function refreshLater(){refreshing=false;await refresh()}
function promptPreview(){const d=directions.find(x=>x.id===$('direction').value);$('direction').disabled=false;$('prompt-controls').hidden=$('use-model').value!=='1';if(!route&&researchSources.length)previewScope();if(!d)return;$('direction-description').textContent=d.description;$('prompt-preview').textContent=d.full_prompt}
async function renderDetail(){
 showPage('detail-page',route[1]==='collections'?'采集数据详情':'完整研究报告');
 if(route[1]==='collections')await collectionDetail(route[2]);else await reportDetail(route[2]);
}
async function collectionDetail(id){
 const job=await api('/api/jobs/'+encodeURIComponent(id)),out=$('detail-content');
 out.replaceChildren(link('← 返回工作台','/'),el('h1','采集数据详情'),el('p',scope(job.payload.context)),el('p','状态：'+stateLabel(job.state)+' · 尝试 '+job.attempts+' 次'+(job.error_code?' · '+job.error_code:'')));
 if(!['SUCCEEDED','PARTIAL'].includes(job.state)){out.append(el('div',['PENDING','RUNNING'].includes(job.state)?'等待采集完成，页面每5秒自动更新。':'本任务没有可查看的数据。','report-status'));detailFinished=!['PENDING','RUNNING'].includes(job.state);return}
 const b=await api('/api/jobs/'+encodeURIComponent(id)+'/result');detailFinished=true;
 out.append(el('p','共 '+b.rows.length+' 条 · 采集时间 '+date(b.collected_at)),actions(button('下载完整 JSON',()=>download(b,'collection-'+id+'.json')),link('打开点点原始榜单',b.source_url,true)));
 if(b.status==='PARTIAL')out.append(el('p','这是部分采集结果，不参与完整榜单机会研究。'));
 const search=el('input');search.className='data-search';search.placeholder='搜索应用名称或开发者';search.setAttribute('aria-label','搜索采集应用');out.append(search);const count=el('p'),grid=el('div');out.append(count,grid);
 const metric=(r,n)=>{const m=r.metrics.find(x=>x.name===n);return m?.value??'未知'};
 const draw=()=>{const q=search.value.trim().toLowerCase(),rows=b.rows.filter(r=>(r.name+' '+(r.developer||'')).toLowerCase().includes(q));count.textContent='显示 '+rows.length+' / '+b.rows.length+' 条';if(!rows.length){empty(grid,'没有匹配的应用。');return}table(grid,['排名','应用','开发者','评分','评分数','详情'],rows.map(r=>[metric(r,'rank'),button(r.name,()=>appDetail(r,b)),r.developer||'未知',metric(r,'rating'),metric(r,'rating_count'),button('查看字段',()=>appDetail(r,b))]))};search.oninput=draw;draw();
}
function appDetail(row,b){
 const root=$('app-detail-content');root.replaceChildren(el('h2',row.name),el('p',scope(b.context)));
 const list=el('dl');const fields={'开发者':row.developer||'未知','采集时间':date(b.collected_at),'应用标识':row.listing_key,...(row.raw_columns||{})};
 for(const [k,v] of Object.entries(fields)){list.append(el('dt',k),el('dd',typeof v==='object'?JSON.stringify(v):String(v??'未知')))}
 root.append(list,link('查看点点应用详情',row.detail_url||b.source_url,true));const raw=el('details');raw.append(el('summary','查看标准化指标'),el('pre',JSON.stringify(row.metrics,null,2)));root.append(raw);$('app-detail').showModal();
}
function disclosure(title,text){const d=el('details');d.append(el('summary',title),el('pre',text));return d}
async function reportDetail(id){
 currentReport=await api('/api/analyses/'+encodeURIComponent(id));const record=currentReport,out=$('detail-content'),prompt=record.result?.prompt_snapshot||record.filters?.prompt_snapshot;
 document.title=(prompt?.title||'榜单趋势')+'报告 · 机会台';
 out.replaceChildren(link('← 返回机会研究','/#research'),el('div','RESEARCH REPORT','eyebrow'),el('h1',(record.use_model?(prompt?.title||'AI机会研究'):'榜单趋势')+'报告','report-title'),el('p',date(record.requested_at)+' · '+stateLabel(record.state)+' · '+(record.filters?.country||'全部地区')));
 if(record.state!=='SUCCEEDED'){
  out.append(el('div',['PENDING','RUNNING'].includes(record.state)?'研究正在处理，页面每5秒更新。可关闭页面后从研究列表再次打开。':('研究未完成：'+(record.error||stateLabel(record.state))),'report-status'));
  if(prompt)out.append(disclosure('本次提交的完整提示词',prompt.system_prompt));
  detailFinished=!['PENDING','RUNNING'].includes(record.state);return;
 }
 detailFinished=true;notes=await api('/api/feedback');const r=record.result;
 out.append(actions(button('导出完整报告 JSON',()=>download(record,'report-'+id+'.json')),button('打印 / 保存 PDF',()=>window.print())));
 if(r.source_overview){out.append(link('按这些来源重新选择研究','/?sources='+encodeURIComponent(r.source_overview.sources.map(s=>s.id).join(','))+'#research'),el('h2','本报告用了哪些数据'));const sources=el('div');renderScope(sources,r.source_overview);out.append(sources)}
 r.warnings.forEach(x=>out.append(el('p',x)));
 if(r.model){out.append(el('h2','待验证机会线索'),el('p','模型 '+r.model.model+' · 实际输入 '+(r.model_evidence_ids?.length??'未知')+' 条证据 · '+(r.model.cached?'复用缓存':'本次生成')));
  out.append(el('p','以下为模型提出的待验证假设，不代表收入、增长或资质已获证实。'));const diagnosis=r.model.result;if(diagnosis.summary)out.append(el('div',diagnosis.summary,'panel prose'));if(!diagnosis.candidates.length)out.append(el('div','本次模型没有提出候选，不等于市场没有机会。请先查看上方数据覆盖与缺口；单日数据可切换综合选品或MVP方向寻找待验证线索。','empty'));if(diagnosis.data_gaps)out.append(disclosure('AI说明：本次判断缺少什么',diagnosis.data_gaps.join('\n')));if(diagnosis.next_steps)out.append(disclosure('AI建议：下一步怎么验证',diagnosis.next_steps.join('\n')));
  r.model.result.candidates.forEach((c,i)=>{const card=el('article',undefined,'card');card.append(el('h3',(i+1)+'. '+c.task),el('div',c.hypothesis,'prose'),el('h4','尚待验证'),el('p',c.unknowns.join('\n'),'prose'));const refs=el('div',undefined,'evidence-list');c.evidence_ids.forEach(ref=>{const a=el('a','证据 '+ref);a.href='#evidence-'+encodeURIComponent(ref);refs.append(a,el('br'))});card.append(refs);out.append(card)})
 }else out.append(el('p','本报告是数据趋势分析，没有调用大模型。'));
 if(prompt)out.append(disclosure('本次实际使用的提示词 · '+prompt.version,prompt.system_prompt));
 out.append(el('h2','竞品与趋势依据'));
 if(!r.candidates.length)out.append(el('div','暂无已完成的可比采集数据。','empty'));
 r.candidates.forEach(c=>{const card=el('article',undefined,'card');card.append(el('div',scope(c.context),'meta'),el('h3',c.name),el('p','当前排名 '+(c.rank??'未知')+' · 已观察 '+c.observed_days+' 天'),el('p','7日名次改善：'+(c.windows['7'].rank_improvement??'历史不足')+'；28日：'+(c.windows['28'].rank_improvement??'历史不足')+'；90日：'+(c.windows['90'].rank_improvement??'历史不足')),el('p',c.unknowns.join('；')),actions(link('原始来源',c.source_url,true),button('审核 / 记录实验',()=>review(c))),el('p','审核状态：'+(notes[c.key]?.qualification||'UNREVIEWED')));out.append(card)});
 out.append(el('h2','证据附录'));
 (r.evidence||[]).forEach(e=>{const d=disclosure(e.id,e.text);d.id='evidence-'+e.id;const job=e.id.split(':')[0];d.append(link('查看本次采集数据','/collections/'+encodeURIComponent(job),true));out.append(d)});
}
function review(c){const n=notes[c.key]||{};$('review-key').value=c.key;$('decision').value=n.decision||'watch';$('qualification').value=n.qualification||'UNREVIEWED';$('note').value=n.note||'';$('experiment').value=n.experiment||'';$('evidence-refs').value=(n.evidence_refs||[]).join('\n');$('review').showModal()}
async function enter(){
 [catalog,directions]=await Promise.all([api('/api/catalog'),api('/api/research-directions')]);$('catalog').replaceChildren();Object.keys(catalog).forEach(k=>{const s=catalog[k],o=el('option',scope(s));o.value=k;$('catalog').append(o)});
 $('direction').replaceChildren();const placeholder=el('option','选择方向，启用 AI 分析');placeholder.value='';$('direction').append(placeholder);directions.forEach(d=>{const o=el('option',d.title);o.value=d.id;$('direction').append(o)});promptPreview();
 $('login').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;
 if(!route){await loadSources();const page=location.hash.slice(1),nav=[...document.querySelectorAll('nav button')].find(b=>b.dataset.page===page);if(nav)nav.click()}await refresh();
}
$('login-form').onsubmit=async e=>{e.preventDefault();try{await api('/auth/login','POST',{password:$('password').value});$('password').value='';notice('');detailFinished=false;await enter()}catch(e){notice(e.message)}};
$('logout').onclick=async()=>{try{await api('/auth/logout','POST');locked()}catch(e){notice(e.message)}};
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{if(route){location.href='/#'+b.dataset.page;return}showPage(b.dataset.page,b.textContent);document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('selected',x===b))});
$('day').value=new Date(Date.now()+8*3600000-86400000).toISOString().slice(0,10);
$('direction').onchange=()=>{$('use-model').value=$('direction').value?'1':'0';promptPreview();notice($('direction').value?'已启用 AI 分析；生成报告时将调用模型。':'已切换为无模型费用的趋势分析。')};$('use-model').onchange=()=>{if($('use-model').value==='1'&&!$('direction').value)$('direction').value='comprehensive';if($('use-model').value==='0')$('direction').value='';promptPreview()};
$('prompt-file').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;if(!/\.(txt|md)$/i.test(f.name)||f.size>24000)throw Error('请导入24KB以内的 UTF-8 txt/md 文件');const text=new TextDecoder('utf-8',{fatal:true}).decode(await f.arrayBuffer());if(text.length>6000)throw Error('补充提示词不能超过6000字');$('guidance').value=text;notice('已导入补充提示词，请检查后提交。')}catch(e){notice(e.message)}finally{$('prompt-file').value=''}};
$('collect-form').onsubmit=async e=>{e.preventDefault();const submit=e.submitter;submit.disabled=true;try{const name=$('catalog').value;if(submit.value==='plan')await api('/api/plans','POST',{name,catalog_id:name,enabled:true});else{const spec=catalog[name],context={};['market','country','store','device','category','chart'].forEach(k=>context[k]=spec[k]);context.data_date=$('day').value;await api('/api/jobs','POST',{request_key:crypto.randomUUID(),recipe:name,context})}notice('已保存，Mac 节点会领取任务。');await refresh()}catch(e){notice(e.message)}finally{submit.disabled=false}};
$('research-form').onsubmit=async e=>{e.preventDefault();const submit=e.submitter;submit.disabled=true;try{const r=await api('/api/analyses','POST',researchInput());location.href='/reports/'+r.id}catch(e){notice(e.message);submit.disabled=false}};
$('review-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/feedback/'+$('review-key').value,'PUT',{decision:$('decision').value,qualification:$('qualification').value,note:$('note').value,experiment:$('experiment').value,evidence_refs:$('evidence-refs').value.split('\n').map(x=>x.trim()).filter(Boolean)});$('review').close();detailFinished=false;await refresh();notice('审核记录已保存。')}catch(e){notice(e.message)}};
$('close-review').onclick=()=>$('review').close();$('close-app-detail').onclick=()=>$('app-detail').close();

function researchInput(){return {use_model:$('use-model').value==='1',country:$('country').value,store:'',direction:$('direction').value||'comprehensive',guidance:$('guidance').value,evidence_limit:Number($('evidence-limit').value),source_ids:[...document.querySelectorAll('.source-check:checked')].filter(x=>!x.disabled).map(x=>x.value)}}
async function loadSources(){researchSources=await api('/api/research-sources');drawSources();await previewScope()}
function drawSources(){
 const root=$('source-list');root.replaceChildren();if(!researchSources.length){empty(root,'还没有采集数据，请先到采集计划创建任务。');return}
 for(const s of researchSources){const matches=!$('country').value||$('country').value===s.context.country;const row=el('div',undefined,'source-row'),label=el('label'),box=el('input');box.type='checkbox';box.className='source-check';box.value=s.id;const requested=new URLSearchParams(location.search).get('sources');box.checked=s.eligible&&matches&&(!requested||requested.split(',').includes(s.id));box.disabled=!s.eligible||!matches;box.onchange=previewScope;label.append(box,el('span',scope(s.context)+' · '+s.row_count+' 条'));row.append(label,el('span',!matches?'地区筛选已排除':s.eligible?'可纳入':stateLabel(s.status)+' · '+s.reason,'muted'),link('查看数据','/collections/'+s.id,true));root.append(row)}
}
async function previewScope(){
 const seq=++previewSequence;const root=$('source-preview');root.replaceChildren(el('p','正在核对本次输入…'));
 try{const value=await api('/api/research-preview','POST',researchInput());if(seq!==previewSequence)return;renderScope(root,value,true);const warning=el('p');warning.textContent=$('direction').value==='momentum'&&!Object.values(value.comparable).some(Boolean)?'你选择了增长研究，但没有可比历史。仍可生成跟踪线索与补采计划，不能输出已验证增长排名。':'';root.prepend(warning)}catch(e){if(seq===previewSequence)empty(root,'无法预览：'+e.message)}
}
function renderScope(root,s,preview=false){
 root.replaceChildren();root.append(el('p',(s.reconstructed?'以下来源从旧报告保存的证据重建，条数代表已保存证据。':'本次数据范围已明确。')+' '+s.sources.length+' 个批次 · '+s.source_record_count+' 条记录 · '+s.dates.length+' 个榜单日期。'));
 if(s.dates.length)root.append(el('p','日期：'+s.dates.join('、')));
 const grid=el('div');table(grid,['数据来源 / 日期','记录数',preview?'AI将读取数':'AI读取数','核对'],s.sources.map(x=>[scope(x.context),x.row_count,s.model_inputs===null?'历史未记录':s.model_inputs.filter(e=>e.id.startsWith(x.id+':')).length,link('查看批次','/collections/'+x.id,true)]));root.append(grid);
 root.append(el('p','可计算名次变化的记录：7日 '+s.comparable['7']+'；28日 '+s.comparable['28']+'；90日 '+s.comparable['90']+'。'));
 const gaps=el('div',undefined,'data-gaps');gaps.append(el('h3','这些数据现在能支持什么'));gaps.append(el('p','可查看已有应用、榜单位置与评分，寻找需要验证的任务切口。'));s.gaps.forEach(x=>gaps.append(el('p',x)));root.append(gaps);
 const steps=el('details');steps.append(el('summary','建议下一步补充的数据'));s.next_steps.forEach(x=>steps.append(el('p',x)));root.append(steps);
 if(s.model_inputs===null){root.append(el('p','旧报告未保存完整的AI输入名单，无法准确还原，不能把全部报告证据算作AI已读。'));return}
 if(!s.model_inputs.length){root.append(el('p','本次不调用AI，或尚未选择可用数据。'));return}
 root.append(el('p',(preview?'AI 将读取 ':'AI 实际读取 ')+s.model_inputs.length+' 条，报告展示 '+s.displayed_count+' 项；两者不是同一个范围。'),el('p',s.sampling));const detail=el('details');detail.append(el('summary','展开 AI 读取的 '+s.model_inputs.length+' 个应用'));const apps=el('div');table(apps,['应用','来源','排名'],s.model_inputs.map(e=>[e.name,scope(e.context),e.rank??'未知']));detail.append(apps);root.append(detail);
}
$('reload-sources').onclick=()=>loadSources().catch(e=>notice(e.message));$('country').onchange=()=>{drawSources();previewScope()};$('evidence-limit').onchange=previewScope;

enter().catch(e=>{locked();if(e.message!=='UNAUTHORIZED')notice(e.message)});
setInterval(()=>{if(!$('workspace').hidden)refresh().catch(e=>notice(e.message))},5000);
