"""Retrieve the contiguous public original-image section, excluding 1.8 GB of model outputs."""
import hashlib,json,struct,zlib
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'data/hard_collection/cmmath_new'
manifest=json.loads((BASE/'image_archive_manifest.json').read_text(encoding='utf-8'))
entries=[json.loads(x) for x in (BASE/'image_archive_index.jsonl').read_text(encoding='utf-8').splitlines()]
images=[a for a in entries if a['member'].startswith('CMMaTH/images/')]
start=min(a['header_offset'] for a in images)
# Find the next ZIP local header, so the original image section is complete.
last=max(images,key=lambda a:a['header_offset']);nexts=[a['header_offset'] for a in entries if a['header_offset']>last['header_offset']]
end=min(nexts)-1 if nexts else last['header_offset']+last['compressed_bytes']+500
block=BASE/'images_public_block.bin'
if not block.is_file() or block.stat().st_size!=end-start+1:
 req=Request(manifest['archive_url'],headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity','User-Agent':'EduMathBench-public-source-collection'})
 with urlopen(req,timeout=60) as r:
  assert r.status==206 and r.headers['Content-Range'].startswith(f'bytes {start}-{end}/')
  with block.open('wb') as f:
   while True:
    b=r.read(1048576)
    if not b:break
    f.write(b)
 assert block.stat().st_size==end-start+1
refs=set(json.loads((BASE/'priority_image_refs.json').read_text(encoding='utf-8')));out=BASE/'images';out.mkdir(exist_ok=True)
rows=[]
with block.open('rb') as f:
 for a in images:
  ref=Path(a['member']).name
  if ref not in refs:continue
  f.seek(a['header_offset']-start);header=f.read(30);assert header[:4]==b'PK\x03\x04'
  values=struct.unpack('<4s5H3L2H',header);assert not values[2]&1
  f.seek(values[-2]+values[-1],1);packed=f.read(a['compressed_bytes'])
  data=zlib.decompress(packed,-15) if a['compression']==8 else packed
  assert len(data)==a['bytes'] and zlib.crc32(data)==a['crc32']
  assert data.startswith((b'\x89PNG',b'\xff\xd8',b'GIF8'))
  p=out/ref;p.write_bytes(data)
  rows.append({'reference':ref,'member':a['member'],'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'crc32':a['crc32']})
assert {a['reference'] for a in rows}==refs
(BASE/'downloaded_images.jsonl').write_text(''.join(json.dumps(a,ensure_ascii=False)+'\n' for a in rows),encoding='utf-8')
(BASE/'image_block_manifest.json').write_text(json.dumps({'archive_url':manifest['archive_url'],'range_start':start,'range_end':end,'bytes':block.stat().st_size,'sha256':hashlib.sha256(block.read_bytes()).hexdigest(),'extracted_refs':len(rows),'full_archive_downloaded':False},indent=2),encoding='utf-8')
print(json.dumps({'downloaded_public_image_bytes':block.stat().st_size,'verified_original_images':len(rows)}))
