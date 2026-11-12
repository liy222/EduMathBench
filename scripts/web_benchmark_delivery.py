"""Build versioned draft, isolated splits, offline viewer and review material."""
from __future__ import annotations
import argparse,base64,copy,csv,hashlib,json,re,shutil,sys
from collections import Counter,defaultdict
from pathlib import Path
import rebuild_web_benchmark as r
ROOT,OUT=r.ROOT,r.OUT

def public():
    new=r.read(OUT/'selected/new_questions.jsonl')
    assert len(new)==1137,'新原题配额未齐'
    errors=[{'id':q['id'],'reasons':r.rejection_reasons(q)} for q in new if r.rejection_reasons(q)]
    r.dump(OUT/'reports/public_asset_gate.json',{'checked':len(new),'issues':errors})
    assert not errors,f'{len(errors)}道新题仍有资源或答案问题'
    rows=r.read(OUT/'retained/questions.jsonl')+new
    expected=json.loads((ROOT/'config/quotas.json').read_text(encoding='utf-8'))
    assert Counter((q['grade'],q['module']) for q in rows)==Counter({(c['grade'],c['module']):c['target'] for c in expected['cells'] if c['target']})
    assert Counter(q['difficulty'] for q in rows)==Counter(expected['difficulty_targets'])
    for q in rows:
        old_assets=q['image_assets'];input_assets=[];answer_assets=[]
        for index,a in enumerate(old_assets):
            if a.get('role')=='answer':answer_assets.append(a);continue
            if a.get('role')=='solution':continue
            if q.get('acquisition_origin')=='retained_legacy_web':
                candidates=[ROOT/'data/benchmark_draft'/a.get('path',''),ROOT/a.get('source_project_path','')]
                source=next((p for p in candidates if p.is_file()),None)
                assert source,f'历史配图缺失：{q["id"]}'
                suffix=source.suffix;digest=r.sha(source);dest=OUT/'assets/input'/(digest[:24]+suffix)
                dest.parent.mkdir(parents=True,exist_ok=True)
                if not dest.exists():shutil.copyfile(source,dest)
                field=a.get('source_placeholder_field','question')
                input_assets.append({**a,'path':dest.relative_to(OUT).as_posix(),'sha256':digest,'source_placeholder_field':field,'placeholder_index':index})
            else:
                source=OUT/a['local_path'];assert source.is_file() and r.sha(source)==a['sha256']
                field='question' if a['role']=='question' else 'option_'+a['role'].split('_',1)[-1].lower()
                input_assets.append({'path':a['local_path'],'sha256':a['sha256'],'role':'stem' if field=='question' else 'option',
                   'source_url':a['url'],'source_ref':q['source_question_id'],'source_placeholder_field':field,
                   'placeholder':'[图片:'+a['asset_id']+']','placeholder_index':index,'alt':'原题配图','contains_answer_or_solution':False})
        q['image_assets']=input_assets;q['answer_image_assets']=answer_assets
        q['input_modality']='text_image' if input_assets else 'text'
        q['solution']='';q['solution_format']='not_requested';q['additional_sources']=q.get('additional_sources',[])
        q['status']='auto_checked';q['benchmark_status']='draft_not_frozen';q['format_version']='benchmark-format-v0.2-web'
        if q.get('answer_ocr'):
            q['risk_flags']=[x for x in q['risk_flags'] if x not in ('answer_image_requires_transcription','source_answer_missing')]
            q['risk_flags'].append('ocr_answer_pending_human_sample_check')
        assert q['answer'] in 'ABCD' and len(q['answer'])==1
    r.jsonl(OUT/'public/questions.jsonl',rows)
    return rows

def families(rows):
    parent={q['id']:q['id'] for q in rows};groups=defaultdict(list)
    def find(a):
        while parent[a]!=a:parent[a]=parent[parent[a]];a=parent[a]
        return a
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[max(a,b)]=min(a,b)
    # Existing families, exact wording, and conservative numerical-template groups.
    buckets=defaultdict(list)
    for q in rows:
        if q.get('family_id'):buckets['old:'+q['family_id']].append(q['id'])
        key=r.identity(q);buckets['exact:'+key].append(q['id'])
        if not q['image_assets']:
            stem=r.site.canonical(q['question'])
            # Only large near-identical stems qualify; short generic stems overmerge.
            template=re.sub(r'\d+(?:\.\d+)?','<N>',stem)
            if len(template)>=35:buckets['template:'+template].append(q['id'])
    for ids in buckets.values():
        for b in ids[1:]:union(ids[0],b)
    for q in rows:groups[find(q['id'])].append(q)
    for members in groups.values():
        fid='EMB-F-WEB2-'+hashlib.sha256('|'.join(sorted(q['id'] for q in members)).encode()).hexdigest()[:16]
        for q in members:q['upstream_family_id']=q.get('family_id','');q['family_id']=fid
    return list(groups.values())

