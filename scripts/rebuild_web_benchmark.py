"""Reproducible web-source replacement; no model calls in acquisition/processing."""
from __future__ import annotations
import argparse, copy, csv, hashlib, json, re, sqlite3, sys, time, math
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlencode, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/site_crawler'))
import edumath_crawler as site
site.MATH_DELIMITERS=True
from lxml import html

OUT = ROOT / 'data/benchmark_web_v0.2'
PREFIXES = ('EMB-P-BULK-CMM-', 'EMB-P-BULK-TAL-', 'EMB-P-MATHBENCH-',
            'EMB-P-CEVAL-', 'EMB-P-CJEVAL-', 'EMB-P-IMG-CMM-', 'EMB-P-CMMA-')

def read(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]

def dump(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def jsonl(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def db():
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(OUT/'state.sqlite')
    con.execute('CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, site TEXT, raw_path TEXT, sha256 TEXT, state TEXT, acquired_at TEXT, error TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS items (site TEXT, native_id TEXT, record TEXT, PRIMARY KEY(site,native_id))')
    con.execute('CREATE TABLE IF NOT EXISTS jobs (url TEXT PRIMARY KEY, state TEXT, candidates INTEGER, finished_at TEXT)')
    return con

def initialize():
    baseline = ROOT/'data/benchmark_draft/questions.jsonl'
    digest = sha(baseline)
    lock = OUT/'baseline/snapshot.json'
    if lock.exists():
        assert json.loads(lock.read_text(encoding='utf-8'))['sha256'] == digest, '旧版题库已变化，停止，避免混用版本'
        return
    rows = read(baseline)
    public = [q for q in rows if q['source_type']=='public']
    retained = [q for q in public if not q['id'].startswith(PREFIXES)]
    retired = [q for q in public if q['id'].startswith(PREFIXES)]
    assert (len(retained),len(retired)) == (363,1137)
    protected_dev = [q['id'] for q in retained if q['split']=='dev']
    protected_debug = [q['id'] for q in retained if q.get('debug_subset')]
    assert len(protected_dev)==31 and len(protected_debug)==20
    jsonl(OUT/'baseline/retained_original.jsonl', retained)
    jsonl(OUT/'baseline/retired_public.jsonl', retired)
    jsonl(OUT/'baseline/retired_variants.jsonl', [q for q in rows if q['source_type']=='variant'])
    cleaned = []
    for q in retained:
        q = copy.deepcopy(q); q['solution']='';q['solution_format']='not_requested'
        q['acquisition_origin']='retained_legacy_web'; q['retained_label_basis']='legacy_annotation_not_reclassified'
        q['benchmark_status']='draft_not_frozen';q['lineage']['retained_from_sha256']=digest
        cleaned.append(q)
    jsonl(OUT/'retained/questions.jsonl',cleaned)
    cells=Counter((q['grade'],q['module']) for q in retired)
    config={'version':'web-rebuild-v0.2','created_at':site.stamp(),'seed':'EduMathBench-web-20261022-v0.2',
      'retained_count':363,'new_public_target':1137,'public_target':1500,'variant_target':300,
      'cells':[{'grade':g,'module':m,'new_target':n} for (g,m),n in sorted(cells.items())],
      'new_difficulty_targets':dict(Counter(q['difficulty'] for q in retired)),
      'protected_dev_ids':protected_dev,'protected_debug_ids':protected_debug,
      'models_in_acquisition':False,'variants_generation':'current_assistant_pending_review',
      'solutions_requested':False,'archive_output':False,'candidate_budget':2000,'additional_round_limit':500}
    dump(OUT/'rebuild_config.json',config)
    dump(lock,{'source_path':str(baseline.relative_to(ROOT)),'sha256':digest,'created_at':site.stamp(),
               'retained':363,'retired_public':1137,'retired_variants':300,'baseline_mutated':False})
    db().close()

def cached_fetch(url, platform, collector, con, force=False):
    row=con.execute('SELECT raw_path,state FROM pages WHERE url=?',(url,)).fetchone()
    if row and row[1]=='saved' and not force:
        path=OUT/row[0]
        if path.exists():return path.read_bytes(), path
    filename=hashlib.sha256(url.encode()).hexdigest()[:20]+'.html'
    path=OUT/'raw'/platform/filename
    try:
        data=collector.fetch(url,path)
        con.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?)',
                    (url,platform,path.relative_to(OUT).as_posix(),sha(path),'saved',site.stamp(),''))
        con.commit();return data,path
    except Exception as exc:
        con.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?)',
                    (url,platform,'','','failed',site.stamp(),str(exc)));con.commit();raise

