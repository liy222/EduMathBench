"""Verify data lineage, split invariants, portable inputs, and packaged bytes."""
import csv, hashlib, json, zipfile
from collections import Counter
from pathlib import Path
from build_benchmark_draft import ROOT, OUT, INPUTS, read, sha, graph, split_families

def verify(package=False):
    rows=read(OUT/'questions.jsonl');byid={q['id']:q for q in rows}
    originals=read(ROOT/INPUTS[2])+read(ROOT/INPUTS[3]);source={q['id']:q for q in originals}
    assert len(rows)==len(byid)==1800 and set(byid)==set(source)
    policy=json.loads((OUT/'split_policy.json').read_text(encoding='utf-8'))
    for name,digest in policy['input_snapshots'].items():assert sha(ROOT/name)==digest
    for name,digest in policy['ledger_snapshots'].items():assert sha(ROOT/name)==digest
    assert policy['version']=='split-policy-v0.2'
    assert sha(ROOT/policy['revision_config_path'])==policy['revision_config_sha256']
    assert sha(ROOT/policy['prior_policy_path'])==policy['prior_policy_sha256']
    for q in rows:
        s=source[q['id']]
        for k in ['question','options','answer','solution','status','risk_flags','grade','module','difficulty','knowledge_point','image_assets']:
            assert q.get(k)==s.get(k),f'upstream content changed {q["id"]}:{k}'
        assert q['answer'] in 'ABCD' and set(q['options'])==set('ABCD')
        assert q['upstream_family_id']==s.get('family_id','')
        assert all(k in q['source'] for k in ['id','title','url','reference','raw_path','accessed_at','reuse_status','relation'])
        if q['source_type']=='public':
            for k,v in s['source'].items():assert q['source'][k]==v
        else:
            assert q['source']['id']==s['source']['source_id'] and q['source']['reference']==s['source']['source_ref']
            assert q['source']['url']==s['source']['source_url'] and q['upstream_source']==s['source']
            assert q['parent_id'] in byid
            p=byid[q['parent_id']]
            assert q['family_id']==p['family_id'] and q['split']==p['split']
            assert q['split']=='test' and not q['debug_subset'] and not p['debug_subset']
            for k in ['generation_metadata','verification_note','verification_spec','change_description']:
                assert q[k]==s[k]
        for a in q['image_assets']:assert sha(OUT/a['path'])==a['sha256']
    families=read(OUT/'families.jsonl');member_ids=[]
    for f in families:
        member_ids.extend(f['member_ids']);members=[byid[i] for i in f['member_ids']]
        assert {q['split'] for q in members}=={f['split']}
        assert {q['family_id'] for q in members}=={f['family_id']}
        assert len({q['debug_subset'] for q in members})==1
    assert len(member_ids)==len(set(member_ids))==1800 and set(member_ids)==set(byid)
    for e in read(OUT/'family_edges.jsonl'):
        if e['left_id'] in byid and e['right_id'] in byid:
            assert byid[e['left_id']]['split']==byid[e['right_id']]['split']
            assert byid[e['left_id']]['family_id']==byid[e['right_id']]['family_id']
    # Repeat grouping/selection from archived inputs, without writing any files.
    generated_families,_=graph(originals);assignments,debug=split_families(originals,generated_families)
    assert all(assignments[q['id']]==q['split'] and (q['id'] in debug)==q['debug_subset'] for q in rows)
    dev={q['id'] for q in rows if q['split']=='dev'};test={q['id'] for q in rows if q['split']=='test'}
    assert not dev&test and dev|test==set(byid) and debug<=dev and len(debug)==100
    assert all(byid[i]['source_type']=='public' for i in dev|debug)
    revision=json.loads((ROOT/policy['revision_config_path']).read_text(encoding='utf-8'))
    assert set(revision['protected_dev_public_ids'])<=dev and set(revision['protected_debug_public_ids'])<=debug
    for name,expected in [('dev',{'public':150}),('test',{'public':1350,'variant':300}),('debug100',{'public':100})]:
        subset=read(OUT/'splits'/f'{name}.jsonl');ids=json.loads((OUT/'splits'/f'{name}_ids.json').read_text(encoding='utf-8'))
        assert [q['id'] for q in subset]==ids and Counter(q['source_type'] for q in subset)==expected
        for q in subset:assert q==byid[q['id']]
        if name!='debug100':assert Counter(q['grade'] for q in subset)=={7:50 if name=='dev' else 550,8:50 if name=='dev' else 550,9:50 if name=='dev' else 550}
        inp=read(OUT/f'{name}_inputs.jsonl');keys=read(OUT/f'{name}_answer_key.jsonl')
        assert [q['id'] for q in inp]==ids==[q['id'] for q in keys]
        for q,key in zip(inp,keys):
            original=byid[q['id']];assert set(q)=={'id','question','options','input_modality','image_assets'}
            assert q['question']==original['question'] and q['options']==original['options']
            assert key=={'id':original['id'],'answer':original['answer'],'solution':original['solution']}
            for a in q['image_assets']:
                assert set(a)<={'path','sha256','role','placeholder_index','source_placeholder_field','alt'}
                assert sha(OUT/a['path'])==a['sha256']
    with (OUT/'questions.csv').open(encoding='utf-8-sig',newline='') as f:csvrows=list(csv.DictReader(f))
    assert len(csvrows)==1800
    for q,c in zip(rows,csvrows):
        for k in ['id','parent_id','family_id','split','question','answer','solution','status']:assert str(q[k])==c[k]
        for k in 'ABCD':assert q['options'][k]==c['option_'+k.lower()]
        assert q['source']['url']==c['source_url']
    html=(ROOT/'可视化/完整题库浏览.html').read_bytes()
    import re
    page_rows=json.loads(re.search(rb'<script id="questions-data" type="application/json">(.*?)</script>',html,re.S)[1])
    assert len(page_rows)==1800
    fragments=0
    for q,rendered in zip(rows,page_rows):
        for k,v in q.items():assert rendered[k]==v
        for a,img in zip(q['image_assets'],rendered['image_data']):
            import base64
            assert hashlib.sha256(base64.b64decode(img['data_url'].split(',')[1])).hexdigest()==a['sha256']
            assert img['field']==a.get('source_placeholder_field','question')
        display=rendered['solution_display']
        assert display['source_sha256']==hashlib.sha256(q['solution'].encode()).hexdigest()
        if display['status']=='raw_source_fragment':
            fragments+=1;assert display['text']==q['solution'] and q['source_type']=='public' and display['issues']
    assert html==(OUT/'完整题库浏览.html').read_bytes()
    report=json.loads((ROOT/'data/reports/benchmark_draft_presentation_check.json').read_text(encoding='utf-8'))
    assert report['page_sha256']==hashlib.sha256(html).hexdigest() and not report['formula_errors']
    assert report['source_solution_fragments_displayed_literally']==fragments
    result={'passed':True,'questions':1800,'parent_variant_pairs':300,'families':len(families),
            'dev_count':150,'dev_variants':0,'test_count':1650,'test_variants':300,'debug100_count':100,'debug100_variants':0,'all_variant_parent_families_test_only':True,'source_content_preserved':True,
            'deterministic_split_reproduced':True,'family_cross_split_count':0,'image_refs_checked':sum(len(q['image_assets']) for q in rows),
            'source_solution_fragment_fallbacks':fragments,'browser_execution_verified':False,'final_approved':False}
    if package:
        with zipfile.ZipFile(ROOT/'data/exports/EduMathBench_1800_draft_v0.1.zip') as z:
            assert z.testzip() is None
            manifest=json.loads(z.read('manifest.json'))
            assert set(z.namelist())==set(manifest['files'])|{'manifest.json'}
            for name,meta in manifest['files'].items():
                raw=z.read(name);assert len(raw)==meta['bytes'] and hashlib.sha256(raw).hexdigest()==meta['sha256']
                assert raw==(OUT/name).read_bytes()
            audit=json.loads(z.read('luna_split_audit.json'));assert audit['passed'] and not audit['issues']
            for name,meta in audit['artifact_binding']['audited_file_sha256_and_bytes'].items():assert sha(ROOT/name)==meta['sha256']
        result['zip_crc_and_manifest_checked']=True
    else:
        (ROOT/'data/reports/benchmark_draft_verify.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));return result

if __name__=='__main__':
    import sys
    verify('--package' in sys.argv)
