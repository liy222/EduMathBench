"""Pending human-review tasks; never fabricate completed review results."""
import base64,copy,csv,html,json,mimetypes,re
from collections import defaultdict
from lxml import html as lh
import rebuild_web_benchmark as r

SOURCE_SUSPECTS={
 'EMB-P-WEB2-TIKU-2003992':'题干条件使用z，所求出现未定义的c，源题变量疑似混用。原样保留并要求源站比对；不得视为已确认有效数学题。',
 'EMB-P-WEB2-TIKU-1855917':'单选题中“异号”与“异号且正数绝对值较大”两项可能同时成立，待核实源站单选标注与选项。',
 'EMB-P-WEB2-TIKU-1754084':'按平行线知识点归档到七年级，但题干包含sin三角函数；知识点映射不能保证综合题完全符合目标年级课程。',
 'EMB-P-WEB2-TIKU-3883591':'生成变式时发现：按题干数字−2、0、1、2枚举16个有序结果，三角形内含边界命中7个，得7/16；来源答案C图片为1/2。原题保留来源答案，疑似源题或答案冲突，优先对照原材料复核。'
}

def select_balanced(pool,n,forced=()):
    result=[];used=set()
    def take(q):
        if q and q['id'] not in used and len(result)<n:result.append(q);used.add(q['id'])
    for id in forced:take(next((q for q in pool if q['id']==id),None))
    buckets=defaultdict(list)
    for q in sorted(pool,key=lambda q:r.rank(q['id'])):buckets[(q['grade'],q['module'])].append(q)
    for bucket in buckets.values():take(next((q for q in bucket if q['difficulty']=='困难'),bucket[0]))
    for grade in (7,8,9):
        for difficulty in ['基础','中等','困难']:take(next((q for q in pool if q['grade']==grade and q['difficulty']==difficulty and q['id'] not in used),None))
    for q in sorted(pool,key=lambda q:r.rank(q['id'])):take(q)
    assert len(result)==n
    return result

def sanitized_raw(q,assetmap):
    location=q.get('raw_path')
    if location:path=r.OUT/location
    else:path=r.ROOT/q['source']['raw_path']
    if not path.is_file():return '<p>请使用来源链接及项目原材料索引核查。</p>'
    data=path.read_text(encoding='utf-8',errors='replace')
    if path.suffix not in ('.html','.htm'):return '<pre style="white-space:pre-wrap">'+html.escape(data)+'</pre>'
    try:
        tree=lh.fromstring(data)
        # Show the actual question region, rather than page chrome or account UI.
        selector={'tiku':'q-detail','21cnjy':'QuestionView','chujuan':'QuestionView','jyeoo':'QUES_LI'}.get(q.get('source_platform'))
        regions=r.site.nodes(tree,selector) if selector else []
        if regions:tree=copy.deepcopy(regions[0])
        for node in list(tree.xpath('.//form')):node.drop_tag()
        for node in list(tree.xpath('.//script|.//iframe|.//object|.//embed|.//input|.//link|.//style')):
            if node.getparent() is not None:node.drop_tree()
        for node in tree.iter():
            if not isinstance(node.tag,str):continue
            for key in list(node.attrib):
                if key.lower().startswith('on') or key in ('href','srcset','action'):node.attrib.pop(key,None)
            if 'url(' in node.get('style','').lower():node.attrib.pop('style',None)
        for im in tree.xpath('//img'):
            url=im.get('src') or im.get('data-src') or ''
            asset=assetmap.get(url)
            if asset and (r.OUT/asset['local_path']).is_file():
                file=r.OUT/asset['local_path'];mime=mimetypes.guess_type(str(file))[0] or 'image/png';im.set('src','data:'+mime+';base64,'+base64.b64encode(file.read_bytes()).decode())
            else:im.attrib.pop('src',None);im.set('alt','未内嵌图片，按来源网页或原材料路径核查')
        return '<meta charset="utf-8"><style>body{font:16px/1.8 sans-serif;padding:12px;overflow-wrap:anywhere}img{max-width:100%}table{max-width:100%;border-collapse:collapse}td{border:1px solid #ccc;padding:4px}</style>'+lh.tostring(tree,encoding='unicode')
    except Exception as error:raise ValueError('来源区域预览构建失败：'+q['id']+'；'+str(error)) from error

