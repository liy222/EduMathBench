import csv,hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
read=lambda p:[json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s]
q=read(ROOT/'data/variants/collection/questions.jsonl')
count=len(q)
assert count in (90,300) and count==len({r['id'] for r in q})==len({r['parent_id'] for r in q})
with (ROOT/'data/variants/collection/questions.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
assert len(rows)==count
for a,b in zip(q,rows):
    assert a['question']==b['question'] and a['answer']==b['answer']
    assert all(a['options'][k]==b['option_'+k.lower()] for k in 'ABCD')
    assert a['source']['source_url']==b['source_url']
html_bytes=(ROOT/'可视化/变式题库浏览.html').read_bytes()
html=html_bytes.decode('utf-8')
pairs=json.loads(re.search(r'<script id="pairs-data" type="application/json">(.*?)</script>',html,re.S).group(1))
assert [p['variant'] for p in pairs]==q
presentation=json.loads((ROOT/'data/reports/variant_collection_presentation_check.json').read_text(encoding='utf-8'))
assert presentation['pairs']==count and not presentation['formula_errors']
assert presentation['page_sha256']==hashlib.sha256(html_bytes).hexdigest()
assert hashlib.sha256((ROOT/'data/variants/pilot/variants_30.jsonl').read_bytes()).hexdigest()=='b2b7f945326d3fce31751ba8e4ba9275b02f749e4afd2dd5e1480d2b118fb7cd'
parent_hash=hashlib.sha256((ROOT/'data/variants/parents/parents_300.jsonl').read_bytes()).hexdigest()
if parent_hash!='93d3e7404caf7b13aee7a9987a66460f456ec285c3749f1fd847b26b2fc7f3d4':
    ledger=json.loads((ROOT/'data/variants/parents/b003_substitutions.json').read_text(encoding='utf-8'))
    assert ledger[-1]['new_parent_list_sha256']==parent_hash
    assert hashlib.sha256((ROOT/'data/variants/parents/history/parents_300_before_b003_substitutions.jsonl').read_bytes()).hexdigest()=='93d3e7404caf7b13aee7a9987a66460f456ec285c3749f1fd847b26b2fc7f3d4'
assert hashlib.sha256((ROOT/'data/public_draft/questions.jsonl').read_bytes()).hexdigest()=='3cc709087c4d88d6bdfe885cbfd3c9b9e9f8475b6b10d5f1d129f1d362cd35f4'
assert hashlib.sha256((ROOT/'data/normalized/questions.jsonl').read_bytes()).hexdigest()=='50332abc9d484614f6345ee97953b495d9c94970e3afd127c92287b18d79e647'
if count==300:
    with zipfile.ZipFile(ROOT/'data/exports/EduMathBench_variants_90_draft.zip') as oldzip:
        prior=[json.loads(s) for s in oldzip.read('data/variants/collection/questions.jsonl').decode('utf-8').splitlines() if s]
    stable_fields=['id','parent_id','family_id','question','options','answer','solution','grade','module','difficulty','generation_metadata']
    assert [{k:r[k] for k in stable_fields} for r in prior]==[{k:r[k] for k in stable_fields} for r in q[:90]],'prior90 changed'
package=ROOT/f'data/exports/EduMathBench_variants_{count}_draft.zip'
with zipfile.ZipFile(package) as z:
    assert z.testzip() is None
    manifest=json.loads(z.read('data/variants/collection/manifest.json'))
    for name,meta in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==meta['sha256']
    assert z.read('变式题库浏览.html')==html_bytes
progress=json.loads((ROOT/'data/reports/variant_collection_progress.json').read_text(encoding='utf-8'))
reviewed=sum(r['verification_note']['prose_derivation_review']=='independent_draft_review' for r in q)
assert progress['independent_reviewed_variants']==reviewed
assert progress['independent_review_pending']==count-reviewed
print(f'PASS: JSONL/CSV/HTML{count} aligned; parent{count} unique; pilot30/public unchanged and parent substitutions traceable; package hashes/CRC; independent reviewed{reviewed}, pending{count-reviewed}')
