"""一次取得公开图片包，避免上千次零散请求；不修改题库。"""
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/hard_collection/images_round1/bulk_probe'
meta=json.loads((BASE/'inventory.json').read_text(encoding='utf-8'))['cmm_math']
url=meta['image_archive_url'];expected=meta['image_archive_exact_size_bytes']
dest=BASE/'images.zip';partial=BASE/'images.zip.part'
assert url.startswith('https://huggingface.co/datasets/ecnu-icalk/cmm-math/resolve/')
if not dest.is_file():
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'EduMathBench-bulk-image-collection'}),timeout=60) as r, partial.open('wb') as f:
        total=0;next_progress=20*1024*1024
        while data:=r.read(1024*1024):
            f.write(data);total+=len(data)
            if total>=next_progress:
                print(json.dumps({'downloaded_bytes':total,'expected_bytes':expected}),flush=True);next_progress+=20*1024*1024
    assert partial.stat().st_size==expected,'下载长度不匹配'
    partial.replace(dest)
assert dest.stat().st_size==expected
with zipfile.ZipFile(dest) as z:
    names=set(z.namelist())
    rows=[json.loads(s) for s in (BASE/'cmm_image_candidates.jsonl').read_text(encoding='utf-8').splitlines()]
    assert all('All_Images/'+r in names for q in rows for r in q['image_refs'])
record={'url':url,'bytes':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
        'path':dest.relative_to(ROOT).as_posix(),'candidate_rows_with_matched_images':len(rows)}
(BASE/'full_archive_manifest.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'complete':True,**record}),flush=True)
