"""Deterministic member-feedback release; cached source selection and answer-free exports.

Preserve v0.2 and the submitted feedback. No LLM calls or new human review queue.
"""
import copy,csv,hashlib,json,re
from collections import Counter,defaultdict
from pathlib import Path
from question_format import normalize_text
from review_release_assets import export_assets,AssetValidationError
from review_quota_selector import select_public,QuotaSelectionError

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'data/benchmark_web_v0.2'
FEEDBACK=ROOT/'AI复核/反馈汇总_20261107/合并草稿/questions.jsonl'
REV=ROOT/'data/revisions_20261110'
OUT=ROOT/'data/benchmark_web_v0.3'
SEED='EduMathBench-member-reviewed-20261110-v0.3'
VERSION='benchmark-web-v0.3-member-reviewed'

def read(p):return [json.loads(x) for x in Path(p).read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def jsonl(p,x):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(y,ensure_ascii=False)+'\n' for y in x),encoding='utf-8')
def rank(x):return digest([SEED,x])
def norm(x):return re.sub(r'\s+','',str(x)).replace('－','-').replace('−','-')
def content_key(q):return digest([norm(q['question']),sorted(norm(x) for x in q['options'].values())])

def cache_canonical(item):
    q=copy.deepcopy(item);assets=[]
    for a in q.get('image_assets',[]):
        if a['role'] in {'answer','solution'}:continue
        field='question' if a['role']=='question' else 'option_'+a['role'].split('_')[-1].lower()
        assets.append({'path':a['local_path'],'sha256':a['sha256'],'role':'stem' if field=='question' else 'option','source_placeholder_field':field,'placeholder':'[图片:'+a['asset_id']+']','contains_answer_or_solution':False})
    q['image_assets']=assets
    q['source']={'id':'SRC-WEB2-'+q['source_platform'],'title':q.get('source_title') or q.get('source_site','网页题源'),'url':q['source_url'],'reference':q['source_question_id'],'raw_path':str((OLD/q['raw_path']).relative_to(ROOT)),'accessed_at':q.get('collected_at'),'answer_location':'原始网页答案区域','notes':'由既有爬虫缓存程序补入；未新增网络采集；未采集解析。','relation':'public_origin'}
    q.update(parent_id='',family_id='EMB-F-WEB3-'+digest(q['id'])[:16],split='',debug_subset=False,solution='',solution_format='not_requested',review_no=None)
    q['release_review']={'status':'program_checked_cached_replacement','member_review_claimed':False,'basis':'existing_source_html_and_answer_evidence','acquisition_date':q.get('collected_at')}
    return q

