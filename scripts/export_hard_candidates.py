"""汇总已经采集的网上困难候选及来源证据，保持主库原样。"""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/hard_collection'
OUT=BASE/'exports'
OUT.mkdir(exist_ok=True)
rows=[]
for p in sorted(BASE.glob('g*/candidates.jsonl')):
    rows.extend(json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip())
assert len({q['id'] for q in rows})==len(rows)
seen={}
for q in rows:
    for k in ['question','option_a','option_b','option_c','option_d','answer','source_id','source_url','source_ref','source_answer_location','source_raw_path']:
        assert q.get(k), (q['id'],k)
    assert q['answer'] in 'ABCD' and len(q['answer'])==1
    assert all(not any(ord(c)<32 and c not in '\n\r\t' for c in q[k]) for k in ['question','option_a','option_b','option_c','option_d'])
    assert (ROOT/q['source_raw_path']).is_file()
    for path in q.get('source_image_files',[]):assert (ROOT/path).is_file()
    key=tuple(''.join(q[k].split()) for k in ['question','option_a','option_b','option_c','option_d'])
    assert key not in seen, (q['id'],seen.get(key))
    seen[key]=q['id']
    q['source_type']='public'
    q['batch_phase']='source_checked_candidate_not_in_main_draft'
    q.setdefault('difficulty_evidence',{
        'kind':'competition_context' if q['grade']==7 else 'capstone_topic',
        'source_label':'' if q['grade']==7 else '选择压轴题',
        'source_value':None,'url':q['source_url'],'reference':q.get('source_difficulty_evidence',''),
        'empirical':False})
    q.setdefault('difficulty_annotation',{
        'difficulty':q['difficulty'],'reason':q['hardness_rationale'],
        'model':'gpt-6-luna','annotated_at':q['source_accessed_at'],
        'review_method':q.get('review_method','public_preview_correspondence'),
        'confidence':q.get('confidence','medium'),'rule_version':'source-hard-v0.1'})

# 与当前主库精确比较，不改变源题、答案或既有难度。
draft=ROOT/'data/public_draft/questions.jsonl'
main=[json.loads(s) for s in draft.read_text(encoding='utf-8').splitlines()]
main_keys={tuple(''.join(q[k].split()) for k in ['question','option_a','option_b','option_c','option_d']) for q in main}
assert not any(key in main_keys for key in seen)
json_path=OUT/'hard_candidates_round1.jsonl'
json_path.write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in rows),encoding='utf-8')
fields=list(dict.fromkeys(k for q in rows for k in q))
csv_path=OUT/'hard_candidates_round1.csv'
with csv_path.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in q.items()} for q in rows)
assert [json.loads(s) for s in json_path.read_text(encoding='utf-8').splitlines()]==rows
with csv_path.open(encoding='utf-8-sig',newline='') as f:
    flat=list(csv.DictReader(f))
for q,c in zip(rows,flat):
    for key in ['id','question','option_a','option_b','option_c','option_d','answer','source_url','source_ref']:
        assert c[key]==q[key]
    assert json.loads(c['difficulty_evidence'])==q['difficulty_evidence']
    assert json.loads(c['difficulty_annotation'])==q['difficulty_annotation']
summary={'candidates':len(rows),'grade_counts':dict(Counter(q['grade'] for q in rows)),
         'source_urls':len({q['source_url'] for q in rows}),
         'difficulty_evidence_kinds':dict(Counter(q['difficulty_evidence']['kind'] for q in rows)),
         'unique_ids':True,'four_options_and_source_answer':True,
         'exact_duplicates_in_main':0,'format_roundtrip_verified':len(rows),
         'main_draft_count':len(main),'main_draft_sha256':hashlib.sha256(draft.read_bytes()).hexdigest(),
         'main_draft_modified':False,'remaining_main_hard_gap':300-sum(q['difficulty']=='困难' for q in main)}
(BASE/'round1_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
fmt=OUT/'FORMAT.md'
fmt.write_text('''# 网上困难候选首批

JSONL为UTF-8，每行一题；CSV为带BOM的UTF-8。四个选项固定对应A/B/C/D，answer是来源答案。source_前缀字段保存来源、题号、答案位置、取得时间与原件路径；difficulty_evidence与difficulty_annotation分别记录来源证据和本项目暂定判断，CSV中对象/数组保存为JSON文本。

这些是已核对公开题面与答案位置的候选，不在1500题主库内。source_value为空表示没有可映射的逐题数值；empirical=false表示没有本项目学生测试数据。压轴专题与竞赛出处不等于逐题实测难度。未取得的原卷及完整解析不补猜。原件留在D:/EduMathBench项目内，轻量包不包含全部题页材料。主库的困难237道缺口尚未补齐。
''',encoding='utf-8')
policy=OUT/'source_difficulty_collection.md';policy.write_bytes((ROOT/'docs/source_difficulty_collection.md').read_bytes())
summary_path=OUT/'round1_summary.json'
summary_path.write_bytes((BASE/'round1_summary.json').read_bytes())
files=[json_path,csv_path,fmt,policy,summary_path]
for name in ['collection_report.md','source_probe_results.json']:
    source=BASE/name
    if source.is_file():
        target=OUT/name;target.write_bytes(source.read_bytes());files.append(target)
manifest={'count':len(rows),'files':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in files]}
mp=OUT/'manifest.json';mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');files.append(mp)
with ZipFile(OUT/'hard_candidates_round1.zip','w',ZIP_DEFLATED) as z:
    for p in files:z.write(p,p.name)
with ZipFile(OUT/'hard_candidates_round1.zip') as z:assert z.testzip() is None
print(json.dumps(summary,ensure_ascii=True))
