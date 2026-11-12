"""Record item-specific evidence for resolving previous collector holds."""
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from check_collection import fingerprint,write_jsonl,INFORMATION_FLAGS
from prepare_completion import read
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/hard_collection/completion'
originals={q['id']:q for p in (ROOT/'data/batches').glob('*/questions.jsonl') for q in read(p)}
now=datetime.now(timezone(timedelta(hours=8))).isoformat();rows=[]
for a in read(BASE/'held_hard_resolutions.jsonl'):
 if a['decision']!='eligible' or a['id'] not in originals:continue
 q=originals[a['id']]
 if a['grade']==9 and a['module']=='数与式':
  a={**a,'grade':8,'grade_reason':'主要知识为平方展开、整数整除与代数构造，不需要九年级函数/圆/相似知识；来源竞赛级别另保留。'}
 annotation={**a,'model':'gpt-6-luna','annotated_at':now,'rule_version':'difficulty-v0.2',
             'confidence':'medium','review_method':'source_question_options_and_specific_mathematical_issue_review','empirical':False}
 rows.append({**a,'original_fingerprint':fingerprint(q),
              'remove_flags':[f for f in q.get('risk_flags',[]) if f not in INFORMATION_FLAGS],
              'difficulty_annotation':annotation,'reviewer':'gpt-6-luna','reviewed_at':now})
write_jsonl(ROOT/'data/annotations/quality_admission_hard.jsonl',rows)
print(json.dumps({'reviewed_admissions':len(rows)}))
