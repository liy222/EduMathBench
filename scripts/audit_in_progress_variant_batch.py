"""Audit partial B003 records without merging or declaring independent review."""
import json,sys,re
from pathlib import Path
from verify_pilot_variants import check_spec
ROOT=Path(__file__).resolve().parents[1]
batch=ROOT/'data/variants/batches/b003'
existing={q['parent_id'] for q in map(json.loads,(ROOT/'data/variants/collection/questions.jsonl').read_text(encoding='utf-8').splitlines()) if not q['id'].startswith('EMB-V-B003-')}
results=[];counts={};seen=set();parents_seen=set()
for grade in (7,8,9):
    p=batch/f'g{grade}.jsonl'
    if not p.exists():counts[str(grade)]=0;continue
    try:qs=[json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s]
    except json.JSONDecodeError:counts[str(grade)]='write_in_progress';continue
    counts[str(grade)]=len(qs)
    parents=[json.loads(s) for s in (batch/f'parents_g{grade}.jsonl').read_text(encoding='utf-8').splitlines()]
    for q in qs:
        errors=[]
        try:
            n=int(q['id'].rsplit('-',1)[-1]);assert 1<=n<=70
            expected=parents[n-1]
            assert q['id'] not in seen;seen.add(q['id'])
            assert q['parent_id']==expected['id'] and q['family_id']==expected['family_id'],'parent/family mapping'
            assert q['parent_id'] not in existing and q['parent_id'] not in parents_seen,'parent reused';parents_seen.add(q['parent_id'])
            assert int(q['grade'])==grade and q['module']==expected['module'],'grade/module mapping'
            assert q['source_type']=='variant' and q['input_modality']=='text' and not q.get('image_assets'),'type/modality'
            assert set(q['options'])==set('ABCD') and all(q['options'].values()),'options'
            assert q['question']!=expected['question'] and q['solution'] and q['change_description'],'unchanged/missing derivation'
            assert not re.search(r'如图|下图|图中|<ImageHere>|<img\b',q['question']),'unspecified image reference'
            assert not any(ord(c)<32 and c not in '\n\r\t' for t in [q['question'],*q['options'].values(),q['solution']] for c in t),'control character'
            matches,_=check_spec(q['verification_spec'])
            assert matches==[q['answer']],f'calculated {matches}, answer {q["answer"]}'
        except (AssertionError,KeyError,ValueError,TypeError,ZeroDivisionError) as e:errors.append(str(e))
        results.append({'id':q['id'],'errors':errors})
report={'partial_record_counts':counts,'checked':len(results),'arithmetic_and_structure_passed':sum(not r['errors'] for r in results),'failures':[r for r in results if r['errors']],'scope':'Partial generation audit only; no independent review or collection merge.'}
(batch/'in_progress_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
