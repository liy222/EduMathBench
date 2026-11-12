"""Integrity, split and offline parser reproducibility checks; no network calls."""
import copy,csv,json,hashlib,re,sqlite3
from collections import Counter,defaultdict
from pathlib import Path
import rebuild_web_benchmark as r
import web_benchmark_delivery as d

def replay():
    con=r.db();saved=[json.loads(x[0]) for x in con.execute('select record from items order by site,native_id')];con.close()
    errors=[];raws=set()
    for old in saved:
        try:
            raw=r.OUT/old['raw_path'];raws.add(str(raw));assert r.sha(raw)==old['raw_sha256'],'raw SHA changed'
            parsed=r.site.parse_question(old['source_platform'],raw.read_text(encoding='utf-8'),old['source_url'],old['filters_requested'],raw)
            q=r.normalize_record(parsed,old['filters_requested'],raw,r.sha(raw))
            if old.get('answer_ocr',{}).get('accepted'):
                images=[a for a in old['image_assets'] if a['role']=='answer'];assert len(images)==1
                assert r.sha(r.OUT/images[0]['local_path'])==old['answer_ocr']['image_sha256']
                q['answer']=old['answer_ocr']['answer']
            for key in ['id','question','options','answer','grade','module','difficulty','source_difficulty_label']:
                assert q[key]==old[key],f'{key} not reproducible'
            assert [(a['asset_id'],a['role']) for a in q['image_assets']]==[(a['asset_id'],a['role']) for a in old['image_assets']],'image occurrence changed'
        except Exception as error:errors.append({'id':old['id'],'error':str(error)})
    chosen=r.select(True,write=False,records=saved);expected=r.read(r.OUT/'selected/new_questions.jsonl')
    same=[q['id'] for q in chosen]==[q['id'] for q in expected]
    report={'checked_at':r.site.stamp(),'candidate_records':len(saved),'distinct_raw_files':len(raws),'parser_errors':errors,'selection_reproduced':same,'selected_count':len(chosen),'network_requests':0,
            'scope':'Source HTML reparsed offline; ordinary OCR accepted evidence reused after answer-image SHA check. Selection recomputed with fixed mapping, seed and archived assets; no OCR accuracy or math approval claim.',
            'passed':not errors and same}
    r.dump(r.OUT/'reports/offline_replay.json',report);assert report['passed'],errors[:3]
    return report

