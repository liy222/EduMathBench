"""Render the reviewed release through the existing local viewer."""
import copy,json
from pathlib import Path
import web_benchmark_viewer as viewer
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/benchmark_web_v0.3'
def render():
    rows=[json.loads(s) for s in (OUT/'questions.jsonl').read_text(encoding='utf-8').splitlines()]
    rows=copy.deepcopy(rows)
    for q in rows:
        q.pop('assistant_self_review',None);q['answer_image_assets']=[]
        q['status']=q['release_review']['status']
    template=viewer.TEMPLATE
    start=template.index('<p class="muted">');end=template.index('</p>',start)+4
    additions=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))['source_build']['added_from_existing_crawler_cache']
    intro=f'<p class="muted">成员复核后修订版 v0.3：1500道原题（363沿用＋1137网页采集）与300道变式。原题难度600／600／300，变式实际难度120／121／59，各年级600题。按用户确认接收六份成员复核版本，不新增人工复核任务。{additions}题从既有爬虫缓存补入，3道变式由助手针对知识范围与分集问题修订，均单独记录。原图与文字分开保存；解析未采集。</p>'
    template=template[:start]+intro+template[end:]
    template=template.replace('EduMathBench · 网页题源重建版','EduMathBench · 成员复核修订版 v0.3')
    template=template.replace("const id=text('div',q.id)","const id=text('div',`展示编号 ${q.display_no} · 原复核编号 ${q.review_no} · ${q.id}`)")
    template=template.replace("block(review,'状态：'+q.status+'；未完成正式数学复核。');","block(review,'当前处理状态：'+q.status);block(review,'成员复核按用户确认接收；程序补入、助手修订记录单独保存。');")
    template=template.replace('难度依据、变式修改与待复核信息','难度依据、变式修改与处理记录')
    template=template.replace("[q.id,q.question,q.source.title,q.parent_id]","[q.id,String(q.review_no),q.question,q.source.title,q.parent_id]")
    viewer.render(rows,output_path=OUT/'完整题库浏览.html',asset_root=OUT,template=template)
    print(json.dumps({'rendered':1800,'path':str(OUT/'完整题库浏览.html'),'external_dependencies':False},ensure_ascii=False))
if __name__=='__main__':render()
