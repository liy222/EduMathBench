"""Separate pilot exports and offline parent/variant browser; no public mutations."""
import base64
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
from verify_pilot_variants import main as verify

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/variants/pilot'
def read(path):return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
def writejson(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def build():
    check=verify()
    assert check['count']==check['passed']==30 and check['failed']==0, 'pilot constraints must pass'
    public=ROOT/'data/normalized/questions.jsonl';public_hash=digest(public)
    source={p['id']:p for p in read(public)}
    parents=read(ROOT/'data/variants/parents/parents_300.jsonl');mapping={p['id']:p for p in parents}
    assert len(mapping)==len(parents)==300
    config=json.loads((ROOT/'config/variant_quotas.json').read_text(encoding='utf-8'))
    cells=Counter((int(p['grade']),p['module'],p['difficulty']) for p in parents)
    for cell in config['cells']:
        for label,target in cell['difficulty'].items():assert cells[(cell['grade'],cell['module'],label)]==target
    for p in parents:
        assert all(p[k]==v for k,v in source[p['id']].items()), 'source altered in candidate copy'
    variants=[];pairs=[]
    for grade in (7,8,9):
        for q in read(OUT/f'g{grade}.jsonl'):
            p=mapping[q['parent_id']]
            q['source']={k:p.get(k,'') for k in ['source_id','source_ref','source_title','source_url','source_raw_path','source_accessed_at','source_reuse_status','source_notes']}
            q['source']['relation']='Generated variant; URLs and raw paths identify the public parent, not a public source for the generated text.'
            q['parent_risk_flags']=p.get('risk_flags',[])
            q['verification_note']={'arithmetic_constraints':'passed','prose_derivation_review':'independent_reviewer_checked','final_math_approval':False,'scope':'显式计算与题面推导已初核；保留草稿，未通过正式复核与冻结。'}
            variants.append(q)
            parent={k:p.get(k,'') for k in ['id','grade','module','knowledge_point','difficulty','question','answer','family_id','source_title','source_url','source_ref','risk_flags']}
            parent['options']={k:p['option_'+k.lower()] for k in 'ABCD'}
            parent['image_assets']=p.get('image_assets',[])
            parent['image_data']=[]
            for asset in parent['image_assets']:
                file=ROOT/asset['path'];suffix=file.suffix.lower()
                mime='image/png' if suffix=='.png' else 'image/jpeg' if suffix in ('.jpg','.jpeg') else 'image/svg+xml'
                parent['image_data'].append({'alt':asset.get('alt','原题配图'),'data_url':'data:'+mime+';base64,'+base64.b64encode(file.read_bytes()).decode()})
            pairs.append({'parent':parent,'variant':q})
    assert len({q['parent_id'] for q in variants})==30
    jsonl=OUT/'variants_30.jsonl';jsonl.write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in variants),encoding='utf-8')
    writejson(OUT/'pairs_30.json',pairs)
    csvpath=OUT/'variants_30.csv'
    fields=['id','parent_id','family_id','source_type','grade','module','knowledge_point','difficulty','question','option_a','option_b','option_c','option_d','answer','solution','change_description','source_title','source_url','source_ref','generated_by','generation_model','generated_at','status','verification_note']
    with csvpath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for q in variants:
            row={k:q.get(k,'') for k in fields};row.update({'option_'+k.lower():q['options'][k] for k in 'ABCD'})
            row.update({k:q['source'].get(k,'') for k in ['source_title','source_url','source_ref']})
            row.update(generated_by=q['generation_metadata']['agent'],generation_model=q['generation_metadata']['model'],generated_at=q['generation_metadata']['generated_at'],verification_note=json.dumps(q['verification_note'],ensure_ascii=False))
            w.writerow(row)
    assets=ROOT/'data/reports/visualization_assets'
    css=(assets/'katex.min.css').read_text(encoding='utf-8')
    def embed(match):
        name=match.group(1);font=assets/'fonts'/name
        if not font.exists():raise FileNotFoundError(font)
        mime='font/woff2' if name.endswith('.woff2') else 'font/woff' if name.endswith('.woff') else 'font/ttf'
        return 'url(data:'+mime+';base64,'+base64.b64encode(font.read_bytes()).decode()+')'
    # Keep the preferred woff2 source only; all referenced faces are embedded.
    css=re.sub(r'src:url\(fonts/([^)]*\.woff2)\) format\("woff2"\)[^}]*}',lambda m:'src:'+embed(m)+' format("woff2")}',css)
    assert 'url(fonts/' not in css
    template=(ROOT/'data/visualization/variant_pairs_template.html').read_text(encoding='utf-8')
    page=template.replace('__KATEX_CSS__',css).replace('__KATEX_JS__',(assets/'katex.min.js').read_text(encoding='utf-8')).replace('__AUTO_RENDER_JS__',(assets/'auto-render.min.js').read_text(encoding='utf-8')).replace('__CONTENT_JS__',(ROOT/'data/visualization/question_content.js').read_text(encoding='utf-8')).replace('__PAIRS__',json.dumps(pairs,ensure_ascii=False).replace('<','\\u003c'))
    pagepath=ROOT/'可视化/变式试做题对.html';pagepath.write_text(page,encoding='utf-8')
    note='''# 首批变式草稿使用说明\n\n300道母题是候选，其中30道已用于试做。首批30道变式每年级10道，暂定难度12基础、12中等、6困难；变式均为纯文字；试做母题有1道附原图但文字条件完整。后续按用户偏好尽量采用纯文字变式，保留文字条件完整的几何题，不设含图最低数量。\n\nvariants_30.jsonl为通用主记录，options使用A/B/C/D对象，含parent_id、family_id、source、generation_metadata、修改说明与推导。CSV为UTF-8带BOM，可用Excel打开。pairs_30.json保存原母题显示内容与变式关联。来源网址指向公开母题，变式明确标记为生成草稿。\n\n双击“变式试做题对.html”可离线并排查看题对、来源、母题原图、修改说明和折叠的答案/推导，不需要联网。尚未取得这份新页面的真实浏览器检查报告；目前只做公式引擎和代码检查。\n\n显式算术约束与独立题面推导已初核；不表示整个1500题母库数学通过，不表示变式最终批准。原7道缺图提示已更正：独立image_assets原图均完整，筛选漏读字段造成误报。300候选实际21道带图、24个图引用；包中原图保留相对路径。题对与同一family应放在同一数据划分中，防止开发/测试泄漏。\n\n后续：修订候选中的条件/配图风险，依据已验证的试做流程按批扩至300变式，再汇总1800题并划分数据。当前只生成30，剩270。\n'''
    (OUT/'使用说明.md').write_text(note,encoding='utf-8')
    if config.get('generated_variant_count',0)<=30:
        config['status']='pilot_30_generated_constraints_checked_pending_final_review';config['generated_variant_count']=30;config['remaining_variant_count']=270;config['selected_parent_count']=300
        writejson(ROOT/'config/variant_quotas.json',config)
    manifest={'stage':'variant_pilot_v0.1','created_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),'public_count':1500,'public_normalized_sha256':public_hash,'candidate_parents':300,'generated_variants':30,'remaining_variants':270,'grades':dict(Counter(str(q['grade']) for q in variants)),'difficulty':dict(Counter(q['difficulty'] for q in variants)),'mathematical_status':'independent draft review; not approved/frozen','browser_execution_verified':False,'files':{}}
    files=[jsonl,csvpath,OUT/'pairs_30.json',OUT/'使用说明.md',ROOT/'data/variants/parents/parents_300.jsonl',ROOT/'data/variants/parents/parents_300.csv',ROOT/'data/variants/parents/selection_report.md',ROOT/'data/variants/parents/figure_reference_triage.csv',ROOT/'data/reports/variant_pilot_check.json',ROOT/'data/reports/variant_stage_progress.md',pagepath]
    files.extend([ROOT/'config/variant_quotas.json',ROOT/'docs/variant_stage_plan.md'])
    for name in ['variant_pilot_g9_independent_review.json','variant_pilot_root_review.json','variant_parent_diagram_triage.json','variant_pilot_provenance_review.json','variant_pilot_presentation_check.json','parent_image_metadata_correction.json']:
        path=ROOT/'data/reports'/name
        if path.exists():files.append(path)
    image_files={ROOT/a['path'] for p in parents for a in p.get('image_assets',[])}
    files.extend(sorted(image_files))
    def archive_name(file):return file.relative_to(ROOT).as_posix() if file in image_files else file.name
    for f in files:manifest['files'][archive_name(f)]={'sha256':digest(f),'bytes':f.stat().st_size}
    writejson(OUT/'manifest.json',manifest)
    package=ROOT/'data/exports/EduMathBench_variant_pilot_v0.1.zip'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        for f in files+[OUT/'manifest.json']:z.write(f,archive_name(f))
    with zipfile.ZipFile(package) as z:assert z.testzip() is None
    assert digest(public)==public_hash
    print(json.dumps({'parents':300,'drafts':30,'package_bytes':package.stat().st_size,'public_unchanged':True},ensure_ascii=False))

if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8');build()
