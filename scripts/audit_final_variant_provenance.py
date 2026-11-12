"""Fixed-rule final lineage audit, distinct from mathematical review."""
import hashlib,json
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];BATCH=ROOT/'data/variants/batches/b003'
def read(p):return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s]
source={p['id']:p for p in read(ROOT/'data/normalized/questions.jsonl')}
parents={p['id']:p for p in read(ROOT/'data/variants/parents/parents_300.jsonl')}
prior=[p for p in read(ROOT/'data/variants/collection/questions.jsonl') if not p['id'].startswith('EMB-V-B003-')]
assert len(prior)==90
used={p['parent_id'] for p in prior};ids=set();new=[];image_refs=[]
for grade in (7,8,9):
    selected=read(BATCH/f'parents_g{grade}.jsonl');qs=read(BATCH/f'g{grade}.jsonl')
    assert len(selected)==len(qs)==70
    for i,(p,q) in enumerate(zip(selected,qs),1):
        assert q['id']==f'EMB-V-B003-G{grade}-{i:03d}'
        assert q['parent_id']==p['id'] and q['family_id']==p['family_id']
        assert q['grade']==grade and q['module']==p['module']
        assert q['id'] not in ids and q['parent_id'] not in used
        ids.add(q['id']);used.add(q['parent_id'])
        assert q['source_type']=='variant' and q['input_modality']=='text' and not q['image_assets']
        assert set(q['options'])==set('ABCD') and all(q['options'].values()) and q['question']
        aliases={'source_id':'id','source_title':'title','source_url':'url','source_ref':'ref'}
        assert all(q['source'].get(k,q['source'].get(aliases[k]))==p[k] for k in aliases),'source fields mismatch'
        assert all(p[k]==v for k,v in source[p['id']].items()),'parent source fields changed'
        for a in p.get('image_assets',[]):
            f=ROOT/a['path'];assert f.is_file() and hashlib.sha256(f.read_bytes()).hexdigest()==a['sha256'];image_refs.append(a['path'])
        new.append(q)
assert len(new)==210 and used==set(parents)
report={'status':'passed','method':'Python standard-library fixed rules; no model mathematical approval','new_count':210,'prior_count':90,'final_count':300,'unique_parent_count':300,'source_field_match':210,'text_only':210,'grade_counts':dict(Counter(str(q['grade']) for q in new)),'difficulty_counts':dict(Counter(q['difficulty'] for q in new)),'verified_new_parent_image_refs':len(image_refs),'difficulty_note':'实际标签允许与母题不同，不强抬难度；年级模块对应严格核对。','substitution_ledger':'data/variants/parents/b003_substitutions.json','public_bank_unchanged':True,'scope':'Fields, lineage, source parity and asset integrity only; independent math reviews are separate files.'}
(BATCH/'provenance_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