def parents():
    # Stage only. Never silently fill a missing difficulty with another label.
    from select_variant_parents_v2 import main
    main()

def variants():
    from verify_web_variant_math import check_spec
    mothers={q['id']:q for q in r.read(OUT/'variants/parents.jsonl')};rows=[];checks=[]
    active_file=OUT/'variants/active_generation.json'
    active=json.loads(active_file.read_text(encoding='utf-8')) if active_file.exists() else {}
    authored=OUT/active.get('authored_directory','variants/authored')
    self_check_file=OUT/'review/assistant_self_check_v2/records.jsonl'
    self_checks={q['id']:q for q in r.read(self_check_file)} if self_check_file.exists() else {}
    assert authored.resolve().is_relative_to((OUT/'variants').resolve()),'变式目录超出项目范围'
    if active:assert r.sha(OUT/'variants/parents.jsonl')==active['parent_sha256'],'母题绑定变化'
    for file in sorted(authored.glob('*.jsonl')):
        for q in r.read(file):
            p=mothers[q['parent_id']]
            assert q['source_type']=='variant' and q['parent_id'] not in {x['parent_id'] for x in rows}
            assert set(q['options'])==set('ABCD') and len(set(q['options'].values()))==4 and q['answer'] in q['options']
            assert q['question']!=p['question'] and q['change_description']
            if active:
                assert q['parent_snapshot_sha256']==active['parent_sha256'] and q['generation_revision']==active['revision']
            q.update(grade=p['grade'],module=p['module'],knowledge_point=p['knowledge_point'],family_id=p['family_id'],
                     input_modality='text',image_assets=[],source=copy.deepcopy(p['source']),additional_sources=[],
                     solution='',solution_format='not_requested',status='variant_draft',benchmark_status='draft_not_frozen',
                     format_version='benchmark-format-v0.2-web',source_exam_grade=p.get('source_exam_grade'),
                     risk_flags=['generated_variant','math_review_pending'],acquisition_origin='assistant_generated_variant')
            q['source']['relation']='generated_variant_of_public_parent'
            q['generation_metadata']={'agent':'current_assistant','model':'runtime_model_identifier_unavailable','generated_at':q.get('authored_at',r.site.stamp()),'method':'assistant_authored_per_parent','revision':active.get('revision','first_web_generation'),'parent_snapshot_sha256':q.get('parent_snapshot_sha256','')}
            q['difficulty_annotation']={'reason':q.pop('difficulty_reason','与母题主要知识及推理步骤对照后的暂定标签，未实测校准'),'method':'assistant_provisional_variant_label'}
            q['difficulty_annotation']['basis']=q.get('difficulty_basis','author_task_review_not_empirical')
            q['verification_note']={'scope':q['verification_note'] if isinstance(q['verification_note'],str) else q['verification_note']['scope'],'independent_math_review_completed':False}
            if q.get('verification_spec',{}).get('kind')=='manual_review_required':
                checks.append({'id':q['id'],'program_math_check':'not_supported','reason':q['verification_spec']['reason']})
                q['risk_flags'].append('program_math_verification_not_supported')
            else:
                matches,detail=check_spec(q['verification_spec']);assert matches==[q['answer']],(q['id'],matches,q['answer'])
                checks.append({'id':q['id'],'program_math_check':'pass','detail':detail})
            if self_checks:
                from record_variant_self_review import signature
                record=self_checks[q['id']]
                assert record['reviewed_input_sha256']==signature(q),'自查记录与题面不匹配：'+q['id']
                q['assistant_self_review']=copy.deepcopy(record)
                q['risk_flags'].append('assistant_self_checked_user_review_pending')
            rows.append(q)
    r.jsonl(OUT/'variants/questions.jsonl',rows);r.dump(OUT/'reports/variant_checks.json',checks)
    print(json.dumps({'authored_variants':len(rows),'program_math_passed':sum(x['program_math_check']=='pass' for x in checks),'manual_review_pending':len(rows)},ensure_ascii=False))
    return rows

def subset_families(pool,need):
    dp={0:[]}
    for group in sorted(pool,key=lambda g:r.rank(g[0]['family_id'])):
        size=len(group)
        for count,chosen in sorted(list(dp.items()),reverse=True):
            if count+size<=need and count+size not in dp:dp[count+size]=chosen+[group]
        if need in dp:return dp[need]
    raise ValueError(f'无法按完整题族填充开发集缺口{need}')