def probe():
    tasks=json.loads((ROOT/'scripts/site_crawler/tasks.json').read_text(encoding='utf-8'))['tasks']
    con=db(); collector=site.HttpCollector(OUT,delay=2,timeout=20); result=[]
    for task in tasks:
        entry={'site':task['site'],'url':task['url'],'checked_at':site.stamp()}
        try:
            data,path=cached_fetch(task['url'],task['site'],collector,con)
            tree=html.fromstring(site.decode_html(data))
            selector={'tiku':'q-detail','21cnjy':'QuestionView','chujuan':'QuestionView','jyeoo':'QUES_LI'}[task['site']]
            roots=site.nodes(tree,selector);text=' '.join(tree.itertext())
            entry.update(raw_path=path.relative_to(OUT).as_posix(),sha256=sha(path),cards=len(roots),
                         title=''.join(tree.xpath('//title/text()')),
                         state='list_accessible' if roots else 'login_or_dynamic_or_changed',
                         access_gate=bool(site.GATES.search(text)),acceptance='not_yet_qualified')
            links=[]
            for a in tree.xpath('//a[@href]'):
                href=urljoin(task['url'],a.get('href'))
                if re.search(r'/question/detail/|/math/ques/detail/',href) and href not in links:links.append(href)
            entry['detail_links']=links[:20]
        except Exception as exc:entry.update(state='network_error',error=str(exc),acceptance='not_qualified')
        result.append(entry);print(json.dumps(entry,ensure_ascii=False),flush=True)
    jsonl(OUT/'reports/probe_events.jsonl',collector.requests)
    dump(OUT/'reports/site_probe.json',result);con.close()

SECTION_GRADES={
 '有理数':7,'无理数与实数':7,'代数式':7,'整式':8,'因式分解':8,'分式':8,'二次根式':8,
 '一元一次方程':7,'二元一次方程组':7,'一元二次方程':9,'分式方程':8,'不等式与不等式组':7,
 '函数基础知识':8,'一次函数':8,'反比例函数':9,'二次函数':9,
 '图形认识初步':7,'相交线与平行线':7,'三角形':8,'四边形':8,'圆':9,
 '图形的对称':8,'图形的平移':7,'图形的旋转':9,'图形的相似':9,'锐角三角函数':9,'投影与视图':9,
 '数据收集与处理':7,'数据分析':8,'概率':9}

def discover():
    con=db();col=site.HttpCollector(OUT,delay=2,timeout=20)
    task=next(t for t in json.loads((ROOT/'scripts/site_crawler/tasks.json').read_text(encoding='utf-8'))['tasks'] if t['site']=='tiku')
    data,path=cached_fetch(task['url'],'tiku',col,con)
    tree=html.fromstring(site.decode_html(data));leaves=[];excluded=[]
    for a in tree.xpath('//a[starts-with(normalize-space(@onclick),"tourl") and contains(@onclick,"thirdknowid")]'):
        match=re.search(r"tourl\(\s*(\d+)\s*,\s*'thirdknowid'",a.get('onclick',''))
        if not match:continue
        dl=a.xpath('ancestor::dl[1]');li=a.xpath('ancestor::li[1]')
        section=site.clean(''.join(dl[0].xpath('./dt//text()'))) if dl else ''
        major=site.clean(''.join(li[0].xpath('./a[1]//text()'))) if li else ''
        source_major=major
        if major in {'图形的性质','图形的变化'}:major='几何'
        label=site.clean(''.join(a.itertext()));kid=int(match[1]);grade=SECTION_GRADES.get(section)
        if section=='整式' and kid<701187:grade=7
        if section=='三角形' and kid<=701592:grade=7
        item={'site':'tiku','knowledge_id':kid,'knowledge':label,'section':section,'module':major,'source_module':source_major,'grade':grade,
              'knowledge_path':[major,section,label],'tree_raw_path':path.relative_to(OUT).as_posix(),
              'classification_basis':'fixed_curriculum_section_mapping_v1_provisional',
              'knowledge_id_evidence':'observed_tourl_control_in_source_html'}
        if grade is None or '计算器' in label or major not in {'数与式','方程与不等式','函数','几何','统计与概率'}:
            excluded.append(item)
        else:leaves.append(item)
    dump(OUT/'knowledge/tiku_tree.json',{'leaves':leaves,'excluded_pending_mapping':excluded,
       'source_url':task['url'],'source_sha256':sha(path),'source_checked_at':site.stamp(),
       'note':'固定知识点映射，不通过模型逐题判年级；教材版本暂定，不声称官方校准。'})
    con.close();print(json.dumps({'mapped_leaves':len(leaves),'excluded_leaves':len(excluded)},ensure_ascii=False))
    return leaves