def prepare():
    original=read(OLD/'questions.jsonl');by={q['id']:q for q in original}
    corrections={q['id']:q for q in read(REV/'math_resolutions.jsonl')}
    excluded={x['id'] for x in corrections.values() if x['action']=='replace_required'}|{'EMB-P-WEB2-TIKU-1754116','EMB-P-WEB2-TIKU-3883004','EMB-P-WEB2-TIKU-1754093'}
    rows=[];edits=[];retired=[]
    for item in read(FEEDBACK):
        q=copy.deepcopy(by[item['question_id']]);q['review_no']=item['review_no']
        if q['id'] in excluded:
            reason=corrections.get(q['id'],{}).get('reason','非数学学科题：物理/生物')
            if q['id']=='EMB-P-WEB2-TIKU-1754093':reason='网页知识点错误混入：直线与圆的解析几何参数优化被放进七年级平行线距离节点，不适合作为本项目该节点题目；程序固定排除，不抬标签凑配额。'
            retired.append({'id':q['id'],'review_no':item['review_no'],'reason':reason,'original':q});continue
        for field in ['question','options','grade','module']:q[field]=copy.deepcopy(item[field])
        q['difficulty']=item['difficulty_provisional'];q['answer']=item['answer']
        fb=item['feedback'];proposal=fb['complete_review_proposal']
        # User explicitly confirms these submissions are member-reviewed versions.
        # Blank reasoning/foreign status names no longer trigger a new human review.
        if fb['selected_content_from']=='original_input' and fb['raw_correction_status'] in {'verified','unchanged','proposed'}:
            if proposal.get('answer') in list('ABCD'):
                for field in ['question','options','grade','module','answer']:q[field]=copy.deepcopy(proposal[field])
                q['difficulty']=proposal['difficulty_provisional']
        if q['id'] in corrections:
            resolution=corrections[q['id']]
            for field in ['question','options','answer','grade','module','difficulty']:
                if field in resolution:q[field]=copy.deepcopy(resolution[field])
            q['post_member_resolution']=resolution
        if q['review_no']==340:
            q['question']='已知点M(1-2m，m-1)关于x轴的对称点在第一象限，则m的取值范围是（ ）'
            q['post_member_resolution']={'reason':'四个数轴选项已由成员准确改为区间文字，去掉不再适用的“在数轴上表示”表述；保留唯一正确项C。'}
        if q['review_no']==1633:
            q['question']='在平面直角坐标系中，点A的坐标为(-4，-3)，将线段OA绕原点O顺时针旋转90°得到OA′，则点A′的坐标是（ ）'
            q['post_member_resolution']={'reason':'坐标与旋转方向已完整给出，删除冗余图示及旧图占位符，避免使用与新条件不一致的原图；答案B。'}
        if q['review_no']==1752:
            q['answer']='B'
            q['post_member_resolution']={'reason':'当前题干问三角形“边界上”，成员改答案C时使用了“内部含边界”的计数。按当前正文及有限枚举，边界有4个等可能点，共16个结果，概率1/4，正确项B。','evidence':'reports/current_variant_math.json','method':'finite_probability exact boundary predicate, 4/16'}
        if q['review_no']==1420:
            q['answer']='A'
            q['post_member_resolution']={'reason':'y=-x²向左1、向下3的平移函数为y=-(x+1)²-3，对应A；成员提交仍保留C，现按明确的平移规则修正。','method':'f_new(x)=f_old(x+1)-3; symbolic polynomial identity','correct_expression':'-(x+1)**2-3'}
        q['release_review']={'status':'member_reviewed_user_confirmed','confirmation_date':'2026-11-10','confirmation_basis':'user states submitted six parts are member-reviewed and requests no further human checks','reviewer_as_submitted':fb['reviewer_as_submitted'],'submitted_record':fb['file'],'submitted_verdict':fb['raw_verdict'],'automatic_resolution_applied':q['id'] in corrections,'generation_provenance_preserved':True}
        fmt=[]
        for field in ['question']:
            q[field],rules=normalize_text(q[field]);fmt.extend([field+':'+x for x in rules])
        for key in 'ABCD':q['options'][key],rules=normalize_text(q['options'][key]);fmt.extend(['option_'+key+':'+x for x in rules])
        q['format_rules_applied']=fmt
        q['solution']='';q['solution_format']='not_requested'
        if q['answer'] not in list('ABCD'):raise ValueError('Unresolved answer '+str(q['review_no']))
        if set(q['options'])!=set('ABCD') or len({norm(x) for x in q['options'].values()})<4:raise ValueError('Invalid options '+str(q['review_no']))
        fields=[k for k in ['question','options','answer','grade','module','difficulty'] if q[k]!=by[q['id']][k]]
        if fields:edits.append({'id':q['id'],'review_no':q['review_no'],'fields':fields,'before':{k:by[q['id']][k] for k in fields},'after':{k:q[k] for k in fields}})
        q['release_revision']=VERSION;q['format_version']='benchmark-format-v0.3';q['benchmark_status']='member_reviewed_program_revised'
        q['input_snapshot_before_member_review']=digest({k:by[q['id']][k] for k in ['question','options','answer']})
        rows.append(q)
    # Review normalization exposed a near-identical retained equation in protected
    # dev and an old test mother. Keep both source records on the dev family side;
    # genuinely re-author its one variant from another eligible test mother.
    by_current={q['id']:q for q in rows}
    variant=by_current['EMB-V-WEB2R2-G8-183'];mother=by_current['EMB-P-G8-000006']
    assert mother['id'] not in {q['parent_id'] for q in rows if q['source_type']=='variant'}
    predecessor={k:copy.deepcopy(variant[k]) for k in ['id','review_no','parent_id','question','options','answer','verification_spec']}
    variant.update(question='分式方程3/(x+4)=2/(x-2)的解是（ ）',options={'A':'x=-14','B':'x=14','C':'x=2','D':'x=-4'},answer='B',parent_id=mother['id'],grade=8,module='方程与不等式',difficulty='中等',knowledge_point=mother['knowledge_point'])
    variant['source']=copy.deepcopy(mother['source']);variant['source']['relation']='generated_variant_of_public_parent'
    variant['image_assets']=[]
    variant['verification_spec']={'kind':'equation_with_predicate','variable':'x','lhs':'3/(x+4)-2/(x-2)','condition':'x!=-4 and x!=2','option_exprs':{'A':'-14','B':'14','C':'2','D':'-4'}}
    variant['generation_metadata']={'agent':'current_assistant','model':'runtime_model_identifier_unavailable','generated_at':'2026-11-10','method':'assistant_authored_per_parent_leakage_repair','revision':'member-feedback-r3','parent_id':mother['id']}
    variant['release_review']={'status':'assistant_repaired_variant_program_verified','member_review_claimed':False,'basis':'new parent-specific revision to repair a protected-dev/test near-duplicate family collision'}
    variant['change_description']='母题2/(x+2)=1/(x-1)改为3/(x+4)=2/(x-2)，重新设置系数、平移量和干扰项，独立去分母验算并排除分母为零的值。'
    variant['post_member_resolution']={'reason':'原母题与受保护开发题在规范化后构成近重复题族，重新选取另一道测试侧母题并实际重写该变式，原生成稿保留以追溯。','derivation':'定义域x≠-4且x≠2；3(x-2)=2(x+4)，解得x=14，唯一正确项B。','predecessor':predecessor,'new_parent_snapshot':{k:copy.deepcopy(mother[k]) for k in ['id','question','options','answer']}}
    from verify_web_variant_math import check_spec
    answers,detail=check_spec(variant['verification_spec']);assert answers==['B']
    dump(OUT/'reports/variant_family_repair.json',variant['post_member_resolution']|{'new_variant_id':variant['id'],'program_check':detail})
    function_repairs=[]
    for ident in ['EMB-V-WEB2R2-G8-126','EMB-V-WEB2R2-G8-131']:
        q=by_current[ident];previous={k:copy.deepcopy(q[k]) for k in ['question','options','answer','grade','module','verification_spec']}
        if ident.endswith('126'):
            q.update(question='水箱原有42升水，以每分钟0.7升的速度匀速排水。排水t分钟后，余水量y（升）与t的函数关系及自变量取值范围正确的是（ ）',options={'A':'y=42-0.7t，0≤t≤60','B':'y=42-0.7t，0≤t≤42','C':'y=0.7t，0≤t≤60','D':'y=42+0.7t，0≤t≤60'},answer='A')
            q['verification_spec']={'kind':'draining_tank_affine_domain','initial':'42','rate':'7/10','options':{'A':{'expr':'42-7*t/10','lower':'0','upper':'60'},'B':{'expr':'42-7*t/10','lower':'0','upper':'42'},'C':{'expr':'7*t/10','lower':'0','upper':'60'},'D':{'expr':'42+7*t/10','lower':'0','upper':'60'}}}
        else:
            q.update(question='某人以每分钟75米的速度匀速步行，行走路程s（米）与时间t（分钟）的函数图象上，属于该图象的点(t，s)是（ ）',options={'A':'(6，450)','B':'(6，525)','C':'(8，525)','D':'(9，600)'},answer='A')
            q['verification_spec']={'kind':'statement_selection','target_truth':True,'statements':{'A':{'lhs':'450','op':'==','rhs':'75*6'},'B':{'lhs':'525','op':'==','rhs':'75*6'},'C':{'lhs':'525','op':'==','rhs':'75*8'},'D':{'lhs':'600','op':'==','rhs':'75*9'}}}
        q.update(grade=8,module='函数',difficulty='基础',image_assets=[])
        q['release_review']={'status':'assistant_repaired_variant_program_verified','member_review_claimed':False,'basis':'member correctly identified arithmetic-only scope; re-author as a real function task from the same mother'}
        q['generation_metadata']={'agent':'current_assistant','model':'runtime_model_identifier_unavailable','generated_at':'2026-11-10','method':'assistant_authored_function_scope_repair','revision':'member-feedback-r3','parent_id':q['parent_id']}
        q['change_description']='依据成员指出的知识范围偏移，保留母题情境和主要数量关系，改问完整函数关系/定义域或函数图象上的点，使题面实际考查八年级函数。'
        q['post_member_resolution']={'reason':q['change_description'],'predecessor':previous,'new_parent_snapshot':{k:copy.deepcopy(by_current[q['parent_id']][k]) for k in ['id','question','options','answer']}}
        answers,detail=check_spec(q['verification_spec']);assert answers==[q['answer']]
        function_repairs.append({'id':ident,'resolution':q['post_member_resolution'],'program_check':detail})
    dump(OUT/'reports/function_variant_repairs.json',function_repairs)
    # These retained text questions define the geometry completely. Remove stale
    # figure references when the original collection never contained a figure.
    self_contained={'EMB-P-WEB-G7GEOM-24772607-5','HC-G8-0001','EMB-P-WEB-FUNCTIONS-XJ2026-7','HC-G9-25572206-HARBIN','HC-G9-25572206-GUANGYUAN','HC-G9-25572206-SUIHUA'}
    for q in rows:
        if q['id'] in self_contained:
            q['question']=q['question'].replace('如图，','').replace('如图,','')
            q['text_completeness_note']='原收藏为完整条件文字题，移除不再对应附件的“如图”前缀；数学条件和选项未改。'
        if q['release_review']['status']=='assistant_repaired_variant_program_verified':
            q['prior_verification_note']=q.get('verification_note')
            if 'assistant_self_review' in q:q['prior_assistant_self_review']=q.pop('assistant_self_review')
            q['verification_note']={'scope':q['post_member_resolution'].get('derivation',q['change_description'])+'；当前显式数学规格的结果见reports/current_variant_math.json。','independent_member_review_of_new_revision_claimed':False}
    audit={q['id']:q for q in read(REV/'reserve_audit.jsonl')}
    pool=[];seen={content_key(q):q['id'] for q in rows};rejected=[]
    for item in sorted(read(OLD/'candidates/eligible.jsonl'),key=lambda q:rank(q['id'])):
        if item['id'] in by:continue
        if item['id'] not in audit or not audit[item['id']]['usable']:continue
        q=cache_canonical(item);key=content_key(q)
        if key in seen:rejected.append({'id':q['id'],'reason':'exact_content_duplicate','same_as':seen[key]});continue
        seen[key]=q['id'];pool.append(q)
    return original,rows,pool,retired,edits,rejected

