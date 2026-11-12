"""Cross-format and packaged provenance integrity checks for the pilot."""
import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
q=[json.loads(s) for s in (ROOT/'data/variants/pilot/variants_30.jsonl').read_text(encoding='utf-8').splitlines()]
with (ROOT/'data/variants/pilot/variants_30.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
assert len(rows)==len(q)==30
required=load('config/variant_quotas.json')['variant_required_fields']
assert all(all(k in a for k in required) for a in q)
for a,b in zip(q,rows):
    assert a['question']==b['question'] and a['answer']==b['answer']
    assert all(a['options'][k]==b['option_'+k.lower()] for k in 'ABCD')
    assert a['source']['source_url']==b['source_url']
html=(ROOT/'可视化/变式试做题对.html').read_text(encoding='utf-8')
pairs=json.loads(re.search(r'<script id="pairs-data" type="application/json">(.*?)</script>',html,re.S).group(1))
assert [p['variant'] for p in pairs]==q
reviews=load('data/reports/variant_pilot_root_review.json')['records']+load('data/reports/variant_pilot_g9_independent_review.json')['records']
reviewmap={a['id']:a.get('answer',a.get('independently_derived_answer')) for a in reviews}
assert len(reviewmap)==30 and all(reviewmap[a['id']]==a['answer'] for a in q)
with (ROOT/'data/variants/parents/figure_reference_triage.csv').open(encoding='utf-8-sig',newline='') as f:triage=list(csv.DictReader(f))
assert len(triage)==17 and sum(a['figure_reference_status']=='需图待补' for a in triage)==0
image_report=load('data/reports/parent_image_metadata_correction.json')
assert image_report['actual_image_parents']==21 and image_report['verified_image_references']==24 and image_report['missing_image_files']==0
assert hashlib.sha256((ROOT/'data/public_draft/questions.jsonl').read_bytes()).hexdigest()=='3cc709087c4d88d6bdfe885cbfd3c9b9e9f8475b6b10d5f1d129f1d362cd35f4'
with zipfile.ZipFile(ROOT/'data/exports/EduMathBench_variant_pilot_v0.1.zip') as z:
    assert z.testzip() is None
    manifest=json.loads(z.read('manifest.json'))
    assert all(hashlib.sha256(z.read(name)).hexdigest()==meta['sha256'] for name,meta in manifest['files'].items())
print('PASS: CSV roundtrip30; HTML payload30; independent-review coverage30; image parents21/references24/missing0; public raw hash unchanged; ZIP CRC and all manifest hashes')