def rank(value):return hashlib.sha256(('EduMathBench-web-20261022|'+str(value)).encode()).hexdigest()

def make_jobs():
    kp=OUT/'knowledge/tiku_tree.json'
    leaves=json.loads(kp.read_text(encoding='utf-8'))['leaves'] if kp.exists() else discover()
    cells=json.loads((OUT/'rebuild_config.json').read_text(encoding='utf-8'))['cells']
    groups={(x['grade'],x['module']):[] for x in cells}
    for leaf in leaves:
        if (leaf['grade'],leaf['module']) in groups:groups[(leaf['grade'],leaf['module'])].append(leaf)
    for group in groups.values():group.sort(key=lambda x:rank(x['knowledge_id']))
    jobs=[]
    for cycle in range(max(len(x) for x in groups.values())*3):
        for cell in sorted(cells,key=lambda x:rank((x['grade'],x['module']))):
            group=groups[(cell['grade'],cell['module'])];index=cycle//3
            if index>=len(group):continue
            leaf=group[index];diffid=cycle%3
            params={'cid':10,'cno':2,'thirdknowid':leaf['knowledge_id'],'diffid':diffid,'typeid':600012}
            jobs.append({'site':'tiku','url':'https://www.tiku.cn/knowledgeq?'+urlencode(params),
                         'filters':{**leaf,'type':'单选题','difficulty':['易','中','难'][diffid],
                                    'source':None,'source_filter_supported':False},'target':cell['new_target']})
    dump(OUT/'knowledge/jobs.json',jobs)
    return jobs

def preserve_assets(record,collector):
    evidence=[]
    for asset in record['image_assets']:
        if asset['role']=='solution':continue
        key=asset['asset_id'];folder=OUT/'assets/source';folder.mkdir(parents=True,exist_ok=True)
        matches=list(folder.glob(key+'.*'))
        try:
            if matches:target=matches[0]
            else:
                target=folder/(key+'.download')
                data=collector.fetch(asset['url'],target)
                if b'<svg' in data[:3000]:extension='.svg'
                else:
                    from PIL import Image
                    import io
                    image=Image.open(io.BytesIO(data));image.verify()
                    extension={ 'JPEG':'.jpg','PNG':'.png','GIF':'.gif','WEBP':'.webp'}.get(image.format,'.bin')
                final=target.with_suffix(extension);target.rename(final);target=final
            if target.suffix=='.download':raise ValueError('未验证的图片下载')
            asset.update(download_status='saved',local_path=target.relative_to(OUT).as_posix(),sha256=sha(target))
            if asset['role']=='answer' and not record['answer']:
                from answer_ocr import recognize
                ocr=recognize(target);record['answer_ocr']=ocr
                if ocr['accepted']:
                    record['answer']=ocr['answer'];record['answer_format']='text';record['answer_access']='source_image_local_ocr'
        except Exception as exc:asset.update(download_status='failed',error=str(exc))
        evidence.append(asset)
    record['image_assets']=evidence

def downloaded_fields(asset):
    """File cache metadata never owns an occurrence's semantic role or URL."""
    return {k:asset[k] for k in ('local_path','download_status','sha256','error') if k in asset}

def normalize_record(record,filters,raw_path,source_sha):
    r=site.answer_only(record)
    r.update(id=f'EMB-P-WEB2-{r["source_platform"].upper()}-{r["source_question_id"]}',
             grade=filters['grade'],module=filters['module'],knowledge_path=filters['knowledge_path'],
             source_type='public',parent_id='',family_id='',split='',debug_subset=False,
             collection_method='http_crawler',acquisition_origin='new_web_crawl',
             crawl_run_id='web-rebuild-20261022-v0.2',status='needs_review',benchmark_status='draft_not_frozen',
             raw_path=raw_path.relative_to(OUT).as_posix(),raw_sha256=source_sha,
             difficulty_annotation={'reason':'网站难度筛选原标签的固定映射，未按学生数据校准','method':'source_filter_mapping'},
             classification_basis=filters['classification_basis'],format_version='benchmark-format-v0.2-web',
             additional_sources=[],generation_metadata={},change_description='')
    r['source']={'id':f'SRC-WEB2-{r["source_platform"]}', 'title':r['source_title'] or r['source_site']+'知识点题库',
       'url':r['source_url'],'reference':r['source_question_id'],'answer_location':'原站答案区域',
       'raw_path':str(raw_path.relative_to(ROOT)),'accessed_at':r['collected_at'],'material_year':None,
       'region':None,'access_status':'http_collected','reuse_status':'unknown','notes':'原题与答案由程序提取；未采集解析。',
       'relation':'public_origin'}
    fields={'question':r['question'],**{'option_'+k.lower():v for k,v in r['options'].items()}}
    r['source_input']=fields.copy()
    from question_format import normalize_text
    for field,value in fields.items():
        value,_=normalize_text(value)
        value=value.replace('﹣','-').replace('−','-')
        value=re.sub(r'\$([^$]*)\$',lambda m:'$'+m[1].replace('□',r'\square ')+'$',value)
        if field=='question':r['question']=value
        else:r['options'][field[-1].upper()]=value
    r['lineage']={'acquisition':'programmatic_http','raw_sha256':source_sha,'source_id':r['source_question_id']}
    return r

