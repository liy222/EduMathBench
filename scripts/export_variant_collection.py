"""Combine checked batches; keep the public bank and historical pilot immutable."""
import base64
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
from verify_pilot_variants import check_spec
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/variants/collection'
def read(p):return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def dump(p,obj):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def content_sha(q):return hashlib.sha256(json.dumps({k:q[k] for k in ['question','options','answer','solution']},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
def load_reviews():
    reviews={}
    for name in ['variant_pilot_root_review.json','variant_pilot_g9_independent_review.json']:
        path=ROOT/'data/reports'/name
        for r in json.loads(path.read_text(encoding='utf-8'))['records']:
            reviews[r['id']]={'answer':r.get('answer',r.get('independently_derived_answer')),'file':str(path.relative_to(ROOT)),'status':'independent_draft_review','snapshot_sha256':None}
    for path in sorted((ROOT/'data/variants/batches').glob('*/review_g*.json')):
        report=json.loads(path.read_text(encoding='utf-8'))
        for r in report['records']:
            assert r['status'] in ['pass','independent_review_pending'],f'unresolved review: {r["id"]}'
            assert not r.get('issues'),f'unresolved issues: {r["id"]}'
            reviews[r['id']]={'answer':r['independently_derived_answer'],'file':str(path.relative_to(ROOT)),'status':r['status'],'snapshot_sha256':r['content_sha256'],'reviewer_agent':report['reviewer_agent']}
    return reviews
def build():
    OUT.mkdir(parents=True,exist_ok=True)
    raw=ROOT/'data/public_draft/questions.jsonl';normalized=ROOT/'data/normalized/questions.jsonl'
    raw_hash=sha(raw);norm_hash=sha(normalized)
    parents={p['id']:p for p in read(ROOT/'data/variants/parents/parents_300.jsonl')}
    source={p['id']:p for p in read(normalized)}
    for p in parents.values():assert all(p[k]==v for k,v in source[p['id']].items()),'source-field mutation'
    qs=read(ROOT/'data/variants/pilot/variants_30.jsonl')
    batch_files=sorted((ROOT/'data/variants/batches').glob('*/g[789].jsonl'))
    for path in batch_files:qs.extend(read(path))
    reviews=load_reviews();results=[];ids=set();used=set();stems=set()
    config=json.loads((ROOT/'config/variant_quotas.json').read_text(encoding='utf-8'))
    for q in qs:
        errors=[];detail={}
        try:
            assert q['id'] not in ids,'duplicate variant id';ids.add(q['id'])
            assert q['parent_id'] not in used,'parent used twice';used.add(q['parent_id'])
            p=parents[q['parent_id']]
            assert q['family_id']==p['family_id'],'family mismatch'
            assert int(q['grade'])==int(p['grade']) and q['module']==p['module'],'grade/module mismatch'
            assert q['source_type']=='variant' and q['status']=='variant_draft_pending_review','wrong draft status'
            assert set(q['options'])==set('ABCD') and len(set(q['options'].values()))==4,'options missing/identical'
            assert all(q.get(k) for k in ['question','solution','change_description','generation_metadata','difficulty_annotation']),'missing derivation/metadata'
            assert q['question']!=p['question'],'unchanged parent stem'
            fingerprint=re.sub(r'\s+','',q['question'])
            assert fingerprint not in stems,'duplicate generated stem';stems.add(fingerprint)
            assert q['input_modality']=='text' and not q.get('image_assets'),'this batch must be text only'
            assert not re.search(r'如图|下图|图中|<ImageHere>|<img\b',q['question']),'text variant still depends on unspecified image'
            for field in [q['question'],*q['options'].values(),q['solution']]:
                assert not any(ord(c)<32 and c not in '\n\t\r' for c in field),'control character'
            correct,detail=check_spec(q['verification_spec'])
            assert correct==[q['answer']],f'arithmetic choices {correct}, answer {q["answer"]}'
            review=reviews[q['id']]
            pending=review['status']=='independent_review_pending'
            if not pending:assert review['answer']==q['answer'],'independent answer disagreement'
            if review.get('snapshot_sha256'):assert review['snapshot_sha256']==content_sha(q),'review applies to different text/answer'
            if review.get('reviewer_agent'):assert review['reviewer_agent']!=q['generation_metadata']['agent'],'generator self-review is not independent'
            q['verification_note']={'arithmetic_constraints':'passed','prose_derivation_review':'independent_review_pending' if pending else 'independent_draft_review','review_record':review['file'],'recorded_content_sha256':content_sha(q),'final_math_approval':False,'scope':'计算与生成者自检通过，独立复核尚未完成。' if pending else '题面推导已独立初核，草稿仍待正式复核与冻结。'}
            q['source']={k:p.get(k,'') for k in ['source_id','source_ref','source_title','source_url','source_raw_path','source_accessed_at','source_reuse_status','source_notes']}
            q['source']['relation']='Generated variant; source identifies its public parent, not a public origin for the generated item.'
            q['parent_risk_flags']=p.get('risk_flags',[])
            q['format_version']='variant-format-v0.1'
        except (AssertionError,KeyError,ValueError,TypeError,ZeroDivisionError) as e:errors.append(str(e))
        results.append({'id':q['id'],'passed':not errors,'errors':errors,'detail':detail})
    cells=Counter((int(q['grade']),q['module'],q['difficulty']) for q in qs)
    for cell in config['cells']:
        assert sum(n for (g,m,d),n in cells.items() if g==cell['grade'] and m==cell['module'])<=cell['target'],'grade/module quota overflow'
    # Difficulty is provisional and follows actual tasks; it is not forced to fit a label quota.
    if len(qs)==config['variant_target']:
        assert {q['parent_id'] for q in qs}==set(parents),'final variants do not cover all selected parents'
        for cell in config['cells']:
            assert sum(n for (g,m,d),n in cells.items() if g==cell['grade'] and m==cell['module'])==cell['target'],'final grade/module shortfall'
    independently_reviewed=sum(q.get('verification_note',{}).get('prose_derivation_review')=='independent_draft_review' for q in qs)
    summary={'count':len(qs),'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),'independently_reviewed':independently_reviewed,'independent_review_pending':len(qs)-independently_reviewed,'grade_counts':dict(Counter(str(q['grade']) for q in qs)),'difficulty_counts':dict(Counter(q['difficulty'] for q in qs)),'modality_counts':dict(Counter(q['input_modality'] for q in qs)),'parent_links':len(used),'scope':'Structure and explicit arithmetic constraints; separately records independently reviewed items and pending items. Not final approval or public-bank mathematical validation.','results':results}
    dump(ROOT/'data/reports/variant_collection_check.json',summary)
    for r in results:
        if not r['passed']:print(r['id'],r['errors'])
    assert summary['failed']==0,'unresolved checks: delivery aborted'
    jsonl=OUT/'questions.jsonl';jsonl.write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in qs),encoding='utf-8')
    fields=['id','parent_id','family_id','source_type','grade','module','knowledge_point','difficulty','input_modality','question','option_a','option_b','option_c','option_d','answer','solution','change_description','source_title','source_url','source_ref','source_reuse_status','agent','model','generated_at','status','verification_note']
    csvfile=OUT/'questions.csv'
    with csvfile.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for q in qs:
            row={k:q.get(k,'') for k in fields};row.update({'option_'+k.lower():q['options'][k] for k in 'ABCD'})
            row.update({k:q['source'].get(k,'') for k in ['source_title','source_url','source_ref','source_reuse_status']})
            row.update({k:q['generation_metadata'].get(k,'') for k in ['agent','model','generated_at']})
            row['verification_note']=json.dumps(q['verification_note'],ensure_ascii=False);w.writerow(row)
    with csvfile.open(encoding='utf-8-sig',newline='') as f:
        csv_rows=list(csv.DictReader(f))
    assert len(csv_rows)==len(qs)
    for q,row in zip(qs,csv_rows):assert q['question']==row['question'] and q['answer']==row['answer'] and all(q['options'][k]==row['option_'+k.lower()] for k in 'ABCD')
    pairs=[];image_paths=set()
    for q in qs:
        p=parents[q['parent_id']]
        parent={k:p.get(k,'') for k in ['id','grade','module','knowledge_point','difficulty','question','answer','family_id','source_title','source_url','source_ref','risk_flags']}
        parent['options']={k:p['option_'+k.lower()] for k in 'ABCD'}
        parent['image_assets']=p.get('image_assets',[]);parent['image_data']=[]
        for a in parent['image_assets']:
            file=ROOT/a['path'];assert file.exists() and sha(file)==a['sha256'];image_paths.add(file)
            mime='image/png' if file.suffix.lower()=='.png' else 'image/jpeg'
            parent['image_data'].append({'alt':a.get('alt','原题配图'),'data_url':'data:'+mime+';base64,'+base64.b64encode(file.read_bytes()).decode()})
        pairs.append({'parent':parent,'variant':q})
    dump(OUT/'pairs.json',pairs)
    assets=ROOT/'data/reports/visualization_assets'
    css=(assets/'katex.min.css').read_text(encoding='utf-8')
    def embed(m):return 'src:url(data:font/woff2;base64,'+base64.b64encode((assets/'fonts'/m[1]).read_bytes()).decode()+') format("woff2")}'
    css=re.sub(r'src:url\(fonts/([^)]*\.woff2)\) format\("woff2"\)[^}]*}',embed,css)
    assert 'url(fonts/' not in css
    template=(ROOT/'data/visualization/variant_pairs_template.html').read_text(encoding='utf-8').replace('首批变式题对 · 30道',f'变式题库 · {len(qs)}道').replace('首批变式题对','变式题库')
    page=template.replace('__KATEX_CSS__',css).replace('__KATEX_JS__',(assets/'katex.min.js').read_text(encoding='utf-8')).replace('__AUTO_RENDER_JS__',(assets/'auto-render.min.js').read_text(encoding='utf-8')).replace('__CONTENT_JS__',(ROOT/'data/visualization/question_content.js').read_text(encoding='utf-8')).replace('__PAIRS__',json.dumps(pairs,ensure_ascii=False).replace('<','\\u003c'))
    pagefile=ROOT/'可视化/变式题库浏览.html';pagefile.write_text(page,encoding='utf-8')
    note=f'''# 变式草稿通用交付\n\n当前{len(qs)}道变式，每题有parent_id/family_id、来源、修改说明、推导、暂定难度和生成记录。全部为纯文字变式；几何题保留完整文字条件，不要求配图。\n\nquestions.jsonl为通用数据；questions.csv为UTF-8带BOM；pairs.json为题对。双击“变式题库浏览.html”可离线查看。必要母题原图内嵌在页面，并以原相对路径附于包中；变式的输入图片列表为空。\n\n显式算术检查全部通过。独立题面初核完成{independently_reviewed}道，剩{len(qs)-independently_reviewed}道独立复核待完成，不能将生成者自检算作独立审查。均仍是草稿，不表示1500公开题已通过数学复核，也未正式冻结。新页面尚未取得实际浏览器运行报告。\n\n1500公开题不变；加变式共{1500+len(qs)}道草稿，距300变式目标还差{300-len(qs)}道。开发/测试划分需同题族同侧，当前尚未划分。\n'''
    (OUT/'使用说明.md').write_text(note,encoding='utf-8')
    complete=len(qs)==config['variant_target']
    config.update(status='variant_generation_complete_pending_final_freeze' if complete else 'variant_batches_generated_checked_pending_final_review',generated_variant_count=len(qs),remaining_variant_count=300-len(qs),next_delivery='汇总1800题初版并按题族划分，正式复核与冻结尚未完成' if complete else '按批完成剩余纯文字优先变式，目标累计300')
    dump(ROOT/'config/variant_quotas.json',config)
    progress={'updated_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),'public_count':1500,'variant_count':len(qs),'combined_draft_count':1500+len(qs),'variant_target':300,'remaining_variants':300-len(qs),'grade_counts':summary['grade_counts'],'difficulty_counts':summary['difficulty_counts'],'input_modality_counts':summary['modality_counts'],'public_raw_sha256':raw_hash,'normalized_public_sha256':norm_hash,'independent_reviewed_variants':independently_reviewed,'independent_review_pending':len(qs)-independently_reviewed,'final_approved':False,'browser_verified':False,'batch_files':[str(p.relative_to(ROOT)) for p in batch_files]}
    dump(ROOT/'data/reports/variant_collection_progress.json',progress)
    if sha(raw)!=raw_hash or sha(normalized)!=norm_hash:raise AssertionError('public mutation')
    print(json.dumps(progress,ensure_ascii=False))
    return qs
def package():
    files=[*sorted(OUT.glob('*')),ROOT/'可视化/变式题库浏览.html',ROOT/'config/variant_quotas.json',ROOT/'docs/variant_stage_plan.md',ROOT/'data/reports/variant_collection_check.json',ROOT/'data/reports/variant_collection_progress.json',ROOT/'data/reports/visualization_assets/KaTeX-LICENSE.txt',ROOT/'data/variants/parents/parents_300.jsonl',ROOT/'data/variants/parents/parents_300.csv']
    substitutions=ROOT/'data/variants/parents/b003_substitutions.json'
    if substitutions.exists():files.append(substitutions)
    for folder in sorted((ROOT/'data/variants/batches').glob('*')):
        files.extend(sorted(folder.glob('review_g*.json')))
        if (folder/'selection_report.json').exists():files.append(folder/'selection_report.json')
        if (folder/'provenance_audit.json').exists():files.append(folder/'provenance_audit.json')
        if (folder/'completion_report.md').exists():files.append(folder/'completion_report.md')
        files.extend(sorted(folder.glob('generation_notes_g*.md')))
        files.extend(sorted(folder.glob('selfcheck_g*.json')))
    presentation=ROOT/'data/reports/variant_collection_presentation_check.json'
    if presentation.exists():files.append(presentation)
    parent_map={p['id']:p for p in read(ROOT/'data/variants/parents/parents_300.jsonl')}
    for q in read(OUT/'questions.jsonl'):
        p=parent_map[q['parent_id']]
        files.extend(ROOT/a['path'] for a in p.get('image_assets',[]))
    manifest={'files':{}}
    files=sorted(set(f for f in files if f.is_file() and f.name!='manifest.json'))
    for f in files:manifest['files'][f.relative_to(ROOT).as_posix()]={'sha256':sha(f),'bytes':f.stat().st_size}
    dump(OUT/'manifest.json',manifest)
    n=len(read(OUT/'questions.jsonl'));destination=ROOT/f'data/exports/EduMathBench_variants_{n}_draft.zip'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as z:
        for f in [*files,OUT/'manifest.json']:z.write(f,f.relative_to(ROOT).as_posix())
        # A conveniently placed self-contained entry point.
        z.write(ROOT/'可视化/变式题库浏览.html','变式题库浏览.html')
    with zipfile.ZipFile(destination) as z:
        assert z.testzip() is None
        for name,meta in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==meta['sha256']
    print(f'Packaged {n} draft variants: {destination.name}')
if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    if '--package-only' in sys.argv:package()
    else:build()