def verify():
    rows=r.read(r.OUT/'questions.jsonl');public=[q for q in rows if q['source_type']=='public'];variants=[q for q in rows if q['source_type']=='variant'];issues=[];checks=[]
    def check(name,fn):
        try:fn();checks.append({'name':name,'passed':True})
        except Exception as e:issues.append({'name':name,'error':str(e)});checks.append({'name':name,'passed':False})
    def require(value,message):
        if not value:raise AssertionError(message)
    cfg=json.loads((r.OUT/'rebuild_config.json').read_text(encoding='utf-8'));baseline=json.loads((r.OUT/'baseline/snapshot.json').read_text(encoding='utf-8'))
    retained=r.read(r.OUT/'baseline/retained_original.jsonl');retired=r.read(r.OUT/'baseline/retired_public.jsonl')+r.read(r.OUT/'baseline/retired_variants.jsonl')
    check('baseline_unchanged',lambda:require(r.sha(r.ROOT/baseline['source_path'])==baseline['sha256'],'legacy data changed'))
    check('record_counts_and_unique_ids',lambda:require((len(rows),len(public),len(variants),len({q['id'] for q in rows}))==(1800,1500,300,1800),'record counts'))
    check('retained_363_stable_ids',lambda:require({q['id'] for q in retained}=={q['id'] for q in public if q['acquisition_origin']=='retained_legacy_web'},'retained ID change'))
    check('no_retired_dataset_or_variant_return',lambda:require(not {q['id'] for q in rows}&{q['id'] for q in retired},'retired ID returned'))
    check('new_crawl_1137',lambda:require(sum(q['acquisition_origin']=='new_web_crawl' for q in rows)==1137,'new count'))
    expected=json.loads((r.ROOT/'config/quotas.json').read_text(encoding='utf-8'));vq=json.loads((r.ROOT/'config/variant_quotas.json').read_text(encoding='utf-8'))
    check('public_grade_module',lambda:require(Counter((q['grade'],q['module']) for q in public)==Counter({(c['grade'],c['module']):c['target'] for c in expected['cells'] if c['target']}),'public quotas'))
    check('variant_grade_module',lambda:require(Counter((q['grade'],q['module']) for q in variants)==Counter({(c['grade'],c['module']):c['target'] for c in vq['cells'] if c['target']}),'variant quotas'))
    check('public_difficulty',lambda:require(Counter(q['difficulty'] for q in public)==Counter(expected['difficulty_targets']),'public difficulty quotas'))
    def regeneration():
        from check_variant_regeneration import public_digest,TARGET,REV,ARCHIVE
        active=json.loads((r.OUT/'variants/active_generation.json').read_text(encoding='utf-8'))
        parents=r.read(r.OUT/'variants/parents.jsonl');by={q['id']:q for q in public}
        require(Counter(q['difficulty'] for q in parents)==Counter(TARGET),'mother difficulty quotas')
        require(Counter(q['difficulty'] for q in variants)==Counter(TARGET),'variant provisional coverage')
        require(r.sha(r.OUT/'variants/parents.jsonl')==active['parent_sha256']==r.sha(REV/'parents.jsonl'),'mother snapshot')
        require(all(p['difficulty']==by[p['id']]['difficulty'] for p in parents),'original difficulty relabelled')
        require(all(q['parent_snapshot_sha256']==active['parent_sha256'] and q['generation_metadata']['revision']=='v2_regeneration' for q in variants),'draft binding')
        draft_check=json.loads((REV/'checks.json').read_text(encoding='utf-8'))
        for name,digest in draft_check['authored_files'].items():require(r.sha(REV/'authored'/name)==digest,'authored draft changed since check')
        drafts={q['id']:q for file in sorted((REV/'authored').glob('*.jsonl')) for q in r.read(file)}
        require(set(drafts)=={q['id'] for q in variants},'active drafts differ')
        require(all(all(q[k]==drafts[q['id']][k] for k in ['question','options','answer','parent_id','verification_spec','difficulty','change_description']) for q in variants),'import changed authored content')
        snapshot=json.loads((ARCHIVE/'snapshot.json').read_text(encoding='utf-8'))
        require(public_digest(public)==snapshot['public_content_sha256'],'public content changed during regeneration')
        for file in snapshot['files']:require(r.sha(ARCHIVE/file['path'])==file['sha256'],'previous release archive changed')
        previous=r.read(ARCHIVE/'variants/questions.jsonl');old_ids={q['id'] for q in previous};old_stems={r.site.canonical(q['question']) for q in previous}
        require(not old_ids & {q['id'] for q in variants},'previous variant returned')
        require(not old_stems & {r.site.canonical(q['question']) for q in variants},'previous content copied')
        require(all(q['status']=='variant_draft' and not q['verification_note']['independent_math_review_completed'] for q in variants),'premature math approval')
        from record_variant_self_review import signature,FOLDER
        self_report=json.loads((FOLDER/'summary.json').read_text(encoding='utf-8'))
        self_records={x['id']:x for x in r.read(FOLDER/'records.jsonl')}
        require(self_report['count']==300 and self_report['review_records_sha256']==r.sha(FOLDER/'records.jsonl'),'self review missing or changed')
        require(all(q.get('assistant_self_review')==self_records[q['id']] and signature(q)==self_records[q['id']]['reviewed_input_sha256'] and q['answer']==self_records[q['id']]['rederived_answer'] and not self_records[q['id']]['independent_math_review_completed'] for q in variants),'self review stale or misrepresented')
    check('regenerated_300_bound_to_exact_120_120_60_mothers_and_unchanged_public',regeneration)
    check('four_choices_answers_and_no_solutions',lambda:require(all(set(q['options'])==set('ABCD') and all(q['options'].values()) and q['answer'] in q['options'] and q['solution']=='' and q['solution_format']=='not_requested' for q in rows),'choices/answers/solution'))
    check('300_distinct_mothers_in_test',lambda:require(len({q['parent_id'] for q in variants})==300 and all(q['split']=='test' for q in variants),'mother uniqueness'))
    family=defaultdict(set)
    for q in rows:family[q['family_id']].add(q['split'])
    check('families_do_not_cross_split',lambda:require(all(len(s)==1 for s in family.values()),'family leak'))
    dev=[q for q in rows if q['split']=='dev'];debug=[q for q in rows if q['debug_subset']]
    check('dev150_50_per_grade_no_variants',lambda:require(len(dev)==150 and Counter(q['grade'] for q in dev)==Counter({7:50,8:50,9:50}) and all(q['source_type']=='public' for q in dev),'dev composition'))
    check('debug100_subset_dev_and_protected',lambda:require(len(debug)==100 and {q['id'] for q in debug}<={q['id'] for q in dev} and set(cfg['protected_debug_ids'])<={q['id'] for q in debug} and set(cfg['protected_dev_ids'])<={q['id'] for q in dev},'protected IDs'))
    def split_repeat():
        a=d.split(copy.deepcopy(public),copy.deepcopy(variants));b=d.split(copy.deepcopy(public),copy.deepcopy(variants))
        require({q['id']:(q['split'],q['debug_subset']) for q in a}=={q['id']:(q['split'],q['debug_subset']) for q in b}=={q['id']:(q['split'],q['debug_subset']) for q in rows},'split repeat differs')
    check('deterministic_family_split',split_repeat)
    assets={}
    def evidence():
        for q in public:
            if q['acquisition_origin']=='new_web_crawl':
                require(r.sha(r.OUT/q['raw_path'])==q['raw_sha256'],q['id']+' raw changed')
                require(q['lineage']['raw_sha256']==q['raw_sha256'],q['id']+' lineage')
            for a in q['image_assets']:
                file=r.OUT/a['path'];assets[str(file)]=a['sha256'];require(file.exists() and r.sha(file)==a['sha256'],q['id']+' image changed')
                require(a.get('role') not in ('answer','solution') and not a.get('contains_answer_or_solution'),q['id']+' input answer contamination')
    check('raw_and_input_image_SHA_evidence',evidence)
    def csv_roundtrip():
        with (r.OUT/'questions.csv').open(encoding='utf-8-sig',newline='') as f:csvrows=list(csv.DictReader(f))
        require([json.loads(x['record_json']) for x in csvrows]==rows,'CSV full record roundtrip')
        for csvq,q in zip(csvrows,rows):require(all(csvq['option_'+k.lower()]==q['options'][k] for k in 'ABCD') and csvq['answer']==q['answer'],'CSV choice mismatch')
    check('CSV_JSONL_full_roundtrip',csv_roundtrip)
    def input_gate():
        by={q['id']:q for q in rows}
        for name,n in [('dev',150),('test',1650),('debug100',100)]:
            inputs=r.read(r.OUT/(name+'_inputs.jsonl'));keys=r.read(r.OUT/(name+'_answer_key.jsonl'));require(len(inputs)==len(keys)==n,'input split count')
            for x,k in zip(inputs,keys):
                require(set(x)=={'id','question','options','input_modality','image_assets'},'input field leakage')
                require(x['id']==k['id'] and k['answer']==by[x['id']]['answer'],'key alignment')
                require(all(a['role'] not in ('answer','solution') for a in x['image_assets']),'image role leakage')
    check('model_input_and_answer_key_isolation',input_gate)
    groups=defaultdict(list)
    for q in public:groups[r.identity(q)].append(q)
    legacy_duplicates=[[q['id'] for q in qs] for qs in groups.values() if len(qs)>1]
    check('no_new_source_exact_duplicates',lambda:require(not any(len(qs)>1 and any(q['acquisition_origin']=='new_web_crawl' for q in qs) for qs in groups.values()),'new exact duplicate'))
    check('preserved_legacy_duplicates_same_family',lambda:require(all(len({q['family_id'] for q in qs})==1 for qs in groups.values() if len(qs)>1),'legacy duplicate family'))
    audit=json.loads((r.OUT/'reports/browser_render_check.json').read_text(encoding='utf-8'))
    check('browser_render_checked_current_1800',lambda:require(audit['passed'] and audit['records']==1800 and audit['data_sha256']==r.sha(r.OUT/'questions.jsonl'),'render check stale or failed'))
    review_audit=json.loads((r.OUT/'reports/review_page_check.json').read_text(encoding='utf-8'))
    check('review_page_100_tasks_current_data',lambda:require(review_audit['passed'] and review_audit['checked_tasks']==100 and review_audit.get('data_sha256')==r.sha(r.OUT/'questions.jsonl') and review_audit.get('review_html_sha256')==r.sha(r.OUT/'人工复核对照.html'),'review check stale or failed'))
    variants_math=json.loads((r.OUT/'reports/variant_checks.json').read_text(encoding='utf-8'))
    report={'checked_at':r.site.stamp(),'data_sha256':r.sha(r.OUT/'questions.jsonl'),'checks':checks,'issues':issues,'passed':not issues,'program_checks_passed':not issues,
            'human_review_completed':False,'mathematical_correctness_confirmed':False,'status':'program_checked_draft_pending_human_review',
            'retained_legacy_exact_duplicate_groups':legacy_duplicates,'distinct_input_files_verified':len(assets),
            'variant_math_specs_passed':sum(x['program_math_check']=='pass' for x in variants_math),'variant_semantic_review_required':300,
            'variant_assistant_self_check_completed':sum(bool(q.get('assistant_self_review')) for q in variants),'independent_variant_math_review_completed':0,
            'variant_difficulty':dict(Counter(q['difficulty'] for q in variants)),'variant_difficulty_coverage_goal':{'基础':120,'中等':120,'困难':60},
            'variant_difficulty_goal_met':Counter(q['difficulty'] for q in variants)==Counter({'基础':120,'中等':120,'困难':60}),
            'limitations':['保留363条历史记录包含2组完全重复，按既定保留范围沿用且同族隔离；未计为新爬成果。','年级按网站知识点配置归档，综合题可能涉及更高年级知识，待复核。','原题答案沿用来源；渲染通过不保证题意或数学答案正确。','母题按来源标签120/120/60选取；变式难度为作者对改编任务的暂定判断，没有学生正确率或用时校准。','程序验算覆盖已填写表达式或有限模型，不等同于题面到表达式对应关系的独立数学复核。','OCR答案未入最终1137道，20道OCR抽查任务取自试采池。']}
    r.dump(r.OUT/'reports/final_validation.json',report);assert not issues,issues
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('command',choices=['replay','verify']);a=p.parse_args()
    result=replay() if a.command=='replay' else verify();print(json.dumps({k:result[k] for k in ['passed']},ensure_ascii=False))
