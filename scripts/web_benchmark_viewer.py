"""Offline local HTML; safe text rendering, explicit source and answer evidence."""
import base64,copy,json,mimetypes,re
from pathlib import Path
from rebuild_web_benchmark import ROOT,OUT

def render(rows,*,output_path=None,asset_root=None,template=None):
    asset_root=Path(asset_root) if asset_root is not None else OUT
    resources=ROOT/'data/reports/visualization_assets';css=(resources/'katex.min.css').read_text(encoding='utf-8')
    def embed(m):return 'src:url(data:font/woff2;base64,'+base64.b64encode((resources/'fonts'/m[1]).read_bytes()).decode()+') format("woff2")}'
    css=re.sub(r'src:url\(fonts/([^)]*\.woff2)\) format\("woff2"\)[^}]*}',embed,css)
    data=copy.deepcopy(rows)
    for q in data:
        for group in ['image_assets','answer_image_assets']:
            for a in q.get(group,[]):
                p=asset_root/(a.get('path') or a['local_path'])
                mime=mimetypes.guess_type(p.name)[0] or 'image/png'
                a['data_url']='data:'+mime+';base64,'+base64.b64encode(p.read_bytes()).decode()
    page=(template or TEMPLATE).replace('__CSS__',css).replace('__KATEX__',(resources/'katex.min.js').read_text(encoding='utf-8'))
    page=page.replace('__AUTORENDER__',(resources/'auto-render.min.js').read_text(encoding='utf-8')).replace('__CONTENT__',(ROOT/'data/visualization/question_content.js').read_text(encoding='utf-8'))
    page=page.replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('<','\\u003c'))
    (Path(output_path) if output_path is not None else OUT/'完整题库浏览.html').write_text(page,encoding='utf-8')

