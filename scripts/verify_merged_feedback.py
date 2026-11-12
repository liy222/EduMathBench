"""Independently verify merged coverage, provenance, image hashes and unresolved states."""
import json
from collections import Counter
from pathlib import Path
import analyze_ai_full_reviews as a
from merge_review_feedback import OUT,DRAFT,PACKET,CANON,sha

def verify():
    m=json.loads((OUT/'汇总统计.json').read_text(encoding='utf-8'));dm=json.loads((DRAFT/'manifest.json').read_text(encoding='utf-8'))
    assert sha(CANON)==m['source_questions_sha256'] and sha(DRAFT/'questions.jsonl')==dm['questions_sha256']
    current=a.base.read_jsonl(DRAFT/'questions.jsonl');original={q['review_no']:q for q in a.base.read_jsonl(PACKET/'questions.jsonl')};canonical={q['id']:q for q in a.base.read_jsonl(CANON)}
    assert len(current)==1800 and [q['review_no'] for q in current]==list(range(1,1801))
    assert len({q['question_id'] for q in current})==1800
    assert Counter(q['kind'] for q in current)=={'public':1500,'variant':300}
    images=0;changed=0;nulls=0;answer_changes=0
    for q in current:
        base=original[q['review_no']];old=canonical[q['question_id']]
        assert q['question_id']==base['question_id'] and q['original_canonical_id']==old['id']
        for k in ['kind','batch_id','source_url','parent_review_no','requires_image']:assert q[k]==base[k]
        assert q['original_split']==old['split']
        assert q['original_provided_answer']==base['provided_answer'] and q['original_review_input_sha256']==base['input_sha256']
        assert q['dataset_id']==m['dataset_id'] and q['human_approved'] is False
        assert q['answer']==q['provided_answer'] and q['answer'] in ['A','B','C','D',None]
        assert set(q['options'])==set('ABCD') and all(isinstance(x,str) and x.strip() for x in q['options'].values())
        payload={k:q[k] for k in ['dataset_id','review_no','question_id','question','options','provided_answer','grade','module','difficulty_provisional','requires_image','image_sha256']};assert q['input_sha256']==a.digest(payload)
        if q['requires_image']:
            path=(DRAFT/q['image_file']).resolve();assert path.is_relative_to(DRAFT.resolve()) and sha(path)==q['image_sha256'];images+=1
        else:assert q['image_file'] is None
        if q['answer'] is None:nulls+=1
        if q['answer'] is not None and q['answer']!=base['provided_answer']:answer_changes+=1
        if a.original(q)!=a.original(base):changed+=1
        if q['batch_id']=='P03':assert q['feedback']['selected_content_from']=='original_input' and 'review_protocol_inconsistent' in q['feedback']['flags']
        if q['review_no'] in {1492,1556}:assert q['answer']==base['provided_answer'] and 'feedback_error_identified_by_targeted_check' in q['feedback']['flags']
    assert images==619 and changed==m['content_changed_records'] and nulls==15 and answer_changes==22
    excluded=a.base.read_jsonl(DRAFT/'已隔离题目_3题.jsonl');active=a.base.read_jsonl(DRAFT/'未隔离题目_1797题.jsonl')
    assert {q['review_no'] for q in excluded}=={253,1174,1708} and all(q['answer'] is None for q in excluded)
    assert len(active)==1797 and not {q['review_no'] for q in active}&{253,1174,1708}
    assert len(a.base.read_jsonl(OUT/'原始复核记录.jsonl'))==1800
    images_log=json.loads((OUT/'图片核对记录.json').read_text(encoding='utf-8'));assert sum(x['changed'] for x in images_log)==sum(x['visually_checked_in_this_import'] for x in images_log)==9
    assert not list(OUT.rglob('*.zip')) and not list(OUT.rglob('*.rar'))
    result={'passed':True,'full_records':1800,'active_not_necessarily_resolved':1797,'quarantined':3,'originals':1500,'variants':300,'images_verified':619,'replacement_images_visually_checked':9,'content_changed_including_null_answers':changed,'candidate_answer_changes':answer_changes,'unresolved_or_quarantined_null_answers':nulls,'canonical_unchanged':True,'ids_sources_parents_original_splits_preserved':True,'human_approval_not_inferred':True}
    a.base.dump(OUT/'合并验收记录.json',result)
    print(json.dumps(result,ensure_ascii=False));return result

if __name__=='__main__':verify()
