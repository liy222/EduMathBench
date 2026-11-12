"""Make a high-recall review queue; trigger words are selection hints, not difficulty labels."""
import json,re
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'data/hard_collection/cmmath_new'
raw=json.loads((BASE/'raw/cmmath_archive_full.json').read_text(encoding='utf-8'))
entries={Path(a['member']).name for a in [json.loads(s) for s in (BASE/'image_archive_index.jsonl').read_text(encoding='utf-8').splitlines()] if a['member'].startswith('CMMaTH/images/')}
words=['最小','最大','最值','结论','正确的有','正确的个数','参数','整数解','取值范围','存在','取整数','定义','折叠','翻折','旋转','动点','运动','多少种','规律','正整数','负整数']
pool=[];held=[]
for index,q in enumerate(raw):
 if q.get('grade_group')!=2 or q.get('grade_id') not in [7,8,9] or q.get('answer_type')!='choice' or str(q.get('answer','')).strip() not in list('ABCD'):continue
 if not any(w in q['question'] for w in words):continue
 matches=list(re.finditer(r'(?m)^\s*([A-F])\s*[.．、:：]\s*',q['question']))
 if [m.group(1) for m in matches]!=list('ABCD'):
  held.append({'problem_id':q['problem_id'],'reason':'option parser uncertain'});continue
 if not q.get('image') or any(ref not in entries for ref in q['image']):
  held.append({'problem_id':q['problem_id'],'reason':'original image member missing from public package','images':q.get('image')});continue
 stem=q['question'][:matches[0].start()].strip()
 opts={m.group(1):q['question'][m.end():matches[i+1].start() if i<3 else len(q['question'])].strip() for i,m in enumerate(matches)}
 if not all(opts.values()):continue
 pool.append({**q,'source_index':index,'source_question':q['question'],'question':stem,'options':opts,'answer':q['answer'].strip(),
              'source_grade':q['grade_id'],'difficulty':'pending','candidate_id':'CMMA-'+q['problem_id']})
(BASE/'priority_candidates.jsonl').write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in pool),encoding='utf-8')
refs=sorted({ref for q in pool for ref in q['image']})
(BASE/'priority_image_refs.json').write_text(json.dumps(refs),encoding='utf-8')
(BASE/'priority_holds.jsonl').write_text(''.join(json.dumps(q)+'\n' for q in held),encoding='utf-8')
print(json.dumps({'raw_records':len(raw),'priority_candidates':len(pool),'source_grade_counts':dict(Counter(q['source_grade'] for q in pool)), 'image_refs':len(refs),'preparse_holds':len(held)}))