def rejection_reasons(r, require_assets=True, allow_pending_answer_image=False):
    flags=[]
    if not r.get('question') or set(r.get('options',{}))!=set('ABCD') or not all(r['options'].values()):flags.append('incomplete_four_options')
    pending_answer=allow_pending_answer_image and any(a['role']=='answer' for a in r.get('image_assets',[])) and 'answer_ocr' not in r
    if not re.fullmatch('[A-D]',r.get('answer','')) and not pending_answer:flags.append('source_answer_missing_or_unrecognized')
    if r.get('difficulty') not in {'基础','中等','困难'}:flags.append('source_difficulty_unmapped')
    combined=' '.join([r.get('question',''),*r.get('options',{}).values()])
    if re.search(r'\[公式待转换:|\[缺失图片\]|\ufffd|\x00',combined):flags.append('formula_or_encoding_unresolved')
    if any(re.search(r'[0-9a-zA-Z)}]\s*[+*/=<>-]\s*$',v) for v in r.get('options',{}).values()):
        flags.append('source_option_suspected_truncation')
    if re.search(r'=\s*[Oo](?![A-Za-z0-9_])',combined):flags.append('source_zero_letter_ambiguity')
    for a in r.get('image_assets',[]):
        if require_assets and a['role']!='solution' and a.get('download_status')!='saved':flags.append('required_image_not_saved')
    if r.get('answer_transcription'):flags.append('manual_answer_transcription_not_allowed')
    if r.get('format_validation',{}).get('passed') is False:flags.append('formula_render_validation_failed')
    # A figure reference with no input image can signal a lost diagram.
    if re.search(r'如图|图中|图所示',r.get('question','')) and not any(a['role']=='question' for a in r.get('image_assets',[])):
        flags.append('figure_reference_without_archived_input')
    return sorted(set(flags))

def crawl(budget):
    con=db();collector=site.HttpCollector(OUT,delay=1.5,timeout=20)
    jobs=make_jobs();added=0;errors=0;observations=[]
    for job in jobs:
        if added>=budget:break
        done=con.execute('SELECT state FROM jobs WHERE url=?',(job['url'],)).fetchone()
        if done and done[0]=='done':continue
        # Keep broad coverage instead of filling the candidate pool with one easy cell.
        current=con.execute('SELECT record FROM items WHERE site="tiku"').fetchall()
        cell_count=sum((x['grade'],x['module'])==(job['filters']['grade'],job['filters']['module']) for x in (json.loads(x[0]) for x in current))
        if cell_count>=math.ceil(job['target']*1.9):continue
        try:
            data,path=cached_fetch(job['url'],'tiku',collector,con)
            tree=html.fromstring(site.decode_html(data));roots=site.nodes(tree,'q-detail')
            if not roots:
                visible=copy.deepcopy(tree)
                for node in visible.xpath('//script|//style'):node.drop_tree()
                body_text=' '.join(visible.itertext())
                if '没有找到' in body_text or '暂无' in body_text or 'data-total="0"' in site.decode_html(data):
                    con.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',(job['url'],'done',0,site.stamp()));con.commit()
                    print(json.dumps({'knowledge':job['filters']['knowledge'],'status':'no_results'},ensure_ascii=False),flush=True)
                    continue
                raise ValueError('没有题目节点：可能需登录或页面结构变化')
            saved=0
            for root in roots:
                if added>=budget:break
                try:
                    markup=html.tostring(root,encoding='unicode')
                    parsed=site.parse_question('tiku',markup,job['url'],job['filters'],path)
                    if con.execute('SELECT 1 FROM items WHERE site=? AND native_id=?',('tiku',parsed['source_question_id'])).fetchone():continue
                    raw=OUT/'raw/tiku/questions'/f'{parsed["source_question_id"]}.html';raw.parent.mkdir(parents=True,exist_ok=True)
                    raw.write_text(markup,encoding='utf-8')
                    record=normalize_record(parsed,job['filters'],raw,sha(raw))
                    record['assets_policy']='download_after_quota_preselection'
                    record['automatic_rejection_reasons']=rejection_reasons(record)
                    record['status']='auto_checked' if not record['automatic_rejection_reasons'] else 'needs_review'
                    con.execute('INSERT INTO items VALUES (?,?,?)',('tiku',parsed['source_question_id'],json.dumps(record,ensure_ascii=False)))
                    con.commit();added+=1;saved+=1
                except Exception as exc:observations.append({'url':job['url'],'status':'question_error','error':str(exc)})
            con.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',(job['url'],'done',saved,site.stamp()));con.commit();errors=0
            print(json.dumps({'added':added,'knowledge':job['filters']['knowledge'],'grade':job['filters']['grade'],'module':job['filters']['module'],'difficulty':job['filters']['difficulty'],'new_on_page':saved},ensure_ascii=False),flush=True)
            if added and added%50<10:status(con)
        except Exception as exc:
            errors+=1;observations.append({'url':job['url'],'status':'page_error','error':str(exc)})
            con.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',(job['url'],'failed',0,site.stamp()));con.commit()
            print(json.dumps(observations[-1],ensure_ascii=False),flush=True)
            if errors>=3:break
    previous=read(OUT/'reports/crawl_events.jsonl') if (OUT/'reports/crawl_events.jsonl').exists() else []
    jsonl(OUT/'reports/crawl_events.jsonl',previous+collector.requests+observations)
    status(con);con.close()