def split(rows,variants):
    cfg=json.loads((OUT/'rebuild_config.json').read_text(encoding='utf-8'))
    groups=defaultdict(list)
    for q in rows:groups[q['family_id']].append(q)
    parent_families={q['family_id'] for q in variants}
    protected=set(cfg['protected_dev_ids']);forced={fid for fid,qs in groups.items() if any(q['id'] in protected for q in qs)}
    assert not forced&parent_families,'变式母题与受保护开发题族冲突'
    dev=[q for fid in forced for q in groups[fid]]
    for grade in (7,8,9):
        need=50-sum(q['grade']==grade for q in dev);assert need>=0
        candidates=[qs for fid,qs in groups.items() if fid not in forced|parent_families and {q['grade'] for q in qs}=={grade}]
        for group in subset_families(candidates,need):dev.extend(group);forced.add(group[0]['family_id'])
    debug=set(cfg['protected_debug_ids']);assert debug<={q['id'] for q in dev}
    for q in sorted(dev,key=lambda q:r.rank(q['id'])):
        if len(debug)>=100:break
        debug.add(q['id'])
    for q in rows+variants:q['split']='dev' if q['family_id'] in forced else 'test';q['debug_subset']=q['id'] in debug
    assert len(dev)==150 and len(debug)==100 and all(q['split']=='test' for q in variants)
    return rows+variants

def export(rows):
    r.jsonl(OUT/'questions.jsonl',rows)
    columns=['id','source_type','grade','module','knowledge_point','difficulty','question','option_a','option_b','option_c','option_d','answer','solution','solution_format','parent_id','family_id','split','debug_subset','input_modality','source_url','source_title','status','acquisition_origin','answer_access','record_json']
    with (OUT/'questions.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=columns);writer.writeheader()
        for q in rows:
            row={k:q.get(k,'') for k in columns};row.update({'option_'+k.lower():v for k,v in q['options'].items()});row.update(source_url=q['source']['url'],source_title=q['source']['title'],record_json=json.dumps(q,ensure_ascii=False));writer.writerow(row)
    for name,predicate in [('dev',lambda q:q['split']=='dev'),('test',lambda q:q['split']=='test'),('debug100',lambda q:q['debug_subset'])]:
        subset=[q for q in rows if predicate(q)]
        inputs=[];keys=[]
        for q in subset:
            inputs.append({k:q[k] for k in ['id','question','options','input_modality']}|{'image_assets':[{k:a[k] for k in ['path','sha256','role','source_placeholder_field','placeholder','placeholder_index'] if k in a} for a in q['image_assets']]})
            keys.append({k:q[k] for k in ['id','answer','grade','module','difficulty','source_type','parent_id','family_id']})
        r.jsonl(OUT/(name+'_inputs.jsonl'),inputs);r.jsonl(OUT/(name+'_answer_key.jsonl'),keys)
    stat={'count':len(rows),'by_source_type':dict(Counter(q['source_type'] for q in rows)),
          'public_difficulty':dict(Counter(q['difficulty'] for q in rows if q['source_type']=='public')),
          'variant_difficulty':dict(Counter(q['difficulty'] for q in rows if q['source_type']=='variant')),
          'split':dict(Counter(q['split'] for q in rows)),
          'acquisition':dict(Counter(q['acquisition_origin'] for q in rows)),
          'new_web_by_site':dict(Counter(q.get('source_platform') for q in rows if q['acquisition_origin']=='new_web_crawl')),
          'new_web_ocr_answers':sum(bool(q.get('answer_ocr',{}).get('accepted')) for q in rows),
          'images':dict(Counter(q['input_modality'] for q in rows)),'formal_math_review_completed':False}
    r.dump(OUT/'statistics.json',stat)

def viewer(rows):
    import web_benchmark_viewer
    web_benchmark_viewer.render(rows)

def build():
    rows=r.read(OUT/'public/questions.jsonl');v=variants()
    assert len(rows)==1500 and len(v)==300,'公开题或变式尚未齐全，拒绝发布1800题成品'
    expected=json.loads((ROOT/'config/variant_quotas.json').read_text(encoding='utf-8'))['cells']
    assert Counter((q['grade'],q['module']) for q in v)==Counter({(c['grade'],c['module']):c['target'] for c in expected})
    rows=split(rows,v);export(rows);viewer(rows)
    print(json.dumps({'built':len(rows),'directory':str(OUT)},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['public','parents','variants','build'])
    command=parser.parse_args().command
    if command=='public':public()
    elif command=='parents':parents()
    elif command=='variants':variants()
    elif command=='build':build()