def group_and_split(public,variants,old,config):
    allrows=public+variants;by={q['id']:q for q in allrows};parents={q['parent_id'] for q in variants}
    assert len(parents)==300 and parents<=set(by)
    # Preserve all known old families; join newly discovered exact/long numeric templates.
    uf={q['id']:q['id'] for q in public}
    def find(x):
        while uf[x]!=x:uf[x]=uf[uf[x]];x=uf[x]
        return x
    def union(x,y):
        a,b=find(x),find(y)
        if a!=b:uf[max(a,b)]=min(a,b)
    buckets=defaultdict(list)
    for q in public:
        buckets['prior:'+q['family_id']].append(q['id']);buckets['exact:'+content_key(q)].append(q['id'])
        if not q['image_assets']:
            template=re.sub(r'\d+(?:\.\d+)?','<N>',norm(q['question']))
            if len(template)>=35:buckets['template:'+template].append(q['id'])
    for values in buckets.values():
        for other in values[1:]:union(values[0],other)
    groups=defaultdict(list)
    for q in public:groups[find(q['id'])].append(q)
    for members in groups.values():
        fid='EMB-F-WEB3-'+digest(sorted(q['id'] for q in members))[:16]
        for q in members:q['prior_family_id']=q['family_id'];q['family_id']=fid
    for q in variants:q['prior_family_id']=q['family_id'];q['family_id']=by[q['parent_id']]['family_id']
    grouped=defaultdict(list)
    for q in public:grouped[q['family_id']].append(q)
    protected=set(config['protected_dev_ids']);debug_protected=set(config['protected_debug_ids'])
    forced={q['family_id'] for q in public if q['id'] in protected|debug_protected}
    forbidden={by[i]['family_id'] for i in parents}
    conflicts=forced&forbidden
    if conflicts:
        dump(OUT/'reports/family_conflicts.json',[{'family_id':fid,'members':[{'id':q['id'],'review_no':q['review_no'],'question':q['question'],'is_protected':q['id'] in protected|debug_protected,'is_mother':q['id'] in parents} for q in public if q['family_id']==fid]} for fid in conflicts])
        raise ValueError('Protected dev family joined a variant mother; see reports/family_conflicts.json')
    dump(OUT/'reports/family_conflicts.json',[])
    dev=[q for q in public if q['family_id'] in forced]
    for grade in [7,8,9]:
        need=50-sum(q['grade']==grade for q in dev);assert need>=0
        choices=[g for fid,g in grouped.items() if fid not in forced|forbidden and {q['grade'] for q in g}=={grade}]
        # Prefer previous dev families, preserving exposure boundaries where possible.
        choices.sort(key=lambda g:(not any(old.get(q['id'],{}).get('split')=='dev' for q in g),rank(g[0]['family_id'])))
        dp={0:[]}
        for group in choices:
            for count,chosen in sorted(list(dp.items()),reverse=True):
                if count+len(group)<=need and count+len(group) not in dp:dp[count+len(group)]=chosen+[group]
            if need in dp:break
        if need not in dp:raise ValueError('Cannot complete protected dev split for grade '+str(grade))
        for group in dp[need]:dev.extend(group);forced.add(group[0]['family_id'])
    debug=set(debug_protected)
    for q in sorted(dev,key=lambda q:(not old.get(q['id'],{}).get('debug_subset',False),rank(q['id']))):
        if len(debug)==100:break
        debug.add(q['id'])
    assert len(dev)==150 and len(debug)==100
    for q in allrows:q['split']='dev' if q['family_id'] in forced else 'test';q['debug_subset']=q['id'] in debug
    return allrows