def status(con=None):
    own=con is None
    if own:con=db()
    rows=[json.loads(x[0]) for x in con.execute('SELECT record FROM items ORDER BY site,native_id')]
    accepted=[q for q in rows if not rejection_reasons(q)];held=[q for q in rows if rejection_reasons(q)]
    potential=[q for q in rows if not rejection_reasons(q,require_assets=False,allow_pending_answer_image=True)]
    jsonl(OUT/'candidates/questions.jsonl',rows);jsonl(OUT/'candidates/eligible.jsonl',accepted);jsonl(OUT/'candidates/deferred.jsonl',held)
    summary={'updated_at':site.stamp(),'retained':363,'new_candidate_count':len(rows),'new_eligible_before_dedup':len(accepted),
       'new_deferred_or_assets_pending':len(held),'potential_before_assets':len(potential),'target_new':1137,'old_variant_count_reused':0,
       'difficulty':dict(Counter(q['difficulty'] for q in accepted)),
       'cells':[{'grade':g,'module':m,'eligible':n} for (g,m),n in sorted(Counter((q['grade'],q['module']) for q in accepted).items())],
       'deferred_reasons':dict(Counter(reason for q in held for reason in rejection_reasons(q))),
       'models_in_acquisition':False,'phase':'candidate_pool_snapshot',
       'new_variant_count':len(read(OUT/'variants/questions.jsonl')) if (OUT/'variants/questions.jsonl').exists() else 0}
    dump(OUT/'reports/progress.json',summary)
    if own:con.close()
    return summary

def import_browser():
    path=OUT/'browser_capture/manifest.json'
    manifest=json.loads(path.read_text(encoding='utf-8'));con=db();results=[]
    for item in manifest['items']:
        raw=path.parent/item['raw_path'];filters={**item['filters'],'classification_basis':'observed_knowledge_filter_mapping_v1_provisional'}
        filters.setdefault('knowledge_path',[filters['module'],filters['knowledge']])
        try:
            parsed=site.parse_question(item['site'],raw.read_text(encoding='utf-8'),item['url'],filters,raw,item.get('listing'))
            r=normalize_record(parsed,filters,raw,sha(raw));r['collection_method']='playwright_browser_crawler'
            r['lineage']['acquisition']='programmatic_logged_in_browser'
            r['source']['access_status']='normal_logged_in_browser'
            previous=con.execute('SELECT record FROM items WHERE site=? AND native_id=?',(item['site'],r['source_question_id'])).fetchone()
            if previous:
                previous=json.loads(previous[0]);assets={a['asset_id']:a for a in previous['image_assets']}
                for asset in r['image_assets']:
                    old=assets.get(asset['asset_id'])
                    if old and old.get('download_status')=='saved':asset.update(downloaded_fields(old))
                ocr=previous.get('answer_ocr')
                if ocr and ocr.get('accepted') and any(a.get('sha256')==ocr['image_sha256'] for a in r['image_assets'] if a['role']=='answer'):
                    r['answer_ocr']=ocr;r['answer']=ocr['answer'];r['answer_format']='text';r['answer_access']='source_image_local_ocr'
                elif ocr and ocr.get('preprocess_version')=='answer-crop-v2':r['answer_ocr']=ocr
            r['automatic_rejection_reasons']=rejection_reasons(r)
            con.execute('INSERT OR REPLACE INTO items VALUES (?,?,?)',(item['site'],r['source_question_id'],json.dumps(r,ensure_ascii=False)))
            con.commit();results.append({'site':item['site'],'id':r['id'],'status':'imported','source_answer_format':r['source_answer_format']})
        except Exception as exc:results.append({'site':item['site'],'raw_path':str(raw),'status':'parse_error','error':str(exc)})
    dump(OUT/'reports/browser_import.json',results);status(con);con.close()
    print(json.dumps(dict(Counter(x['status'] for x in results)),ensure_ascii=False))