TEMPLATE=r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EduMathBench · 网页题源重建版</title><style>__CSS__</style><style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#17243a;font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif}header,main{max-width:1120px;margin:auto;padding:22px}h1{font-size:25px;margin:0}.muted{color:#58677b;font-size:14px}.tools{display:flex;flex-wrap:wrap;gap:10px;margin:15px 0}select,input,button{font:inherit;padding:7px 10px;border:1px solid #becbd9;border-radius:6px;background:white;color:inherit}button{cursor:pointer}input{min-width:230px}.card{padding:24px;background:white;border:1px solid #d5dfe9;border-radius:10px;min-width:0}.content{white-space:pre-wrap;overflow-wrap:anywhere}.inline-image{max-width:100%;height:auto;vertical-align:middle;margin:4px}.options{padding:0;list-style:none}.options li{padding:7px 0}details{margin-top:18px}summary{cursor:pointer;color:#205aa3}a{color:#205aa3;overflow-wrap:anywhere}.katex-display,.table-responsive{overflow:auto}table{border-collapse:collapse}td{border:1px solid #cbd5e1;padding:7px}#questionId{font-size:13px;color:#58677b;overflow-wrap:anywhere}.badge{display:inline-block;border-radius:5px;padding:2px 8px;background:#eaf0f7;margin-right:6px}.review-pending{color:#8a4e0c}@media(max-width:650px){header,main{padding:12px}.card{padding:15px}}
</style><header><h1>EduMathBench · 网页题源重建版</h1><p class="muted">1500道原题（363沿用＋1137新爬）与300道第二轮重生成变式。变式暂定难度：基础120、中等120、困难60；每年级100道。300道变式已由助手逐题自查，待用户独立复核。原题处理运行流程不调用大模型。草稿未冻结。</p>
<div class="tools"><select id="split" aria-label="集合"><option value="">全部集合</option><option value="dev">开发集</option><option value="test">测试集</option><option value="debug">调试100题</option></select>
<select id="kind" aria-label="题类"><option value="">全部题类</option><option value="public">原题</option><option value="variant">变式</option></select>
<select id="grade" aria-label="年级"><option value="">全部年级</option><option value="7">七年级</option><option value="8">八年级</option><option value="9">九年级</option></select>
<select id="module" aria-label="模块"><option value="">全部模块</option><option>数与式</option><option>方程与不等式</option><option>函数</option><option>几何</option><option>统计与概率</option></select>
<select id="difficulty" aria-label="难度"><option value="">全部难度</option><option>基础</option><option>中等</option><option>困难</option></select>
<select id="origin" aria-label="获取方式"><option value="">全部获取方式</option><option value="new_web_crawl">本次程序爬取</option><option value="retained_legacy_web">历史沿用</option><option value="assistant_generated_variant">助手生成变式</option></select>
<select id="solutionStatus" aria-label="解析文本"><option value="">解析状态</option><option value="missing">无解析文本／未采集</option><option value="has">有解析文本</option></select>
<input id="search" placeholder="搜索题号、题干、来源"><button id="reset">重置</button></div>
<div class="tools"><button id="prev">上一题</button><span id="counter"></span><button id="next">下一题</button><button id="family">查看当前题族</button></div><div id="summary" class="muted"></div></header>
<main><article id="card" class="card"></article></main><script>__KATEX__</script><script>__AUTORENDER__</script><script>__CONTENT__</script><script>
(()=>{'use strict';const rows=__DATA__,byId=id=>document.getElementById(id);let filtered=rows,index=0,selectedFamily='';
const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value??'';return e};
function image(a){const e=document.createElement('img');e.src=a.data_url;e.alt=a.alt||'原题配图';e.className='inline-image';e.dataset.assetHash=a.sha256;return e;}
function block(parent,value,q,field){const e=document.createElement('div');e.className='content';embAppendText(e,String(value??''));
 const assets=q?.image_assets.filter(a=>(a.source_placeholder_field||'question')===field)||[];const used=new Set();
 const walker=document.createTreeWalker(e,NodeFilter.SHOW_TEXT),nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
 for(const node of nodes){const pieces=node.textContent.split(/(\[图片:[a-f0-9]+\]|<ImageHere>)/g);if(pieces.length===1)continue;const fragment=document.createDocumentFragment();
  for(const piece of pieces){const a=assets.find(a=>a.placeholder===piece||piece==='<ImageHere>');if(a){used.add(a);fragment.append(image(a));}else fragment.append(document.createTextNode(piece));}node.replaceWith(fragment);}
 parent.append(e);for(const a of assets)if(!used.has(a))e.append(image(a));return e;}
function detail(card,label){const e=document.createElement('details');e.append(text('summary',label));card.append(e);return e;}
function draw(){const card=byId('card');card.replaceChildren();byId('counter').textContent=filtered.length?`${index+1} / ${filtered.length}`:'0 / 0';byId('prev').disabled=index===0;byId('next').disabled=index>=filtered.length-1;
 if(!filtered.length){card.append(text('p','没有符合条件的题目。'));return;}
 const q=filtered[index];card.dataset.questionId=q.id;const id=text('div',q.id);id.id='questionId';card.append(id);
 card.append(text('p',`${q.grade}年级 · ${q.module} · ${q.difficulty} · ${q.source_type==='variant'?'变式':'原题'} · ${q.split==='dev'?'开发集':'测试集'}`));
 block(card,q.question,q,'question');const options=document.createElement('ol');options.className='options';
 for(const letter of 'ABCD'){const li=document.createElement('li');block(li,letter+'. '+q.options[letter],q,'option_'+letter.toLowerCase());options.append(li);}card.append(options);
 const answer=detail(card,'查看来源答案／候选答案');block(answer,'答案：'+q.answer);block(answer,'解析未采集。');
 if(q.answer_ocr){block(answer,'答案提取：本地普通OCR，待人工抽查。');for(const a of q.answer_image_assets||[])answer.append(image(a));}
 const source=detail(card,'来源、母题与获取过程');block(source,'题族：'+q.family_id);if(q.parent_id)block(source,'母题：'+q.parent_id);
 block(source,'来源：'+(q.source.title||''));const link=text('a','打开来源网页');link.href=q.source.url;link.target='_blank';link.rel='noopener';source.append(link);
 block(source,'来源位置：'+(q.source.reference||''));block(source,'原材料：'+(q.source.raw_path||''));block(source,'获取方式：'+q.acquisition_origin);
 for(const a of q.additional_sources||[]){block(source,'附加来源：'+(a.title||''));}
 const review=detail(card,'难度依据、变式修改与待复核信息');block(review,q.difficulty_annotation?.reason||'来源暂定标签，未实测校准');
 if(q.change_description)block(review,'修改说明：'+q.change_description);if(q.verification_note)block(review,'生成者验算依据：'+q.verification_note.scope);
 if(q.assistant_self_review){const self=detail(card,'本轮助手逐题自查（待用户复核）');block(self,'自查推导：'+q.assistant_self_review.reasoning);block(self,'自查答案：'+q.assistant_self_review.rederived_answer);block(self,q.assistant_self_review.changed_in_self_check?'本题在自查中修正或完善了表述，具体见自查报告。':'本轮未修改题面与候选答案。');block(self,'由生成者自己重新检查；不等于独立复核或用户批准。');}
 block(review,'状态：'+q.status+'；未完成正式数学复核。');block(review,'风险标记：'+(q.risk_flags||[]).join('；'));
 renderMathInElement(card,{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}],throwOnError:false,strict:'ignore'});
}
function filter(){const query=byId('search').value.trim().toLowerCase();filtered=rows.filter(q=>(!byId('split').value||(byId('split').value==='debug'?q.debug_subset:q.split===byId('split').value))&&(!byId('kind').value||q.source_type===byId('kind').value)&&(!byId('grade').value||String(q.grade)===byId('grade').value)&&(!byId('module').value||q.module===byId('module').value)&&(!byId('difficulty').value||q.difficulty===byId('difficulty').value)&&(!byId('origin').value||q.acquisition_origin===byId('origin').value)&&(!selectedFamily||q.family_id===selectedFamily)&&(!byId('solutionStatus').value||(byId('solutionStatus').value==='has'?!!q.solution:!q.solution))&&(!query||[q.id,q.question,q.source.title,q.parent_id].join(' ').toLowerCase().includes(query)));index=0;draw();}
const controls=['split','kind','grade','module','difficulty','origin','solutionStatus','search'];for(const id of controls)byId(id).addEventListener(id==='search'?'input':'change',filter);
byId('prev').onclick=()=>{if(index>0){index--;draw();}};byId('next').onclick=()=>{if(index<filtered.length-1){index++;draw();}};
byId('reset').onclick=()=>{for(const id of controls)byId(id).value='';selectedFamily='';filter();};byId('family').onclick=()=>{if(filtered.length){selectedFamily=filtered[index].family_id;for(const id of controls)byId(id).value='';filter();}};
byId('summary').textContent=`共${rows.length}题；原题难度为网站或历史暂定标签，变式难度为助手暂定标签。`;
window.__EMB_AUDIT__={count:rows.length,visit(i){filtered=rows;index=i;draw();return rows[i].id;}};
function openHash(){const id=new URLSearchParams(location.hash.slice(1)).get('qid');if(id){const i=rows.findIndex(q=>q.id===id);if(i>=0){filtered=rows;index=i;draw();return;}}draw();}
window.addEventListener('hashchange',openHash);openHash();})();
</script></html>'''