def export(rows,meta):
    rows.sort(key=lambda q:(q['grade'],q['module'],q['source_type']=='variant',q['id']))
    for index,q in enumerate(rows,1):q['display_no']=index
    jsonl(OUT/'questions.jsonl',rows)
    cols=['display_no','review_no','id','source_type','grade','module','difficulty','question','option_a','option_b','option_c','option_d','answer','parent_id','family_id','split','debug_subset','source_url','release_review_status','record_json']
    with (OUT/'questions.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for q in rows:
            row={k:q.get(k,'') for k in cols};row.update({'option_'+k.lower():v for k,v in q['options'].items()});row.update(source_url=q['source']['url'],release_review_status=q['release_review']['status'],record_json=json.dumps(q,ensure_ascii=False));w.writerow(row)
    manifest={'version':VERSION,'status':'ready_for_development_pilot','created_date':'2026-11-10','seed':SEED,'inputs':{},'answers':{},'source_build':meta,'external_model_calls':0,'member_review_basis':'user-confirmed submitted versions; no new human review assigned','quota_status':'matched'}
    for split,pred in [('debug',lambda q:q['debug_subset']),('dev',lambda q:q['split']=='dev'),('test',lambda q:q['split']=='test'),('all',lambda q:True)]:
        subset=[q for q in rows if pred(q)];inputs=[];answers=[]
        for q in subset:
            inputs.append({k:copy.deepcopy(q[k]) for k in ['id','review_no','grade','module','difficulty','parent_id','family_id','question','options','image_assets','split']}|{'kind':q['source_type']})
            for asset in inputs[-1]['image_assets']:
                if asset['field'].startswith('option_'):asset['field']='options.'+asset['field'][-1].upper()
            answers.append({k:q[k] for k in ['id','answer']})
        ip=f'inputs/{split}_inputs.jsonl';ap=f'answers/{split}_answers.jsonl';jsonl(OUT/ip,inputs);jsonl(OUT/ap,answers)
        manifest['inputs'][split]={'path':ip,'sha256':sha(OUT/ip),'count':len(inputs)}
        manifest['answers'][split]={'path':ap,'sha256':sha(OUT/ap),'count':len(answers)}
        p=OUT/'splits'/f'{split}_ids.txt';p.parent.mkdir(exist_ok=True);p.write_text(''.join(q['id']+'\n' for q in subset),encoding='utf-8')
    manifest['questions_sha256']=sha(OUT/'questions.jsonl');manifest['csv_sha256']=sha(OUT/'questions.csv')
    dump(OUT/'manifest.json',manifest)
    stats={'count':len(rows),'kinds':dict(Counter(q['source_type'] for q in rows)),'grades':dict(Counter(q['grade'] for q in rows)),'original_grade_modules':[{'grade':g,'module':m,'count':v} for (g,m),v in sorted(Counter((q['grade'],q['module']) for q in rows if q['source_type']=='public').items())],'public_difficulty':dict(Counter(q['difficulty'] for q in rows if q['source_type']=='public')),'variant_difficulty':dict(Counter(q['difficulty'] for q in rows if q['source_type']=='variant')),'split':dict(Counter(q['split'] for q in rows)),'dev_grades':dict(Counter(q['grade'] for q in rows if q['split']=='dev')),'debug':sum(q['debug_subset'] for q in rows),'with_necessary_images':sum(bool(q['image_assets']) for q in rows),'asset_occurrences':sum(len(q['image_assets']) for q in rows),'review_basis':dict(Counter(q['release_review']['status'] for q in rows)),'acquisition':dict(Counter(q.get('acquisition_origin') for q in rows)),'all_mother_pairs_in_test':all(q['split']=='test' for q in rows if q['source_type']=='variant'),'whole_question_screenshots_used_as_inputs':0}
    dump(OUT/'statistics.json',stats);return manifest,stats

def build():
    source_sha=sha(OLD/'questions.jsonl');original,reviewed,reserves,retired,edits,duplicates=prepare();old={q['id']:q for q in original}
    public=[q for q in reviewed if q['source_type']=='public'];variants=[q for q in reviewed if q['source_type']=='variant'];assert len(variants)==300
    cfg=json.loads((OLD/'rebuild_config.json').read_text(encoding='utf-8'));quotas=json.loads((ROOT/'config/quotas.json').read_text(encoding='utf-8'))
    retained={q['id'] for q in original if q.get('acquisition_origin')=='retained_legacy_web'};parents={q['parent_id'] for q in variants}
    mandatory=retained|parents|set(cfg['protected_dev_ids'])|set(cfg['protected_debug_ids']);preferred={q['id'] for q in public}
    try:selected,selection=select_public(public+reserves,mandatory,quotas['cells'],quotas['difficulty_targets'],preferred,SEED)
    except QuotaSelectionError as e:dump(OUT/'reports/quota_deficit.json',e.deficit);raise
    added=[q for q in selected if q['id'] not in preferred];next_no=1801
    for q in sorted(added,key=lambda q:rank(q['id'])):q['review_no']=next_no;next_no+=1
    active={q['id'] for q in selected};retired.extend({'id':q['id'],'review_no':q['review_no'],'reason':'post-review truthful classification creates quota surplus; deterministic selector preserves parents and retained records','original':q} for q in public if q['id'] not in active)
    image_errors=[]
    for q in selected+variants:
        source=old.get(q['id'],q)
        try:
            q['image_assets']=export_assets(q,source,OUT)
            if not q['image_assets'] and re.search(r'如图|下图|图中|图所示|右图|左图',q['question']):
                stems=[dict(a,placeholder='') for a in source.get('image_assets',[]) if a.get('role') in {'stem','question'}]
                if stems:
                    q['image_assets']=export_assets(q,source,OUT,{'assets':stems})
                    q['asset_binding_note']='成员文字转写移除了占位符，但题干仍引用图示；将原题干图作为明确的补充图绑定，保留原图与摘要。'
                else:raise AssetValidationError('Figure reference remains without a recoverable original stem image')
            q['input_modality']='text_image' if q['image_assets'] else 'text'
            for index,asset in enumerate(q['image_assets']):
                if not asset['placeholder']:
                    marker='[图片:'+asset['sha256'][:16]+']';asset['placeholder']=marker
                    if asset['field']=='question':
                        if marker not in q['question']:q['question']+='\n'+marker
                    else:
                        letter=asset['field'][-1].upper()
                        if marker not in q['options'][letter]:q['options'][letter]+='\n'+marker
                    asset['binding_origin']='explicit_marker_for_original_unplaced_figure'
                asset['source_placeholder_field']=asset['field'];asset['placeholder_index']=index;asset['contains_answer_or_solution']=False
        except AssetValidationError as e:image_errors.append({'id':q['id'],'review_no':q['review_no'],'error':str(e)})
        q['benchmark_status']='member_reviewed_program_revised' if q['id'] in old else 'program_checked_cached_replacement'
        q['format_version']='benchmark-format-v0.3';q['release_revision']=VERSION
        q['previous_risk_flags']=q.get('risk_flags',[])
        stale={'math_review_pending','assistant_self_checked_user_review_pending','ocr_answer_pending_human_sample_check'}
        q['risk_flags']=[x for x in q.get('risk_flags',[]) if x not in stale]
    dump(OUT/'reports/asset_binding.json',{'passed':not image_errors,'errors':image_errors});assert not image_errors
    rows=group_and_split(selected,variants,old,cfg)
    jsonl(OUT/'history/retired_questions.jsonl',retired);jsonl(OUT/'history/revision_changes.jsonl',edits)
    jsonl(OUT/'history/added_cached_questions.jsonl',[{'id':q['id'],'review_no':q['review_no'],'source':q['source'],'basis':q['release_review']} for q in added])
    dump(OUT/'reports/selection.json',selection);dump(OUT/'reports/duplicate_cache_exclusions.json',duplicates)
    meta={'old_questions_sha256':source_sha,'feedback_sha256':sha(FEEDBACK),'math_resolutions_sha256':sha(REV/'math_resolutions.jsonl'),'reserve_audit_sha256':sha(REV/'reserve_audit.jsonl'),'added_from_existing_crawler_cache':len(added),'retired_reviewed_originals':len(retired),'retained_historical_count':len(retained),'new_live_web_crawl_requests_this_release':0,'llm_calls_in_processing':0,'mathematical_editorial_resolutions':len(read(REV/'math_resolutions.jsonl')),'protected_dev_ids':cfg['protected_dev_ids'],'protected_debug_ids':cfg['protected_debug_ids']}
    manifest,stats=export(rows,meta)
    assert sha(OLD/'questions.jsonl')==source_sha
    print(json.dumps({'built':len(rows),'added_cached':len(added),'retired':len(retired),'stats':stats},ensure_ascii=False))

if __name__=='__main__':build()