def reparse():
    """Re-run the pure parser over archived sources, preserving verified image files."""
    con=db();rows=[json.loads(x[0]) for x in con.execute('SELECT record FROM items')];errors=[]
    for old in rows:
        try:
            raw=OUT/old['raw_path'];filters=old['filters_requested']
            filters.setdefault('classification_basis',old['classification_basis'])
            parsed=site.parse_question(old['source_platform'],raw.read_text(encoding='utf-8'),old['source_url'],filters,raw)
            q=normalize_record(parsed,filters,raw,sha(raw));q['collected_at']=old['collected_at']
            q['source']['accessed_at']=old['source']['accessed_at']
            q['collection_method']=old['collection_method'];q['lineage']['acquisition']=old['lineage']['acquisition']
            if q['collection_method']=='playwright_browser_crawler':q['source']['access_status']='normal_logged_in_browser'
            known={a['asset_id']:a for a in old['image_assets']}
            for a in q['image_assets']:
                previous=known.get(a['asset_id'])
                if previous and previous.get('download_status')=='saved':a.update(downloaded_fields(previous))
            ocr=old.get('answer_ocr')
            if ocr and ocr.get('accepted') and any(a.get('sha256')==ocr['image_sha256'] for a in q['image_assets'] if a['role']=='answer'):
                q['answer_ocr']=ocr;q['answer']=ocr['answer'];q['answer_format']='text';q['answer_access']='source_image_local_ocr'
            elif ocr and ocr.get('preprocess_version')=='answer-crop-v2':q['answer_ocr']=ocr
            q['automatic_rejection_reasons']=rejection_reasons(q);q['status']='auto_checked' if not q['automatic_rejection_reasons'] else 'needs_review'
            con.execute('UPDATE items SET record=? WHERE site=? AND native_id=?',(json.dumps(q,ensure_ascii=False),q['source_platform'],q['source_question_id']))
        except Exception as exc:errors.append({'id':old['id'],'error':str(exc)})
    con.commit();status(con);con.close();dump(OUT/'reports/reparse.json',{'count':len(rows),'errors':errors,'parser_version':'web-parser-v2'});print(json.dumps({'reparsed':len(rows),'errors':len(errors)}))

def canonical_content(q,value):
    # Different source URLs may contain identical formula pixels. Once archived,
    # content hashes are a stronger identity than the source-specific placeholder.
    images={a.get('placeholder','[图片:'+a.get('asset_id','')+']'):a['sha256'] for a in q.get('image_assets',[]) if a.get('sha256') and a.get('role') not in ('answer','solution')}
    for token,digest in images.items():value=value.replace(token,'[sha256:'+digest+']')
    return site.canonical(value)

def identity(q):
    return hashlib.sha256((canonical_content(q,q['question'])+json.dumps(sorted(canonical_content(q,x) for x in q['options'].values()),ensure_ascii=False)).encode()).hexdigest()

class Flow:
    def __init__(self):self.g={}
    def edge(self,a,b,cap):
        self.g.setdefault(a,[]);self.g.setdefault(b,[])
        forward=[b,cap,len(self.g[b]),cap];back=[a,0,len(self.g[a]),0]
        self.g[a].append(forward);self.g[b].append(back);return forward
    def run(self,s,t):
        from collections import deque
        total=0
        while True:
            levels={s:0};queue=deque([s])
            while queue:
                a=queue.popleft()
                for b,c,*_ in self.g[a]:
                    if c and b not in levels:levels[b]=levels[a]+1;queue.append(b)
            if t not in levels:return total
            position={a:0 for a in self.g}
            def push(a,n):
                if a==t:return n
                while position[a]<len(self.g[a]):
                    e=self.g[a][position[a]];b,c,rev,_=e
                    if c and levels.get(b)==levels[a]+1:
                        f=push(b,min(n,c))
                        if f:e[1]-=f;self.g[b][rev][1]+=f;return f
                    position[a]+=1
                return 0
            while True:
                f=push(s,10**9)
                if not f:break
                total+=f

