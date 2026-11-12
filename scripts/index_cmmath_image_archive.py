"""Read the public image ZIP directory with a bounded HTTP range request."""
import io,json,re,zipfile,hashlib
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'data/hard_collection/cmmath_new';OUT.mkdir(parents=True,exist_ok=True)
api='https://huggingface.co/api/datasets/lizhongzhi2022/cmmath'
with urlopen(api,timeout=35) as r:metadata=json.load(r)
revision=metadata['sha'];url=f'https://huggingface.co/datasets/lizhongzhi2022/cmmath/resolve/{revision}/CMMaTH.zip'
req=Request(url,headers={'Range':'bytes=-8388608','User-Agent':'EduMathBench-public-source-collection','Accept-Encoding':'identity'})
with urlopen(req,timeout=60) as r:
 assert r.status==206,'Archive server did not support bounded ranges'
 content_range=r.headers['Content-Range'];data=r.read(8388609)
match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',content_range);assert match
start,end,total=map(int,match.groups());assert len(data)==end-start+1 and len(data)<=8388608
(OUT/'image_zip_tail.bin').write_bytes(data)
with zipfile.ZipFile(io.BytesIO(data)) as z:
 entries=[{'member':a.filename,'header_offset':a.header_offset+start,'compressed_bytes':a.compress_size,
           'bytes':a.file_size,'crc32':a.CRC,'compression':a.compress_type} for a in z.infolist() if not a.is_dir()]
(OUT/'image_archive_index.jsonl').write_text(''.join(json.dumps(a,ensure_ascii=False)+'\n' for a in entries),encoding='utf-8')
manifest={'publisher':'lizhongzhi2022/cmmath','revision':revision,'archive_url':url,'archive_exact_bytes':total,
          'tail_start':start,'tail_bytes':len(data),'tail_sha256':hashlib.sha256(data).hexdigest(),'directory_entries':len(entries),
          'full_archive_downloaded':False}
(OUT/'image_archive_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({**manifest,'sample_members':[a['member'] for a in entries[:8]]}))
