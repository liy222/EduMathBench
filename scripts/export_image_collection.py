"""导出图像题初版：题面、来源答案及必要图片一同交付。"""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/hard_collection/images_round1'
OUT=ROOT/'data/exports/image_draft_v0.1'
INTERNAL=ROOT/'data/public_image_draft'
for p in [OUT,OUT/'images',INTERNAL]:p.mkdir(parents=True,exist_ok=True)
rows=[]
for p in sorted(BASE.glob('*_candidates.jsonl')):
    rows.extend(json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip())
assert rows and len({q['id'] for q in rows})==len(rows)
seen=set()
packaged=[]
for q in rows:
    assert q['input_modality']=='text_image' and q['answer'] in 'ABCD'
    assert q['grade'] in [7,8,9] and q['difficulty'] in ['基础','中等','困难','pending']
    for k in ['question','option_a','option_b','option_c','option_d','source_id','source_ref','source_url','source_answer_location','source_raw_path']:
        assert isinstance(q[k],str) and q[k].strip(),(q['id'],k)
    assert (ROOT/q['source_raw_path']).is_file(),(q['id'],'source_raw_path')
    assert len({q['option_'+c] for c in 'abcd'})==4
    assert all(not any(ord(c)<32 for c in q[k]) for k in ['question','option_a','option_b','option_c','option_d'])
    key=tuple(''.join(q[k].split()) for k in ['question','option_a','option_b','option_c','option_d'])
    assert key not in seen;seen.add(key)
    assert q.get('image_assets'),q['id']
    assets=[]
    for a in q['image_assets']:
        path=ROOT/a['path'];data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
        assert sha==a['sha256'].lower(),(q['id'],'asset_hash')
        assert a['role'] in ['stem','option'],(q['id'],'image_role')
        if a['role']=='option':assert a.get('option') in 'ABCD'
        assert a.get('contains_answer_or_solution') is False,(q['id'],'answer_in_input_image')
        name=f'{sha[:12]}-{path.name}'
        target=OUT/'images'/name;target.write_bytes(data)
        assets.append({**a,'path':'images/'+name,'source_project_path':a['path'],'sha256':sha})
    q['source_type']='public';q['status']='auto_checked'
    q['verification_note']='题面与源答案对应、图片完整性和结构检查通过；难度暂定，未进行全量独立数学解答。'
    q['review_method']='public_source_text_image_correspondence_and_structure_check'
    exported={k:v for k,v in q.items() if not k.startswith('source_') and not k.startswith('option_')}
    exported['options']={c:q['option_'+c.lower()] for c in 'ABCD'}
    exported['source']={k.removeprefix('source_'):v for k,v in q.items() if k.startswith('source_')}
    exported['source']['reference']=exported['source'].pop('ref')
    exported['source_exam_grade']=q.get('source_exam_grade','')
    exported['source_type']='public'
    exported['image_assets']=assets
    packaged.append(exported)
internal_json=INTERNAL/'questions.jsonl'
internal_json.write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in rows),encoding='utf-8')
jp=OUT/'EduMathBench_image_draft_v0.1.jsonl'
jp.write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in packaged),encoding='utf-8')
cp=OUT/'EduMathBench_image_draft_v0.1.csv'
fields=list(dict.fromkeys(k for q in rows for k in q))
flat=[]
for original,exp in zip(rows,packaged):flat.append({**original,'image_assets':exp['image_assets']})
with cp.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in q.items()} for q in flat)
with cp.open(encoding='utf-8-sig',newline='') as f:again=list(csv.DictReader(f))
assert [json.loads(s) for s in jp.read_text(encoding='utf-8').splitlines()]==packaged
for raw,exp,c in zip(rows,packaged,again):
    for k in ['id','question','answer','option_a','option_b','option_c','option_d','source_url','source_ref']:assert c[k]==raw[k]
    assert json.loads(c['image_assets'])==exp['image_assets']
summary={'stage':'图像题公开初版，难度暂定','count':len(rows),'grade_counts':dict(Counter(q['grade'] for q in rows)),
         'module_counts':dict(Counter(q['module'] for q in rows)),
         'difficulty_counts':dict(Counter(q['difficulty'] for q in rows)),
         'image_assets':sum(len(q['image_assets']) for q in rows),'images_checked_without_answer':True,
         'roundtrip_verified':len(rows),'source_urls':len({q['source_url'] for q in rows}),
         'existing_text_draft_count':1500,'counted_in_existing_1500':False,
         'first_batch_only':True}
(BASE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'summary.json').write_bytes((BASE/'summary.json').read_bytes())
(OUT/'FORMAT.md').write_text('''# EduMathBench 图像题初版 v0.1

解压后，JSONL每行一题（UTF-8），CSV是UTF-8带BOM。question保留完整文字，options为A/B/C/D，answer为来源答案。input_modality=text_image表示题目带图；image_assets列出必要输入图片，role=stem或option，后者须指定option字母。path相对解压目录，source_project_path保留项目内原路径，sha256用于完整性校验；不以source.image_files中的原材料整页图片作为模型输入。

模型输入只使用question、四项options和image_assets指向的必要题图，不传answer、solution、source、难度依据或验证说明。标准答案和来源保留在数据中用于评分和追溯。difficulty_evidence.source_value为空表示没有逐题量化证据，不冒充学生正确率。JSONL的source.reference与纯文本通用格式一致，CSV对应source_ref；两种表格的image_assets/其他对象数组以JSON文本存储。

这是新增图像题初版，尚未计入原1500道纯文本主库；后续同年级/模块替换时登记稳定题号与替换记录。auto_checked代表结构、来源对应和图片完整性检查，不等于全量数学验算或实测难度。ZIP必须连同images文件夹使用。
''',encoding='utf-8')
files=[jp,cp,OUT/'FORMAT.md',OUT/'summary.json']+sorted((OUT/'images').glob('*'))
manifest={'count':len(rows),'files':[{'name':p.relative_to(OUT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
mp=OUT/'manifest.json';mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');files.append(mp)
zip_path=ROOT/'data/exports/EduMathBench_image_draft_v0.1.zip'
with ZipFile(zip_path,'w',ZIP_DEFLATED) as z:
    for p in files:z.write(p,p.relative_to(OUT).as_posix())
with ZipFile(zip_path) as z:assert z.testzip() is None
print(json.dumps(summary,ensure_ascii=True))