def select(ready_only=False,write=True,records=None):
    if records is None:
        con=db();rows=[json.loads(x[0]) for x in con.execute('SELECT record FROM items')];con.close()
    else:rows=copy.deepcopy(records)
    cfg=json.loads((OUT/'rebuild_config.json').read_text(encoding='utf-8'))
    qualification=OUT/'reports/site_qualification.json'
    assert qualification.exists(),'先运行qualify确认题源验收结果'
    allowed={x['site'] for x in json.loads(qualification.read_text(encoding='utf-8')) if x['qualified']}
    retained=read(OUT/'retained/questions.jsonl');owners={identity(q):q for q in retained};pool=[];duplicates=[]
    def preference(q):
        images=sum(a['role']=='question' or a['role'].startswith('option') for a in q['image_assets'])
        return (images,bool(rejection_reasons(q)),rank(q['id']))
    for q in sorted(rows,key=preference):
        if q['source_platform'] not in allowed:continue
        if ready_only and rejection_reasons(q):continue
        if rejection_reasons(q,require_assets=False,allow_pending_answer_image=True):continue
        key=identity(q)
        if key in owners:
            primary=owners[key]
            agree=canonical_content(primary,primary['options'][primary['answer']])==canonical_content(q,q['options'][q['answer']]) if q['answer'] and primary['answer'] else None
            duplicates.append({'id':q['id'],'same_as':primary['id'],'answer_content_agrees':agree,'source':q['source']})
            if agree is not False:primary.setdefault('additional_sources',[]).append(q['source'])
            else:primary.setdefault('risk_flags',[]).append('cross_source_answer_conflict')
            continue
        owners[key]=q;pool.append(q)
    # Do not choose either side of a detected source-answer conflict.
    pool=[q for q in pool if 'cross_source_answer_conflict' not in q['risk_flags']]
    groups={};f=Flow();edges={};target={}
    for cell in cfg['cells']:
        k=(cell['grade'],cell['module']);name=str(k);target[k]=cell['new_target'];f.edge('start',name,cell['new_target'])
        for d in cfg['new_difficulty_targets']:
            group=[q for q in pool if (q['grade'],q['module'],q['difficulty'])==(*k,d)]
            group.sort(key=preference);groups[(k,d)]=group;edges[(k,d)]=f.edge(name,d,len(group))
    for d,n in cfg['new_difficulty_targets'].items():f.edge(d,'finish',n)
    count=f.run('start','finish');chosen=[]
    for key,e in edges.items():chosen.extend(groups[key][:e[3]-e[1]])
    chosen.sort(key=lambda q:q['id'])
    if write:
        jsonl(OUT/'selected/new_questions.jsonl',chosen);jsonl(OUT/'reports/new_duplicates.jsonl',duplicates)
    got=Counter((q['grade'],q['module']) for q in chosen)
    report={'checked_at':site.stamp(),'selected_new':count,'target_new':1137,'quotas_complete':count==1137,
      'selected_with_assets_ready':sum(not rejection_reasons(q) for q in chosen),
      'difficulty':dict(Counter(q['difficulty'] for q in chosen)),
      'gaps':[{'grade':g,'module':m,'needed':n,'selected':got[(g,m)],'gap':n-got[(g,m)]} for (g,m),n in target.items()],
      'by_site':dict(Counter(q['source_platform'] for q in chosen)),'duplicate_records':len(duplicates),
      'ready_only':ready_only,'meaning':'配额预选不等于入库；必要图片保存及OCR必须随后通过。'}
    if write:
        dump(OUT/'reports/selection.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))
    return chosen

def materialize(records_path=None):
    from concurrent.futures import ThreadPoolExecutor,as_completed
    import threading
    records_path=Path(records_path) if records_path else OUT/'selected/new_questions.jsonl'
    rows=read(records_path)
    assets={a['asset_id']:a for q in rows for a in q['image_assets'] if a['role']!='solution'}
    lock=threading.Lock();slots={};results={};events=[]
    def one(asset):
        folder=OUT/'assets/source';folder.mkdir(parents=True,exist_ok=True)
        cached=[p for p in folder.glob(asset['asset_id']+'.*') if p.suffix!='.download']
        if cached:return {**asset,'local_path':cached[0].relative_to(OUT).as_posix(),'download_status':'saved','sha256':sha(cached[0])}
        host=urlparse(asset['url']).netloc
        with lock:
            now=time.monotonic();slot=max(now,slots.get(host,now));slots[host]=slot+0.5
        time.sleep(max(0,slot-time.monotonic()))
        collector=site.HttpCollector(OUT,delay=0,timeout=20);target=folder/(asset['asset_id']+'.download')
        try:
            data=collector.fetch(asset['url'],target)
            if b'<svg' in data[:3000]:suffix='.svg'
            else:
                import io
                from PIL import Image
                im=Image.open(io.BytesIO(data));im.verify();suffix={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp','GIF':'.gif'}.get(im.format,'.bin')
            final=target.with_suffix(suffix);target.rename(final)
            return {**asset,'local_path':final.relative_to(OUT).as_posix(),'download_status':'saved','sha256':sha(final)}
        except Exception as exc:return {**asset,'download_status':'failed','error':str(exc)}
        finally:
            with lock:events.extend(collector.requests)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures={executor.submit(one,a):k for k,a in assets.items()}
        for i,future in enumerate(as_completed(futures),1):
            results[futures[future]]=future.result()
            if i%50==0:print(json.dumps({'assets_completed':i,'assets_total':len(assets)}),flush=True)
    con=db()
    for q in rows:
        q['image_assets']=[{**a,**downloaded_fields(results[a['asset_id']])} if a['asset_id'] in results else a for a in q['image_assets']]
        for a in q['image_assets']:
            if a['role']=='answer' and not q['answer'] and a.get('download_status')=='saved':
                try:
                    from answer_ocr import recognize
                    q['answer_ocr']=recognize(OUT/a['local_path'])
                    if q['answer_ocr']['accepted']:
                        q['answer']=q['answer_ocr']['answer'];q['answer_format']='text';q['answer_access']='source_image_local_ocr'
                except Exception as exc:q['answer_ocr']={'accepted':False,'error':str(exc)}
        q['automatic_rejection_reasons']=rejection_reasons(q);q['status']='auto_checked' if not q['automatic_rejection_reasons'] else 'needs_review'
        con.execute('UPDATE items SET record=? WHERE site=? AND native_id=?',(json.dumps(q,ensure_ascii=False),q['source_platform'],q['source_question_id']))
    con.commit();con.close()
    jsonl(records_path,rows)
    previous=read(OUT/'reports/asset_events.jsonl') if (OUT/'reports/asset_events.jsonl').exists() else []
    jsonl(OUT/'reports/asset_events.jsonl',previous+events)
    print(json.dumps({'selected':len(rows),'assets':len(assets),'ready':sum(not rejection_reasons(q) for q in rows),'ocr_accepted':sum(q.get('answer_ocr',{}).get('accepted',False) for q in rows)},ensure_ascii=False));status()

def qualify():
    con=db();rows=[json.loads(x[0]) for x in con.execute('SELECT record FROM items')];con.close();results=[]
    for platform in site.SITES:
        subset=[q for q in rows if q['source_platform']==platform]
        ready=[q for q in subset if not rejection_reasons(q)]
        modules={q['module'] for q in ready}
        tested_image=any(any(a['role']=='question' and a.get('download_status')=='saved' for a in q['image_assets']) for q in ready)
        passed=len(ready)>=20 and len(modules)>=2 and (tested_image or any(q['difficulty']=='困难' for q in ready))
        access_limit=False
        for q in subset:
            if q['answer']:continue
            raw=OUT/q['raw_path']
            if raw.exists() and '今日查看试题解析数量已达上限' in raw.read_text(encoding='utf-8'):
                access_limit=True;break
        results.append({'site':platform,'candidate_unique':len(subset),'auto_checked_unique':len(ready),'modules':sorted(modules),
                        'input_image_preservation_tested':tested_image,'qualified':passed,
                        'access_limit_observed':access_limit,'pause_reason':'daily_answer_analysis_view_quota' if access_limit else None,
                        'meaning':'正常HTTP或专用登录浏览器独立程序实跑；数量不代表数学正确性或教师复核。'})
    dump(OUT/'reports/site_qualification.json',results);print(json.dumps(results,ensure_ascii=False,indent=2));return results

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['init','probe','discover','crawl','status','import-browser','select','assets','reparse','qualify'])
    parser.add_argument('--budget',type=int,default=2000)
    parser.add_argument('--records',type=Path)
    parser.add_argument('--ready-only',action='store_true')
    args=parser.parse_args();initialize()
    if args.command=='probe':probe()
    elif args.command=='discover':discover()
    elif args.command=='crawl':crawl(args.budget)
    elif args.command=='status':print(json.dumps(status(),ensure_ascii=False,indent=2))
    elif args.command=='import-browser':import_browser()
    elif args.command=='select':select(args.ready_only)
    elif args.command=='assets':materialize(args.records)
    elif args.command=='reparse':reparse()
    elif args.command=='qualify':qualify()
    else:print((OUT/'rebuild_config.json').read_text(encoding='utf-8'))

if __name__=='__main__':main()
