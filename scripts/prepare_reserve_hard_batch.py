"""Apply explicit hard reviews to stored reserve records while preserving their source fields."""
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from check_collection import write_jsonl
from prepare_completion import read
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/hard_collection/completion'
pool={q['id']:q for p in [ROOT/'data/bulk_prepared/reserve.jsonl',ROOT/'data/mathbench_prepared/reserve.jsonl',ROOT/'data/candidates/quota_reserve.jsonl'] for q in read(p)}
labels={a.get('id',a.get('candidate_id')):a for p in [BASE/'g8_reserve_labels.jsonl',BASE/'reserve_hard_labels.jsonl'] for a in read(p)}
existing={q['id'] for p in (ROOT/'data/batches').glob('*/questions.jsonl') if p.parent.name!='hard_reserve_001' for q in read(p)}
new=[];annotations=[]
now=datetime.now(timezone(timedelta(hours=8))).isoformat()
for qid,a in labels.items():
 if a.get('difficulty')!='困难' or a.get('decision')!='eligible' or qid not in pool:continue
 q=dict(pool[qid]);a={**a,'id':qid,'annotated_at':now,'model':'gpt-6-luna','rule_version':'difficulty-v0.2','review_method':'full_question_options_source_analysis_read','empirical':False}
 if qid in existing:
  a['decision']='document_existing_label' if q.get('difficulty')=='困难' else ('review_existing_label' if q.get('difficulty') not in {'pending',None} else 'assign_pending_label')
  a['previous_difficulty']=q.get('difficulty');annotations.append(a)
 else:
  q.update({k:a[k] for k in ['grade','module','knowledge_point','difficulty']})
  q['difficulty_annotation']=a;q['status']='collected';q['batch_id']='hard_reserve_001';new.append(q)
write_jsonl(ROOT/'data/batches/hard_reserve_001/questions.jsonl',new)
write_jsonl(ROOT/'data/batches/hard_reserve_001/sources.jsonl',[])
write_jsonl(ROOT/'data/annotations/difficulty_hard_reserve.jsonl',annotations)
print(json.dumps({'new_candidates':len(new),'existing_annotations':len(annotations)}))
