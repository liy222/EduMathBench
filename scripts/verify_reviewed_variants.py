"""Execute current authored specifications; preserve submitted member review status."""
import json
from pathlib import Path
from verify_web_variant_math import check_spec
from build_reviewed_release import OUT,sha,digest,dump,read
def verify():
    before=sha(OUT/'questions.jsonl');results=[]
    for q in read(OUT/'questions.jsonl'):
        if q['source_type']!='variant':continue
        spec=q.get('verification_spec',{});row={'id':q['id'],'review_no':q['review_no'],'kind':spec.get('kind'),'current_answer':q['answer'],'question_options_answer_sha256':digest({k:q[k] for k in ['question','options','answer']}),'verification_spec_sha256':digest(spec),'release_review_status':q['release_review']['status']}
        if spec.get('kind')=='manual_review_required':row.update(status='member_review_preserved_spec_not_programmable',reason=spec.get('reason',''))
        else:
            try:
                answers,detail=check_spec(spec);row.update(status='pass' if answers==[q['answer']] else 'answer_conflict',matches=answers,detail=detail)
            except Exception as e:row.update(status='error',error=str(e))
        results.append(row)
    supported=[x for x in results if x['status']!='member_review_preserved_spec_not_programmable']
    report={'input_sha256':before,'count':300,'program_supported_count':len(supported),'program_passed':sum(x['status']=='pass' for x in supported),'spec_answer_mismatches':sum(x['status']=='answer_conflict' for x in supported),'check_errors':sum(x['status']=='error' for x in supported),'member_reviewed_spec_not_programmable':len(results)-len(supported),'new_human_review_tasks_created':0,'scope':'Executions of explicit specifications; not a general natural-language theorem prover. Member review is accepted as user-confirmed, no new human checks assigned.','results':results}
    assert sha(OUT/'questions.jsonl')==before and len(results)==300
    dump(OUT/'reports/current_variant_math.json',report)
    assert all(x['status']=='pass' for x in supported)
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False));return report
if __name__=='__main__':verify()
