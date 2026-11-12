"""Prepare an immutable-input, family-isolated 1800-item research draft."""
from __future__ import annotations
import base64, copy, csv, hashlib, json, re, shutil, subprocess, unicodedata, zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/benchmark_draft'
SEED = 'EduMathBench-20261014-v0.2-public-dev'
REVISION_CONFIG = ROOT / 'config/split_policy_v0.2.json'
INPUTS = ['data/public_draft/questions.jsonl', 'data/normalized/questions.jsonl',
          'data/exports/EduMathBench_public_draft_v0.1.jsonl', 'data/variants/collection/questions.jsonl']
LEDGERS = ['data/reports/duplicates.jsonl', 'data/reports/presentation_duplicate_candidates.jsonl',
           'data/resolutions/round2_cleanup_duplicates.jsonl', 'data/resolutions/exact_source_duplicates.jsonl',
           'data/bulk_prepared/duplicate_groups.jsonl', 'data/mathbench_prepared/duplicate_groups.jsonl']

def read(p):
    return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def dump(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def jsonl(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(''.join(json.dumps(q, ensure_ascii=False)+'\n' for q in rows), encoding='utf-8')

def rank(key):
    return int(hashlib.sha256((SEED+'|'+key).encode()).hexdigest(), 16) / 2**256

def wording(s, numeric=False):
    s = unicodedata.normalize('NFKC', s).lower()
    s = re.sub(r'<[^>]+>', '', s).replace('$', '')
    s = re.sub(r'\\(?:left|right|quad|qquad)\b|\\[,;! ]', '', s)
    s = re.sub(r'\\(?:mathrm|textrm|text)\{([a-z0-9]+)\}', r'\1', s)
    if numeric:
        s = re.sub(r'(?<![a-z])\d+(?:\.\d+)?(?![a-z])', '<N>', s)
    return re.sub(r'\s+', '', s)

def graph(rows):
    ids = {q['id'] for q in rows}; parent = {i:i for i in ids}; edges=[]
    def find(i):
        parent.setdefault(i, i)
        if parent[i] != i: parent[i] = find(parent[i])
        return parent[i]
    def union(a, b, method, evidence):
        if not a or not b or a == b: return
        x,y=find(a),find(b)
        if x != y: parent[max(x,y)] = min(x,y)
        edges.append({'left_id':a,'right_id':b,'method':method,'evidence':evidence})
    existing=defaultdict(list); exact=defaultdict(list); templates=defaultdict(list)
    for q in rows:
        if q.get('parent_id'):
            assert q['parent_id'] in ids
            union(q['id'], q['parent_id'], 'parent_variant', 'parent_id')
        if q.get('family_id'): existing[q['family_id']].append(q['id'])
        # Labels and image hashes are intentionally excluded: differing labels or
        # diagrams must not allow same-wording candidates to cross the split.
        stem = wording(q['question'])
        exact[(stem, tuple(sorted(wording(q['options'][k]) for k in 'ABCD')))].append(q['id'])
        templates[(wording(q['question'], True), tuple(sorted(wording(q['options'][k], True) for k in 'ABCD')))].append(q['id'])
    for groups,method in [(existing,'existing_family'),(exact,'presentation_wording'),(templates,'numeric_template_candidate')]:
        for key,members in sorted(groups.items(), key=lambda x:str(x[0])):
            for i in members[1:]: union(members[0], i, method, str(key))
    for filename in LEDGERS:
        path=ROOT/filename
        if not path.exists(): continue
        for r in read(path):
            members = r.get('member_ids') or r.get('ids') or [r.get('primary_id'), r.get('id')]
            members = [i for i in members if i]
            for i in members[1:]: union(members[0], i, 'known_duplicate_ledger', filename)
    groups=defaultdict(list)
    for q in rows: groups[find(q['id'])].append(q)
    families=[]
    for members in groups.values():
        members=sorted(members,key=lambda q:q['id'])
        fid='EMB-F-'+hashlib.sha256('|'.join(q['id'] for q in members).encode()).hexdigest()[:20]
        families.append({'family_id':fid,'member_ids':[q['id'] for q in members],
                         'public_count':sum(q['source_type']=='public' for q in members),
                         'variant_count':sum(q['source_type']=='variant' for q in members),
                         'grades':sorted({q['grade'] for q in members})})
    return sorted(families,key=lambda f:f['family_id']), edges

def pick_single_families(pool, rows_by_id, count, dimensions, already):
    """Greedy stratification; only select a size that leaves a feasible remainder."""
    totals={d:Counter(q[d] for q in rows_by_id.values() if q['grade']==dimensions['grade']) for d in ['module','difficulty']}
    targets={d:{k:v*dimensions['total']/sum(c.values()) for k,v in c.items()} for d,c in totals.items()}
    observed={d:Counter(rows_by_id[i][d] for f in already for i in f['member_ids']) for d in targets}
    chosen=[];remaining=count
    def reachable(candidates, n):
        bits=1
        for f in candidates: bits |= bits << len(f['member_ids'])
        return bool((bits >> n)&1)
    assert reachable(pool, remaining), 'cannot fill family-isolated grade quota'
    while remaining:
        choices=[]
        for f in pool:
            size=len(f['member_ids'])
            if size>remaining: continue
            deficit=sum((targets[d].get(rows_by_id[i][d],0)-observed[d][rows_by_id[i][d]])/max(targets[d].get(rows_by_id[i][d],0),1)
                        for i in f['member_ids'] for d in targets)/size
            choices.append((-deficit, rank(f['family_id']), f))
        for _,__,f in sorted(choices, key=lambda x:(x[0],x[1])):
            rest=[x for x in pool if x is not f]
            if reachable(rest, remaining-len(f['member_ids'])):
                chosen.append(f);pool=rest;remaining-=len(f['member_ids'])
                for d in observed: observed[d].update(rows_by_id[i][d] for i in f['member_ids'])
                break
        else: raise AssertionError('unreachable quota')
    return chosen

def split_families(rows, families):
    byid={q['id']:q for q in rows};public_byid={i:q for i,q in byid.items() if q['source_type']=='public'};dev=[]
    revision=json.loads(REVISION_CONFIG.read_text(encoding='utf-8'))
    protected=set(revision['protected_dev_public_ids']);debug_protected=set(revision['protected_debug_public_ids'])
    assert protected<=set(public_byid) and debug_protected<=protected
    for grade in [7,8,9]:
        # A variant's entire connected family is ineligible for development,
        # including its public parent and any related public template records.
        public_pool=[f for f in families if f['grades']==[grade] and f['variant_count']==0]
        kept=[f for f in public_pool if set(f['member_ids'])&protected]
        assert all(set(f['member_ids'])<=protected for f in kept),'protected development family incomplete'
        n=sum(len(f['member_ids']) for f in kept);assert n<=50
        pool=[f for f in public_pool if f not in kept]
        dev.extend(kept+pick_single_families(pool,public_byid,50-n,{'grade':grade,'total':50},kept))
    devfamilies={f['family_id'] for f in dev}
    assignments={i:('dev' if f['family_id'] in devfamilies else 'test') for f in families for i in f['member_ids']}
    assert all(assignments[i]=='dev' for i in protected)
    assert all(assignments[q['id']]=='test' and assignments[q['parent_id']]=='test' for q in rows if q['source_type']=='variant')
    # The debugging subset also contains only public questions and whole families.
    debug=[]
    for grade,target in [(7,34),(8,33),(9,33)]:
        pool=[f for f in dev if f['grades']==[grade]]
        kept=[f for f in pool if set(f['member_ids'])&debug_protected]
        assert all(set(f['member_ids'])<=debug_protected for f in kept),'protected debug family incomplete'
        n=sum(len(f['member_ids']) for f in kept);assert n<=target
        debug.extend(kept+pick_single_families([f for f in pool if f not in kept],public_byid,target-n,{'grade':grade,'total':target},kept))
    return assignments, {i for f in debug for i in f['member_ids']}

def canonical(q, fid, split, debug):
    r=copy.deepcopy(q);oldsource=r['source'];r['upstream_family_id']=r.get('family_id','')
    if r['source_type']=='variant':
        p={a:oldsource.get(b,'') for a,b in [('id','source_id'),('title','source_title'),('url','source_url'),('reference','source_ref'),('raw_path','source_raw_path'),('accessed_at','source_accessed_at'),('reuse_status','source_reuse_status'),('notes','source_notes')]}
        p['relation']='generated_variant_of_public_parent';r['upstream_source']=oldsource
        r['source']=p
    else:r['source']['relation']='public_origin'
    for key in ['id','title','url','reference','answer_location','raw_path','accessed_at','material_year','region','access_status','reuse_status','notes']:
        r['source'].setdefault(key,'')
    r.setdefault('parent_id','');r.setdefault('solution','');r.setdefault('additional_sources',[])
    r.setdefault('change_description','');r.setdefault('generation_metadata',{})
    r['family_id']=fid;r['split']=split;r['debug_subset']=debug
    r['format_version']='benchmark-format-v0.1';r['benchmark_status']='draft_not_frozen'
    r['lineage']={'input_file':INPUTS[2 if r['source_type']=='public' else 3], 'input_id':r['id'],
                  'parent_id':r['parent_id'],'source_role':r['source']['relation']}
    return r

def model_input(q):
    # Explicit allowlist: no labels, family/split hints, parent, source, answer,
    # solution, arithmetic specification or generation metadata enters the input.
    result={k:q[k] for k in ['id','question','options','input_modality']}
    result['image_assets']=[{k:a[k] for k in ['path','sha256','role','placeholder_index','source_placeholder_field','alt'] if k in a} for a in q['image_assets']]
    return result

def build():
    before={p:sha(ROOT/p) for p in INPUTS};OUT.mkdir(parents=True,exist_ok=True)
    public=read(ROOT/INPUTS[2]);variants=read(ROOT/INPUTS[3]);rows=public+variants
    assert len(public)==1500 and len(variants)==300 and len({q['id'] for q in rows})==1800
    families,edges=graph(rows);assignments,debug=split_families(rows,families)
    family_by_id={i:f['family_id'] for f in families for i in f['member_ids']}
    rows=[canonical(q,family_by_id[q['id']],assignments[q['id']],q['id'] in debug) for q in rows]
    for q in rows:
        for a in q['image_assets']:
            src=ROOT/a['source_project_path'];dst=OUT/a['path']
            assert src.exists() and sha(src)==a['sha256'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    for f in families:f['split']=assignments[f['member_ids'][0]]
    jsonl(OUT/'questions.jsonl',rows);jsonl(OUT/'families.jsonl',families);jsonl(OUT/'family_edges.jsonl',edges)
    fields=['id','source_type','parent_id','family_id','split','debug_subset','grade','module','knowledge_point','difficulty','input_modality','question','option_a','option_b','option_c','option_d','answer','solution','change_description','source_title','source_url','source_ref','status','risk_flags','image_assets','generation_metadata','verification_note']
    with (OUT/'questions.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for q in rows:
            r={k:q.get(k,'') for k in fields};r.update({'option_'+k.lower():q['options'][k] for k in 'ABCD'})
            r.update(source_title=q['source'].get('title',''),source_url=q['source'].get('url',''),source_ref=q['source'].get('reference',''))
            for k in ['risk_flags','image_assets','generation_metadata','verification_note']:r[k]=json.dumps(r[k],ensure_ascii=False)
            w.writerow(r)
    for name,subset in [('dev',[q for q in rows if q['split']=='dev']),('test',[q for q in rows if q['split']=='test']),('debug100',[q for q in rows if q['debug_subset']])]:
        jsonl(OUT/'splits'/f'{name}.jsonl',subset);dump(OUT/'splits'/f'{name}_ids.json',[q['id'] for q in subset])
        # Inputs are side-by-side with the images directory, so relative asset paths resolve.
        jsonl(OUT/f'{name}_inputs.jsonl',[model_input(q) for q in subset])
        jsonl(OUT/f'{name}_answer_key.jsonl',[{'id':q['id'],'answer':q['answer'],'solution':q['solution']} for q in subset])
    stats={}
    for name in ['all','dev','test','debug100']:
        subset=[q for q in rows if name=='all' or (q['debug_subset'] if name=='debug100' else q['split']==name)]
        stats[name]={'total':len(subset),'source_types':dict(Counter(q['source_type'] for q in subset)),
                     'grades':dict(Counter(str(q['grade']) for q in subset)),
                     'difficulties':dict(Counter(q['difficulty'] for q in subset)),
                     'modalities':dict(Counter(q['input_modality'] for q in subset)),
                     'cells':[{ 'grade':g,'module':m,'difficulty':d,'count':n} for (g,m,d),n in sorted(Counter((q['grade'],q['module'],q['difficulty']) for q in subset).items())]}
    policy={'version':'split-policy-v0.2','seed':SEED,'algorithm':'family graph; variant-containing families test-only; retain eligible prior dev/debug public questions; deterministic module/difficulty deficit ranking; grade-balanced exact counts',
            'quotas':{'dev':{'public':150,'variant':0},'test':{'public':1350,'variant':300},'debug100':{'public':100,'variant':0}},
            'family_policy':['parent_id edges','existing family_id','known duplicate ledgers (including removed aliases)','wording with option order ignored','conservative numeric-template candidates; labels and diagrams excluded'],
            'grouping_scope':'Conservative automatic family separation, not exhaustive semantic duplicate certification. No question is deleted.',
            'debug_subset_policy':'100 public items from dev only, whole families; zero variants or variant parents; grades34/33/33',
            'variant_placement_policy':'Every variant and its entire connected parent family is test-only.',
            'revision_reason':'User requested no variants in development; overrides original mixed dev quota.',
            'revision_config_path':str(REVISION_CONFIG.relative_to(ROOT)).replace('\\','/'),
            'revision_config_sha256':sha(REVISION_CONFIG),
            'prior_policy_path':'data/split_history/split-policy-v0.1/split_policy.json',
            'prior_policy_sha256':sha(ROOT/'data/split_history/split-policy-v0.1/split_policy.json'),
            'test_usage_policy':'Do not tune prompts, develop parsers or select configurations on test.',
            'draft_not_frozen':True,'input_snapshots':before,'ledger_snapshots':{p:sha(ROOT/p) for p in LEDGERS if (ROOT/p).exists()}}
    dump(OUT/'split_policy.json',policy);dump(OUT/'statistics.json',stats)
    assert stats['dev']['source_types']=={'public':150}
    assert stats['test']['source_types']=={'public':1350,'variant':300} and stats['debug100']['source_types']=={'public':100}
    assert before=={p:sha(ROOT/p) for p in INPUTS},'upstream input mutation'
    report={'count':1800,'families':len(families),'multi_member_families':sum(len(f['member_ids'])>1 for f in families),
            'cross_grade_families':sum(len(f['grades'])>1 for f in families),'family_edges':len(edges),'source_snapshots':before,
            'split_statistics':stats,'final_approved':False,'browser_execution_verified':False}
    dump(ROOT/'data/reports/benchmark_draft_build.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ['source_snapshots','split_statistics']},ensure_ascii=False))
    print(json.dumps({k:{a:b for a,b in v.items() if a!='cells'} for k,v in stats.items()},ensure_ascii=False))
    return rows

def viewer(rows):
    from question_format import normalize_text
    displays={}
    for q in rows:
        value,rules=normalize_text(q['solution']) if q['source_type']=='public' else (q['solution'],[])
        if q['source_type']=='public' and '≌' in value:
            value=re.sub(r'(?<!\\)\$([^$]*)\$',lambda m:'$'+m[1].replace('≌',r'\cong ')+'$',value)
            rules.append('math_congruence_glyph_to_cong')
        displays[q['id']]={'text':value,'rules':rules,'status':'formatted',
                          'source_type':q['source_type'],'source_sha256':hashlib.sha256(q['solution'].encode()).hexdigest()}
    dump(OUT/'solution_display.json',displays)
    subprocess.run(['node',str(ROOT/'scripts/prepare_solution_display.cjs')],check=True,capture_output=True)
    displays=json.loads((OUT/'solution_display.json').read_text(encoding='utf-8'))
    assets=ROOT/'data/reports/visualization_assets';css=(assets/'katex.min.css').read_text(encoding='utf-8')
    def embed(m):return 'src:url(data:font/woff2;base64,'+base64.b64encode((assets/'fonts'/m[1]).read_bytes()).decode()+') format("woff2")}'
    css=re.sub(r'src:url\(fonts/([^)]*\.woff2)\) format\("woff2"\)[^}]*}',embed,css)
    data=copy.deepcopy(rows)
    for q in data:
        q['solution_display']=displays[q['id']]
        q['image_data']=[]
        for a in q['image_assets']:
            p=OUT/a['path'];mime={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png'}[p.suffix.lower()]
            q['image_data'].append({'alt':a.get('alt','原题配图'),'role':a.get('role','stem'),
                                    'field':a.get('source_placeholder_field','question'),'data_url':'data:'+mime+';base64,'+base64.b64encode(p.read_bytes()).decode()})
    page=(ROOT/'data/visualization/benchmark_template.html').read_text(encoding='utf-8')
    values={'__KATEX_CSS__':css,'__KATEX_JS__':(assets/'katex.min.js').read_text(encoding='utf-8'),
            '__AUTO_RENDER_JS__':(assets/'auto-render.min.js').read_text(encoding='utf-8'),
            '__CONTENT_JS__':(ROOT/'data/visualization/question_content.js').read_text(encoding='utf-8'),
            '__DATA__':json.dumps(data,ensure_ascii=False).replace('<','\\u003c')}
    for k,v in values.items():page=page.replace(k,v)
    assert 'url(fonts/' not in page
    (ROOT/'可视化/完整题库浏览.html').write_text(page,encoding='utf-8')
    shutil.copyfile(ROOT/'可视化/完整题库浏览.html',OUT/'完整题库浏览.html')

def package():
    shutil.copyfile(REVISION_CONFIG,OUT/'split_revision_config.json')
    shutil.copyfile(ROOT/'data/reports/visualization_assets/KaTeX-LICENSE.txt',OUT/'KaTeX-LICENSE.txt')
    for name in ['benchmark_draft_build.json','benchmark_draft_verify.json','benchmark_draft_presentation_check.json','split_revision_v0.2.json']:
        p=ROOT/'data/reports'/name
        if p.exists():shutil.copyfile(p,OUT/name)
    audit=ROOT/'data/reports/luna_split_audit/final_audit.json'
    if audit.exists():
        review=json.loads(audit.read_text(encoding='utf-8'))
        assert review['passed'] and not review['issues'],'independent audit unresolved'
        for name,meta in review['artifact_binding']['audited_file_sha256_and_bytes'].items():
            assert sha(ROOT/name)==meta['sha256'] and (ROOT/name).stat().st_size==meta['bytes'],'audit binding stale'
        shutil.copyfile(audit,OUT/'luna_split_audit.json')
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='manifest.json')
    dump(OUT/'manifest.json',{'format_version':'benchmark-format-v0.1','draft_not_frozen':True,
         'files':{p.relative_to(OUT).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size} for p in files}})
    zpath=ROOT/'data/exports/EduMathBench_1800_draft_v0.1.zip'
    with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(OUT).as_posix())
    with zipfile.ZipFile(zpath) as z:assert z.testzip() is None
    print(json.dumps({'zip':str(zpath),'bytes':zpath.stat().st_size,'sha256':sha(zpath)}))

if __name__=='__main__':
    import sys
    if '--package' in sys.argv:package()
    else:viewer(build())
