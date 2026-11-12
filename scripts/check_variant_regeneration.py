"""Check explicit drafts and archive the previous release before activation."""
import argparse,copy,json,shutil
from collections import Counter
import rebuild_web_benchmark as r
from verify_web_variant_math import check_spec

REV=r.OUT/'variants/regeneration_v2'
ARCHIVE=r.OUT/'variants/archive_before_regeneration_v2'
TARGET={'基础':120,'中等':120,'困难':60}

def public_digest(rows):
    fields=['id','question','options','answer','grade','module','difficulty','family_id','source','image_assets']
    return r.hashlib.sha256(json.dumps([{k:q.get(k) for k in fields} for q in rows],ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def check():
    parents=r.read(REV/'parents.jsonl');public=r.read(r.OUT/'public/questions.jsonl');by={q['id']:q for q in parents}
    rows=[q for p in sorted((REV/'authored').glob('*.jsonl')) for q in r.read(p)]
    assert len(rows)==len(by)==len({q['parent_id'] for q in rows})==len({q['id'] for q in rows})==300
    assert Counter(q['difficulty'] for q in parents)==Counter(TARGET)
    assert Counter(q['difficulty'] for q in rows)==Counter(TARGET)
    assert Counter(by[q['parent_id']]['grade'] for q in rows)==Counter({7:100,8:100,9:100})
    old=r.read(ARCHIVE/'variants/questions.jsonl') if ARCHIVE.exists() else r.read(r.OUT/'variants/questions.jsonl')
    old_stems={r.site.canonical(q['question']) for q in old}
    seen=set();math=[];source_stems={r.site.canonical(q['question']) for q in public}
    for q in rows:
        p=by[q['parent_id']];stem=r.site.canonical(q['question'])
        assert q['id'].startswith('EMB-V-WEB2R2-') and stem not in old_stems and stem not in source_stems and stem not in seen,q['id']+' duplicate stem'
        seen.add(stem)
        assert q['parent_snapshot_sha256']==r.sha(REV/'parents.jsonl'),q['id']+' parent SHA'
        assert set(q['options'])==set('ABCD') and len(set(q['options'].values()))==4 and all(q['options'].values())
        assert q['answer'] in q['options'] and q['change_description'] and q['verification_note']
        assert q['parent_difficulty']==p['difficulty']
        spec=q['verification_spec']
        if spec['kind']=='manual_review_required':math.append({'id':q['id'],'status':'unsupported','scope':spec['reason']})
        else:
            matches,detail=check_spec(spec);assert matches==[q['answer']],(q['id'],matches,q['answer'])
            math.append({'id':q['id'],'status':'pass','kind':spec['kind'],'detail':detail})
    cfg=json.loads((r.OUT/'rebuild_config.json').read_text(encoding='utf-8'))
    protected={q['family_id'] for q in public if q['id'] in cfg['protected_dev_ids']}
    assert not protected & {q['family_id'] for q in parents}
    assert len({q['family_id'] for q in parents})==300
    expected=json.loads((r.ROOT/'config/variant_quotas.json').read_text(encoding='utf-8'))['cells']
    assert Counter((q['grade'],q['module']) for q in parents)==Counter({(c['grade'],c['module']):c['target'] for c in expected})
    report={'checked_at':r.site.stamp(),'revision':'v2_regeneration','count':300,'parent_difficulty':dict(Counter(q['difficulty'] for q in parents)),
      'variant_provisional_difficulty':dict(Counter(q['difficulty'] for q in rows)),'different_from_previous_300':True,'new_stems_distinct_from_1500_originals':True,
      'parent_sha256':r.sha(REV/'parents.jsonl'),'public_content_sha256':public_digest(public),'authored_files':{p.name:r.sha(p) for p in sorted((REV/'authored').glob('*.jsonl'))},
      'program_math_passed':sum(x['status']=='pass' for x in math),'manual_math_pending':sum(x['status']=='unsupported' for x in math),'all_300_semantic_and_independent_math_review_pending':True,
      'math_details':math,'pilot_30':{'count':30,'passed':all(x['status'] in ('pass','unsupported') for x in math[:30]),'scope':'structure, linkage, changed content and supported math specifications; unsupported geometry/concepts explicitly pending'},'passed':True}
    r.dump(REV/'checks.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('math_details','authored_files')},ensure_ascii=False))
    return report

def activate(report):
    if not ARCHIVE.exists():
        files=['questions.jsonl','questions.csv','statistics.json','完整题库浏览.html','人工复核对照.html','阶段实施报告.md','使用说明.md',
          'dev_inputs.jsonl','dev_answer_key.jsonl','test_inputs.jsonl','test_answer_key.jsonl','debug100_inputs.jsonl','debug100_answer_key.jsonl',
          'public/questions.jsonl','variants/parents.jsonl','variants/questions.jsonl','variants/authoring_input.jsonl',
          'reports/parent_selection.json','reports/variant_checks.json','reports/final_validation.json','reports/browser_render_check.json','reports/review_page_check.json',
          'review/tasks.jsonl','review/人工复核结果表.csv']
        files += [p.relative_to(r.OUT).as_posix() for p in (r.OUT/'variants/authored').glob('*.jsonl')]
        manifest=[]
        for name in files:
            source=r.OUT/name
            if not source.is_file():continue
            target=ARCHIVE/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            assert r.sha(source)==r.sha(target)
            manifest.append({'path':name,'sha256':r.sha(target),'bytes':target.stat().st_size})
        r.dump(ARCHIVE/'snapshot.json',{'archived_at':r.site.stamp(),'status':'superseded_by_v2_regeneration','files':manifest,'public_content_sha256':report['public_content_sha256']})
    r.dump(r.OUT/'variants/active_generation.json',{'revision':'v2_regeneration','authored_directory':'variants/regeneration_v2/authored','parent_file':'variants/regeneration_v2/parents.jsonl','parent_sha256':report['parent_sha256'],'difficulty_basis':'source-labelled parent selection and provisional author task review; no student calibration','superseded_archive':'variants/archive_before_regeneration_v2'})
    shutil.copyfile(REV/'parents.jsonl',r.OUT/'variants/parents.jsonl')
    shutil.copyfile(REV/'authoring_input.jsonl',r.OUT/'variants/authoring_input.jsonl')
    shutil.copyfile(REV/'selection.json',r.OUT/'reports/parent_selection.json')
    print('Activated v2 drafts; previous release archived with SHA-256. Rebuild and render checks are still required.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--activate',action='store_true');args=p.parse_args()
    report=check()
    if args.activate:activate(report)
