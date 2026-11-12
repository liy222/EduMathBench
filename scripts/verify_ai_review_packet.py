"""Check compact AI inputs, return contracts, evidence images and canonical invariants."""
import copy,json
from pathlib import Path
import rebuild_web_benchmark as r
from build_ai_review import DEST,META,digest
from analyze_ai_reviews import validate,summarize

def main():
    manifest=json.loads((DEST/'manifest.json').read_text(encoding='utf-8'));rows=r.read(DEST/'questions.jsonl')
    source={q['id']:q for q in r.read(r.OUT/'questions.jsonl')};by_no={q['review_no']:q for q in rows}
    assert manifest['status']=='ready_for_ai_review' and manifest['questions_sha256']==r.sha(DEST/'questions.jsonl')
    assert manifest['source_questions_sha256']==r.sha(r.OUT/'questions.jsonl')
    assert len(rows)==len(by_no)==1800 and set(by_no)==set(range(1,1801)) and {q['question_id'] for q in rows}==set(source)
    assert sum(q['requires_image'] for q in rows)==619
    assert len(manifest['batches'])==55 and sum(b['count'] for b in manifest['batches'])==1800
    evidence=json.loads((DEST/'image_render_report.json').read_text(encoding='utf-8'));assert evidence['passed'] and len(evidence['images'])==619
    image_by={x['review_no']:x for x in evidence['images']}
    assert r.sha(DEST/'image_render_report.json')==manifest['image_render_report_sha256']
    for q in rows:
        old=source[q['question_id']]
        assert all(q[a]==old[b] for a,b in [('question','question'),('options','options'),('provided_answer','answer'),('grade','grade'),('module','module'),('difficulty_provisional','difficulty'),('kind','source_type')])
        assert not ({'verification_note','assistant_self_review','solution','data_url','generation_metadata'}&set(q))
        base={k:v for k,v in q.items() if k not in {'input_sha256','batch_id','image_file','image_sha256'}}
        imgs=[{'sha256':a['sha256'],'role':a['role'],'field':a.get('source_placeholder_field'),'placeholder':a.get('placeholder')} for a in old['image_assets']]
        assert q['input_sha256']==digest(base|{'original_input_images':imgs})
        assert q['requires_image']==bool(imgs)
        if q['requires_image']:
            path=(DEST/q['image_file']).resolve();assert path.is_relative_to(DEST.resolve()) and r.sha(path)==q['image_sha256']==image_by[q['review_no']]['sha256']
            assert image_by[q['review_no']]['question_id']==q['question_id'] and not image_by[q['review_no']]['contains_answer_or_solution']
        else:assert q['image_file'] is None and q['image_sha256'] is None
    seen=[]
    for batch in manifest['batches']:
        folder=DEST/batch['directory'];items=r.read(folder/'questions.jsonl');assert len(items)==batch['count'] and r.sha(folder/'questions.jsonl')==batch['questions_sha256']
        assert len(items)<=(50 if batch['kind']=='text' else 20)
        for q in items:
            expected=copy.deepcopy(by_no[q['review_no']])
            if expected['image_file']:expected['image_file']='images/'+Path(expected['image_file']).name
            assert q==expected and q['batch_id']==batch['batch_id']
            if q['requires_image']:assert r.sha(folder/q['image_file'])==q['image_sha256']
            seen.append(q['review_no'])
        for template in r.read(folder/'return_template.jsonl'):assert validate(template,by_no,manifest['dataset_id']) is None and template['verdict']=='pending'
    assert len(seen)==len(set(seen))==1800
    templates=r.read(DEST/'return_template.jsonl');assert len(templates)==1800
    assert all(x['verdict']=='pending' and validate(x,by_no,manifest['dataset_id']) is None for x in templates)
    stats,*_=summarize(by_no,templates);assert stats['decided_questions']==stats['covered_questions']==0 and stats['unresolved_questions']==1800
    assert r.sha(DEST/'analyze_ai_reviews.py')==r.sha(r.ROOT/'scripts/analyze_ai_reviews.py')
    report={'passed':True,'records':1800,'batch_count':55,'text_questions':1181,'image_questions':619,'input_hashes_verified':1800,'question_image_files_verified':619,'return_templates_pending':1800,'template_decided_questions':0,'source_master_unchanged':True,'author_derivations_excluded':True,'actual_ai_reviews_received':0,'mathematical_correctness_confirmed':False,'source_questions_sha256':manifest['source_questions_sha256']}
    r.dump(DEST/'verification_report.json',report)
    files=[{'path':p.relative_to(DEST).as_posix(),'bytes':p.stat().st_size,'sha256':r.sha(p)} for p in sorted(DEST.rglob('*')) if p.is_file() and p.name!='file_checksums.json']
    r.dump(DEST/'file_checksums.json',{'files':files,'zip_created':False})
    print(json.dumps(report|{'files':len(files)+1},ensure_ascii=False))

if __name__=='__main__':main()
