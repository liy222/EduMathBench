"""Repair metadata in place while freezing selected IDs and generated variants."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/variants/parents'
spec=importlib.util.spec_from_file_location('selection',OUT/'select_parents.py')
selection=importlib.util.module_from_spec(spec);spec.loader.exec_module(selection)
read=lambda p:[json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s]
before=read(OUT/'parents_300.jsonl')
with (OUT/'figure_reference_triage.csv').open(encoding='utf-8-sig',newline='') as f:
    reader=csv.DictReader(f);fields=reader.fieldnames;old=list(reader)
mapping={q['id']:q for q in before}
rows=[]
for r in old:
    q=mapping[r['id']]
    if q.get('image_assets'):
        for a in q['image_assets']:
            file=ROOT/a['path']
            assert file.exists() and hashlib.sha256(file.read_bytes()).hexdigest()==a['sha256']
        r['figure_reference_status']='原图已关联且文件完整，待数学复核'
        r['figure_reference_rationale']='原题图通过image_assets单独关联，文件存在且SHA-256一致。先前仅检测题干占位符，漏读图片字段，误报未嵌图。'
        r['figure_reference_action']='使用已存原图核对条件；构造含图变式时同步更新图文，不需要因误报重新找图。'
    rows.append(r)
with (OUT/'figure_reference_triage.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
triage={r['id']:r for r in rows}
def repair(q):
    p=dict(q)
    p['has_image']=selection.is_image(q)
    p['diagram_reference_without_embedded_image']=selection.diagram_reference_without_picture(q)
    p['editable_suggestions'],p['image_variant_plan']=selection.suggestion(q,p['has_image'])
    if q['id'] in triage:
        for key in ('figure_reference_status','figure_reference_rationale','figure_reference_action'):p[key]=triage[q['id']][key]
    if 'pilot_substitution_note' in q:
        p['pilot_substitution_note']='首批改用完整纯文字公交相遇题。更正：原矩形母题s_04446已有image_assets配图，先前筛选漏读字段；不是来源缺图。试做题保持不变。'
    if p['has_image'] and '含图，需将图文同步更新。' not in p['selection_reason']:p['selection_reason']+=' 含图，需将图文同步更新。'
    return p
for file in [OUT/'parents_300.jsonl',*[OUT/f'pilot_parents_g{g}.jsonl' for g in (7,8,9)]]:
    qs=read(file);fixed=[repair(q) for q in qs]
    assert [q['id'] for q in qs]==[q['id'] for q in fixed]
    file.write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in fixed),encoding='utf-8')
with (OUT/'parents_300.csv').open(encoding='utf-8-sig',newline='') as f:csvfields=csv.DictReader(f).fieldnames
final=read(OUT/'parents_300.jsonl')
with (OUT/'parents_300.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=csvfields,extrasaction='ignore');w.writeheader()
    for q in final:
        row=dict(q);row['risk_flags']=';'.join(q.get('risk_flags',[]));w.writerow(row)
details=[]
for q in final:
    for a in q.get('image_assets',[]):
        file=ROOT/a['path'];valid=file.exists() and hashlib.sha256(file.read_bytes()).hexdigest()==a['sha256']
        assert valid
        details.append({'id':q['id'],'path':a['path'],'hash_matched':valid})
report={'cause':'selector inspected text placeholders only and ignored separately linked image_assets','candidate_count':300,'actual_image_parents':sum(q['has_image'] for q in final),'verified_image_references':len(details),'previously_flagged_missing_7_all_present':True,'missing_image_files':0,'remaining_text_only_figure_references':sum(q['diagram_reference_without_embedded_image'] for q in final),'public_bank_modified':False,'selected_parent_ids_changed':False,'generated_variants_changed':False,'images':details}
(ROOT/'data/reports/parent_image_metadata_correction.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='images'},ensure_ascii=False))
