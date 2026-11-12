"""Replace a misclassified, unused parent with a same-cell public record."""
import csv,hashlib,importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PARENTS=ROOT/'data/variants/parents'
spec=importlib.util.spec_from_file_location('selection',PARENTS/'select_parents.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
old_id,new_id=sys.argv[1:3]
def read(p):return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s]
current=read(PARENTS/'parents_300.jsonl');used=read(ROOT/'data/variants/collection/questions.jsonl')
assert old_id not in {q['parent_id'] for q in used},'cannot replace a used parent'
old=next(q for q in current if q['id']==old_id)
new=next(q for q in read(ROOT/'data/normalized/questions.jsonl') if q['id']==new_id)
assert tuple(new[k] for k in ['grade','module','difficulty'])==tuple(old[k] for k in ['grade','module','difficulty'])
assert new_id not in {q['id'] for q in current}
new=module.add_meta(new,0)
assert new['family_id'] not in {q['family_id'] for q in current}
history=PARENTS/'history';history.mkdir(exist_ok=True)
backup=history/'parents_300_before_b003_substitutions.jsonl'
if not backup.exists():backup.write_bytes((PARENTS/'parents_300.jsonl').read_bytes())
before_hash=hashlib.sha256((PARENTS/'parents_300.jsonl').read_bytes()).hexdigest()
for path in [PARENTS/'parents_300.jsonl',ROOT/f'data/variants/batches/b003/parents_g{old["grade"]}.jsonl']:
    qs=read(path);assert sum(q['id']==old_id for q in qs)==1
    qs=[new if q['id']==old_id else q for q in qs]
    path.write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in qs),encoding='utf-8')
with (PARENTS/'parents_300.csv').open(encoding='utf-8-sig',newline='') as f:fields=csv.DictReader(f).fieldnames
with (PARENTS/'parents_300.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
    for q in read(PARENTS/'parents_300.jsonl'):
        row=dict(q);row['risk_flags']=';'.join(q.get('risk_flags',[]));w.writerow(row)
ledger=PARENTS/'b003_substitutions.json'
entries=json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else []
entries.append({'old_id':old_id,'new_id':new_id,'reason':'原母题文本为文具单价线性组合，误归九年级几何/圆；替换为真实圆周角与两弧分类题。','grade':old['grade'],'module':old['module'],'difficulty':old['difficulty'],'previous_parent_list_sha256':before_hash,'new_parent_list_sha256':hashlib.sha256((PARENTS/'parents_300.jsonl').read_bytes()).hexdigest(),'prior_90_unchanged':True,'public_bank_unchanged':True})
ledger.write_text(json.dumps(entries,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Replaced unused parent {old_id} with {new_id}; same cell, prior90 unchanged')
