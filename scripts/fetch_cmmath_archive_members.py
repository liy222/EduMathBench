"""Fetch selected public ZIP members with CRC verification and bounded HTTP ranges."""
import argparse,hashlib,json,struct,zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'data/hard_collection/cmmath_new'
manifest=json.loads((BASE/'image_archive_manifest.json').read_text(encoding='utf-8'))
entries={a['member']:a for a in [json.loads(x) for x in (BASE/'image_archive_index.jsonl').read_text(encoding='utf-8').splitlines()]}
cli=argparse.ArgumentParser();cli.add_argument('--metadata',action='store_true');cli.add_argument('--refs-file',type=Path);args=cli.parse_args()
def request(start,end):
 req=Request(manifest['archive_url'],headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity','User-Agent':'EduMathBench-public-source-collection'})
 with urlopen(req,timeout=60) as r:
  assert r.status==206 and r.headers.get('Content-Range','').startswith(f'bytes {start}-{end}/')
  data=r.read(end-start+2)
 assert len(data)==end-start+1
 return data
def fetch(member,path):
 info=entries[member];cached=False
 if path.is_file():
  data=path.read_bytes();cached=len(data)==info['bytes'] and zlib.crc32(data)==info['crc32']
 if not cached:
  start=info['header_offset'];header=request(start,start+29);assert header[:4]==b'PK\x03\x04'
  vals=struct.unpack('<4s5H3L2H',header);assert not vals[2]&1
  offset=start+30+vals[-2]+vals[-1]
  packed=request(offset,offset+info['compressed_bytes']-1)
  data=zlib.decompress(packed,-15) if info['compression']==8 else packed
  assert len(data)==info['bytes'] and zlib.crc32(data)==info['crc32']
  path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
 return {'member':member,'path':path.relative_to(ROOT).as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'crc32':info['crc32'],'cached_verified':cached,'archive_url':manifest['archive_url']}
if args.metadata:
 row=fetch('CMMaTH/cmmath.json',BASE/'raw/cmmath_archive_full.json')
 (BASE/'full_metadata_manifest.json').write_text(json.dumps({**row,'revision':manifest['revision']},ensure_ascii=False,indent=2),encoding='utf-8')
 data=json.loads((BASE/'raw/cmmath_archive_full.json').read_text(encoding='utf-8'))
 print(json.dumps({**row,'data_type':type(data).__name__,'length':len(data),'sample':data[0] if isinstance(data,list) else list(data)[:6]},ensure_ascii=True)[:7000])
elif args.refs_file:
 refs=json.loads(args.refs_file.read_text(encoding='utf-8'));out=BASE/'images'
 basenames={Path(member).name:member for member in entries if member.startswith('CMMaTH/images/')}
 missing=[ref for ref in refs if Path(ref).name not in basenames];assert not missing,missing[:20]
 def job(ref):
  assert Path(ref).name==ref,'image reference contains unexpected directories'
  return {**fetch(basenames[ref],out/ref),'reference':ref}
 with ThreadPoolExecutor(max_workers=6) as pool:rows=list(pool.map(job,refs))
 (BASE/'downloaded_images.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
 print(json.dumps({'images':len(rows),'cached':sum(r['cached_verified'] for r in rows)}))