def build():
    rows=r.read(r.OUT/'questions.jsonl');public=[q for q in rows if q['source_type']=='public'];variants=[q for q in rows if q['source_type']=='variant'];by={q['id']:q for q in rows}
    con=r.db();candidates=[json.loads(x[0]) for x in con.execute('select record from items')];con.close()
    assetmap={a['url']:a for q in candidates for a in q['image_assets'] if a.get('download_status')=='saved'}
    final_sample=select_balanced(public,50,forced=list(SOURCE_SUSPECTS)+[q['id'] for q in public if q.get('source_platform')=='jyeoo'][:5]+[q['id'] for q in public if q['acquisition_origin']=='retained_legacy_web'][:5])
    # Ten per grade, covering every grade/module cell and both supported/manual specs.
    variant_sample=[]
    priority={7:['EMB-V-WEB2R2-G7-066'],8:['EMB-V-WEB2R2-G8-107'],9:['EMB-V-WEB2R2-G9-264']}
    for grade in (7,8,9):variant_sample+=select_balanced([q for q in variants if q['grade']==grade],10,forced=priority[grade])
    ocr=select_balanced([q for q in candidates if q.get('answer_ocr',{}).get('accepted')],20)
    groups=[('原题来源核对50题',final_sample,'final_public_source_check'),('变式验算30题',variant_sample,'variant_math_review'),('OCR试采附加核对20题',ocr,'trial_ocr_not_final')]
    tasks=[];raws={}
    for label,items,scope in groups:
        for q in items:
            tasks.append({'id':q['id'],'group':label,'scope':scope,'grade':q['grade'],'module':q['module'],'difficulty':q['difficulty'],'source_url':q['source']['url'],'parent_id':q.get('parent_id',''),'answer':q['answer'],'reviewer':'','reviewed_at':'','result':'pending','notes':SOURCE_SUSPECTS.get(q['id'],'')})
            rawq=by.get(q.get('parent_id',''),q)
            raws[q['id']]=sanitized_raw(rawq,assetmap)
    folder=r.OUT/'review';folder.mkdir(exist_ok=True)
    r.jsonl(folder/'tasks.jsonl',tasks)
    with (folder/'人工复核结果表.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(tasks[0]));w.writeheader();w.writerows(tasks)
    r.dump(folder/'known_source_suspects.json',{'status':'unresolved_source_semantic_suspects','issues':[{'id':id,'reason':reason} for id,reason in SOURCE_SUSPECTS.items()]})
    data={'tasks':tasks,'raws':raws,'ocr':{q['id']:q for q in ocr}}
    for q in data['ocr'].values():
        for a in q['image_assets']:
            if a.get('download_status')=='saved':
                p=r.OUT/a['local_path'];a['data_url']='data:'+(mimetypes.guess_type(str(p))[0] or 'image/png')+';base64,'+base64.b64encode(p.read_bytes()).decode()
    page=REVIEW_HTML.replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('<','\\u003c'))
    (r.OUT/'人工复核对照.html').write_text(page,encoding='utf-8')
    r.dump(r.OUT/'reports/review_sampling.json',{'final_public':50,'variants':30,'trial_ocr_extra':20,'final_selected_ocr_count':0,'human_completed':0,'reason_for_separate_ocr_pool':'最终1137道均为来源文字答案，不捏造20道最终OCR样本。20道来自真实试采OCR成果，单列核对。','known_source_suspects':len(SOURCE_SUSPECTS)})
    return tasks

REVIEW_HTML=r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EduMathBench 人工复核对照</title><style>body{font:16px/1.7 system-ui,sans-serif;margin:20px;background:#f3f5f8;color:#18283e}select,button{font:inherit;padding:8px;margin:4px}iframe{width:100%;height:720px;background:white;border:1px solid #ccd5e1}main{display:grid;grid-template-columns:1fr 1fr;gap:16px}.panel{min-width:0}#meta{white-space:pre-wrap}.warning{color:#8a4e0c}img{max-width:100%}@media(max-width:900px){main{grid-template-columns:1fr}}</style><h1>人工复核对照</h1><p>原题50题＋变式30题；另有OCR试采20题单列核对。当前均未复核。请填写同目录“review/人工复核结果表.csv”，结果可填通过、需修复或无法判断。</p><select id="group"></select><select id="item"></select><button id="previous">上一题</button><button id="next">下一题</button><div id="meta"></div><main><section class="panel"><h2>统一题目／变式</h2><iframe id="normalized" title="统一题目"></iframe><div id="ocr"></div></section><section class="panel"><h2>保存的来源页面／变式母题原材料</h2><iframe id="raw" sandbox title="保存的来源材料"></iframe></section></main><script>const DATA=__DATA__,g=document.querySelector('#group'),s=document.querySelector('#item');for(const name of [...new Set(DATA.tasks.map(t=>t.group))])g.add(new Option(name,name));function options(){s.replaceChildren();for(const t of DATA.tasks.filter(t=>t.group===g.value))s.add(new Option(t.id,t.id));draw();}function draw(){const t=DATA.tasks.find(t=>t.id===s.value);document.querySelector('#meta').textContent=`${t.grade}年级 · ${t.module} · ${t.difficulty} · 候选答案${t.answer}\n${t.notes||''}\n来源：${t.source_url}\n结果：待复核；OCR试采题不在最终1800题中。`;document.querySelector('#raw').srcdoc=DATA.raws[t.id];const v=document.querySelector('#normalized'),o=document.querySelector('#ocr');o.replaceChildren();if(t.scope==='trial_ocr_not_final'){v.hidden=true;const q=DATA.ocr[t.id];const p=document.createElement('p');p.textContent=q.question+'\n'+Object.entries(q.options).map(([k,v])=>k+'. '+v).join('\n');o.append(p);for(const a of q.image_assets){if(a.data_url){const im=new Image();im.src=a.data_url;im.alt=a.role==='answer'?'来源答案原图':'来源题图';o.append(im);}}const evidence=document.createElement('pre');evidence.textContent=JSON.stringify(q.answer_ocr,null,2);o.append(evidence);}else{v.hidden=false;v.src='完整题库浏览.html#qid='+encodeURIComponent(t.id);}}g.onchange=options;s.onchange=draw;document.querySelector('#previous').onclick=()=>{if(s.selectedIndex>0){s.selectedIndex--;draw();}};document.querySelector('#next').onclick=()=>{if(s.selectedIndex<s.length-1){s.selectedIndex++;draw();}};options();</script></html>'''

if __name__=='__main__':build()
