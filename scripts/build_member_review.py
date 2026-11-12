"""Portable 1..1800 member review export; keep canonical IDs and provenance intact."""
import base64,copy,csv,hashlib,json,mimetypes,re
from collections import Counter
from pathlib import Path
import rebuild_web_benchmark as r
import web_benchmark_viewer as viewer

DEST=r.ROOT/'成员复核/题库复核_1800题_20261023'
MODULES=['数与式','方程与不等式','函数','几何','统计与概率']
PAGE='题库复核.html'

def write_csv(name,fields,records):
    with (DEST/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(records)

def replace_once(text,old,new):
    assert text.count(old)==1,old[:100]
    return text.replace(old,new,1)

def template():
    t=viewer.TEMPLATE
    t=replace_once(t,'<title>EduMathBench · 网页题源重建版</title>','<title>EduMathBench · 成员复核 · 1—1800题</title>')
    t=re.sub(r'<h1>EduMathBench · 网页题源重建版</h1><p class="muted">.*?</p>',
       '<h1>EduMathBench · 成员复核题库</h1><p class="muted">共1800题，复核编号1—1800。七年级1—600，八年级601—1200，九年级1201—1800；变式紧跟母题。先独立作答，再展开答案核对，将结果填写到同目录“复核填写表.csv”。公式和图片已内嵌，可离线打开。</p>',t,count=1)
    t=replace_once(t,'<div class="tools"><button id="prev">',
       '<div class="tools"><label>跳到第 <input id="reviewJump" type="number" min="1" max="1800" style="min-width:90px;width:110px" value="1"> 题</label><button id="jumpReview">跳转</button><label>分工范围 <input id="rangeStart" type="number" min="1" max="1800" style="min-width:90px;width:110px" value="1"> 至 <input id="rangeEnd" type="number" min="1" max="1800" style="min-width:90px;width:110px" value="1800"></label><button id="applyRange">查看范围</button><span id="rangeMessage" role="status"></span></div><div class="tools"><button id="prev">')
    t=replace_once(t,"let filtered=rows,index=0,selectedFamily='';","let filtered=rows,index=0,selectedFamily='',rangeStart=1,rangeEnd=1800;")
    t=replace_once(t,"const id=text('div',q.id);id.id='questionId';card.append(id);",
       "const id=text('h2','第 '+q.review_number+' 题');id.id='questionId';id.style.fontSize='24px';id.style.color='#17243a';card.append(id);")
    t=replace_once(t,"block(source,'题族：'+q.family_id);if(q.parent_id)block(source,'母题：'+q.parent_id);",
       "block(source,'原始题号：'+q.id);block(source,'题族：'+q.family_id);if(q.parent_id){block(source,'母题：第 '+q.parent_review_number+' 题（原始题号 '+q.parent_id+'）');const go=text('button','跳到母题');go.onclick=()=>jumpTo(q.parent_review_number);source.append(go);}")
    t=replace_once(t,"block(source,'获取方式：'+q.acquisition_origin);",
       "block(source,'获取方式：'+({'new_web_crawl':'本次程序爬取','retained_legacy_web':'历史沿用','assistant_generated_variant':'助手生成变式'}[q.acquisition_origin]||q.acquisition_origin));")
    t=replace_once(t,'filtered=rows.filter(q=>','filtered=rows.filter(q=>q.review_number>=rangeStart&&q.review_number<=rangeEnd&&')
    t=replace_once(t,"selectedFamily='';filter();};byId('family')", "selectedFamily='';rangeStart=1;rangeEnd=1800;byId('rangeStart').value=1;byId('rangeEnd').value=1800;byId('rangeMessage').textContent='';filter();};byId('family')")
    t=replace_once(t,"selectedFamily=filtered[index].family_id;for(const id of controls)","selectedFamily=filtered[index].family_id;rangeStart=1;rangeEnd=1800;byId('rangeStart').value=1;byId('rangeEnd').value=1800;byId('rangeMessage').textContent='当前题族';for(const id of controls)")
    t=replace_once(t,"byId('summary').textContent=`共${rows.length}题；原题难度为网站或历史暂定标签，变式难度为助手暂定标签。`;",
       "byId('summary').textContent=`共${rows.length}题。复核编号固定，不随筛选变化；答案折叠显示。全部为待成员复核草稿。`;function jumpTo(number){if(!Number.isInteger(number)||number<1||number>1800){byId('rangeMessage').textContent='请输入1—1800之间的整数。';return;}for(const id of controls)byId(id).value='';rangeStart=1;rangeEnd=1800;selectedFamily='';byId('rangeStart').value=1;byId('rangeEnd').value=1800;byId('rangeMessage').textContent='';filtered=rows;index=number-1;byId('reviewJump').value=number;draw();}byId('jumpReview').onclick=()=>jumpTo(Number(byId('reviewJump').value));byId('reviewJump').onkeydown=e=>{if(e.key==='Enter')jumpTo(Number(e.target.value));};byId('applyRange').onclick=()=>{const a=Number(byId('rangeStart').value),b=Number(byId('rangeEnd').value);if(!Number.isInteger(a)||!Number.isInteger(b)||a<1||b>1800||a>b){byId('rangeMessage').textContent='范围须满足1≤起始题号≤结束题号≤1800。';return;}rangeStart=a;rangeEnd=b;selectedFamily='';for(const id of controls)byId(id).value='';byId('rangeMessage').textContent='当前分工：第 '+a+'—'+b+' 题';filter();};")
    t=replace_once(t,"const id=new URLSearchParams(location.hash.slice(1)).get('qid');if(id)",
       "const params=new URLSearchParams(location.hash.slice(1)),n=params.get('no');if(n){jumpTo(Number(n));return;}const id=params.get('qid');if(id)")
    return t

def build():
    DEST.mkdir(parents=True,exist_ok=True)
    validation=json.loads((r.OUT/'reports/final_validation.json').read_text(encoding='utf-8'))
    source_sha=r.sha(r.OUT/'questions.jsonl');assert validation['passed'] and validation['data_sha256']==source_sha
    source=r.read(r.OUT/'questions.jsonl');assert len(source)==1800
    variants={q['parent_id']:q for q in source if q['source_type']=='variant'};assert len(variants)==300
    ordered=[]
    for grade in (7,8,9):
        public=sorted((q for q in source if q['grade']==grade and q['source_type']=='public'),key=lambda q:(MODULES.index(q['module']),{'基础':0,'中等':1,'困难':2}[q['difficulty']],q['id']))
        for q in public:
            ordered.append(copy.deepcopy(q))
            if q['id'] in variants:ordered.append(copy.deepcopy(variants[q['id']]))
    assert len(ordered)==1800 and Counter(q['grade'] for q in ordered)==Counter({7:600,8:600,9:600})
    numbers={q['id']:i for i,q in enumerate(ordered,1)}
    for q in ordered:
        q['review_number']=numbers[q['id']];q['parent_review_number']=numbers.get(q['parent_id'])
        if q['source_type']=='variant':assert q['parent_review_number']==q['review_number']-1
    viewer.render(ordered,output_path=DEST/PAGE,asset_root=r.OUT,template=template())
    source_labels={'new_web_crawl':'本次程序爬取','retained_legacy_web':'历史沿用','assistant_generated_variant':'助手生成变式'}
    common=lambda q:{'复核编号':q['review_number'],'年级':q['grade'],'模块':q['module'],'题类':'变式' if q['source_type']=='variant' else '原题','暂定难度':q['difficulty'],'母题复核编号':q['parent_review_number'] or '', '原始题号':q['id']}
    base_fields=list(common(ordered[0]))
    blank_fields=['复核成员','复核日期','复核结论','独立作答','建议答案','题干或选项问题','答案问题','年级模块难度问题','修改建议','备注']
    write_csv('复核填写表.csv',base_fields+blank_fields,[common(q)|{k:('待复核' if k=='复核结论' else '') for k in blank_fields} for q in ordered])
    source_fields=['候选答案','获取方式','来源标题','来源链接','来源位置','母题原始题号','助手自查状态','已知待核查问题']
    suspects=json.loads((r.OUT/'review/known_source_suspects.json').read_text(encoding='utf-8'))['issues'];suspects={x['id']:x['reason'] for x in suspects}
    write_csv('答案与来源对照.csv',base_fields+source_fields,[common(q)|{'候选答案':q['answer'],'获取方式':source_labels[q['acquisition_origin']],'来源标题':q['source']['title'],'来源链接':q['source']['url'],'来源位置':q['source'].get('reference',''),'母题原始题号':q['parent_id'],'助手自查状态':'已自查，待成员复核' if q.get('assistant_self_review') else '待成员复核','已知待核查问题':suspects.get(q['id'],'')} for q in ordered])
    write_csv('题号对应表.csv',base_fields+['母题原始题号','题族','原分集'],[common(q)|{'母题原始题号':q['parent_id'],'题族':q['family_id'],'原分集':q['split']} for q in ordered])
    # Portable JSONL includes image bytes as data URLs; original paths remain trace metadata.
    cache={};image_count=0
    for q in ordered:
        for group in ['image_assets','answer_image_assets']:
            for a in q.get(group,[]):
                p=r.OUT/(a.get('path') or a['local_path']);digest=r.sha(p);assert digest==a['sha256']
                if digest not in cache:cache[digest]='data:'+(mimetypes.guess_type(p.name)[0] or 'image/png')+';base64,'+base64.b64encode(p.read_bytes()).decode()
                a['data_url']=cache[digest];image_count+=1
    r.jsonl(DEST/'题目集合.jsonl',ordered)
    readme='''EduMathBench 成员复核题库（2026-10-23）

需要发送哪些文件
只需发送“题库复核.html”和“复核填写表.csv”，成员就能看题、填写并返回结果。
“答案与来源对照.csv”方便核对答案与来源；“题号对应表.csv”和“题目集合.jsonl”供汇总与程序读取，可按需要一起发送。
本目录不含压缩包。

如何复核
1. 用Edge或Chrome双击打开“题库复核.html”。公式与必要图片都已内嵌，无需安装程序或启动服务；来源网页链接需要联网。
2. 按分配的题号范围查看题目，先独立作答，再展开候选答案、自查推导与来源核对。
3. 用Excel或WPS打开“复核填写表.csv”，筛选自己的范围，填写姓名、日期、独立作答和结论。结论填写“通过”“需修改”或“无法判断”；未核对的保持“待复核”。
4. 保存后以“成员姓名_复核结果.csv”返回。请勿修改复核编号和原始题号；若软件提供编码选项，保存为CSV UTF-8。

题号与分工
七年级：1—600；八年级：601—1200；九年级：1201—1800。每年级500原题、100变式。
同年级依次按数与式、方程与不等式、函数、几何、统计与概率排列，空模块跳过；变式紧跟对应母题。
编号1—1800是本轮固定复核编号，筛选不会重新编号。页面支持跳转到指定题号和查看起止范围。
原始题号、母题关联、题族、来源、答案与原有开发/测试划分均保留。本次没有改写来源或采集方式，没有把待复核题自动设为通过。

复核重点
检查题干条件与图形是否完整、公式是否正常、四选项是否清楚且只有一个正确项、来源/候选答案是否正确，以及年级、模块和暂定难度是否合理。
300道变式已做助手自查，但仍需成员独立复核。原题的已知疑点在答案与来源对照表中列出，不代表其他题已经数学确认。
题干解析没有采集；变式的生成者推导和助手自查属于内部核对记录。

数据说明
题目集合.jsonl保留原始id，增加review_number（1—1800）和parent_review_number。图片data_url已内嵌；原path仅供追溯原项目目录，读取本复核集合时可直接使用data_url。
浏览页不会把复核结果自动同步回项目，请填写并返回CSV。所有填写表初始状态都是待复核，姓名与结论没有预填通过。
'''
    (DEST/'发给成员说明.txt').write_text(readme,encoding='utf-8-sig')
    report={'built_at':r.site.stamp(),'source_questions_sha256':source_sha,'records':1800,'review_numbers':{'first':1,'last':1800},'grades':{'7':[1,600],'8':[601,1200],'9':[1201,1800]},'public':1500,'variants':300,'image_occurrences':image_count,'distinct_embedded_images':len(cache),'canonical_ids_preserved':True,'parent_variant_adjacency':True,'provenance_changed':False,'source_master_changed':r.sha(r.OUT/'questions.jsonl')!=source_sha,'human_review_completed':False,'zip_created':False}
    assert not report['source_master_changed']
    r.dump(DEST/'构建记录.json',report)
    print(json.dumps({'directory':str(DEST),'records':1800,'distinct_images':len(cache),'html_megabytes':round((DEST/PAGE).stat().st_size/1024**2,2),'canonical_master_unchanged':True},ensure_ascii=False))

if __name__=='__main__':build()
