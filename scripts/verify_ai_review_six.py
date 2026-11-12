"""Independent, read-only checks of the six-part full-question review export."""
import json
from collections import Counter
from pathlib import Path
import rebuild_web_benchmark as r
import analyze_ai_full_reviews as a
from build_ai_review_six import DEST,OLD

def verify():
    m=json.loads((DEST/'manifest.json').read_text(encoding='utf-8'));checks=json.loads((DEST/'file_checksums.json').read_text(encoding='utf-8'))
    for path,sha in checks.items():assert r.sha(DEST/path)==sha,path
    assert r.sha(r.OUT/'questions.jsonl')==m['source_questions_sha256']
    assert r.sha(OLD/'questions.jsonl')==m['previous_packet_questions_sha256']
    assert r.sha(DEST/'questions.jsonl')==m['questions_sha256']
    master=r.read(DEST/'questions.jsonl');by={q['review_no']:q for q in master};source={q['id']:q for q in r.read(r.OUT/'questions.jsonl')}
    assert len(master)==1800 and set(by)==set(range(1,1801))
    templates=r.read(DEST/'return_template.jsonl');assert len(templates)==1800
    for t in templates:assert a.validate(t,by,m['dataset_id']) is None and t['verdict']=='pending'
    visited=[];images=0;pair_count=0
    for part in m['parts']:
        folder=DEST/part['directory'];rows=r.read(folder/'questions.jsonl');blank=r.read(folder/'return_template.jsonl')
        assert r.sha(folder/'questions.jsonl')==part['questions_sha256'] and r.sha(folder/'return_template.jsonl')==part['template_sha256']
        assert len(rows)==len(blank)==300
        assert Counter(q['grade'] for q in rows)=={7:100,8:100,9:100}
        assert Counter(q['kind'] for q in rows)=={'public':250,'variant':50}
        assert sum(q['requires_image'] for q in rows)==part['image_count']
        for kind,counts in [('public',{'基础':100,'中等':100,'困难':50}),('variant',{'基础':20,'中等':20,'困难':10})]:assert Counter(q['difficulty_provisional'] for q in rows if q['kind']==kind)==counts
        for q,t in zip(rows,blank):
            assert t['review_no']==q['review_no'] and a.validate(t,by,m['dataset_id']) is None
            central=by[q['review_no']];assert {k:v for k,v in q.items() if k!='image_file'}=={k:v for k,v in central.items() if k!='image_file'}
            original=source[q['question_id']]
            assert q['question']==original['question'] and q['options']==original['options'] and q['provided_answer']==original['answer']
            assert q['source_url']==original['source']['url']
            if q['parent_review_no'] is not None:
                assert by[q['parent_review_no']]['question_id']==original['parent_id'] and by[q['parent_review_no']]['batch_id']==q['batch_id'];pair_count+=1
            if q['requires_image']:
                assert r.sha(folder/q['image_file'])==q['image_sha256'] and r.sha(DEST/central['image_file'])==q['image_sha256'];images+=1
            else:assert q['image_file'] is None
            visited.append(q['review_no'])
    assert sorted(visited)==list(range(1,1801)) and images==619 and pair_count==300
    assert not list(DEST.rglob('*.zip'))
    report={'passed':True,'file_checksums_verified':len(checks),'questions':1800,'parts':6,'images':619,'mother_variant_pairs_colocated':300,'pending_templates':1800,'canonical_and_previous_packet_unchanged':True}
    print(json.dumps(report,ensure_ascii=False));return report

if __name__=='__main__':verify()
