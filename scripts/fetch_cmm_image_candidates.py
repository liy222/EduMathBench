"""按题号批量取得公开ZIP中的必要图片，无需整包下载或逐页找图。"""
import argparse
import io
import json
import hashlib
import struct
import urllib.request
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/hard_collection/images_round1/bulk_probe'
inventory=json.loads((BASE/'inventory.json').read_text(encoding='utf-8'))['cmm_math']
url=inventory['image_archive_url']
assert url.startswith('https://huggingface.co/datasets/ecnu-icalk/cmm-math/resolve/')
tail=(BASE/'images_zip_tail.bin').read_bytes()
shift=inventory['image_archive_exact_size_bytes']-len(tail)
with zipfile.ZipFile(io.BytesIO(tail)) as z:
    entries={m.filename:m for m in z.infolist() if m.filename.startswith('All_Images/') and not m.is_dir()}
rows=[json.loads(s) for s in (BASE/'cmm_image_candidates.jsonl').read_text(encoding='utf-8').splitlines()]
cli=argparse.ArgumentParser()
cli.add_argument('--ids',nargs='+',help='源题号，如1293；不指定时须明确给出--limit')
cli.add_argument('--limit',type=int)
cli.add_argument('--workers',type=int,default=4)
args=cli.parse_args()
assert args.ids or args.limit,'请选择题号或小批数量，不隐式下载全部'
selected=[q for q in rows if not args.ids or q['original_id'] in args.ids]
if args.limit:selected=selected[:args.limit]
if args.ids:assert set(args.ids)=={q['original_id'] for q in selected},'未知题号'
refs=sorted({ref for q in selected for ref in q['image_refs']})
out=BASE/'sample_images';out.mkdir(exist_ok=True)

def request_range(start,end):
    req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}','User-Agent':'EduMathBench-image-collection'})
    with urllib.request.urlopen(req,timeout=45) as r:
        assert r.status==206,'服务器没有按范围返回，停止而不隐式下载整包'
        assert r.headers['Content-Range'].startswith(f'bytes {start}-{end}/')
        data=r.read(end-start+2)
    assert len(data)==end-start+1
    return data

def fetch(ref):
    assert Path(ref).name==ref and ref not in ['.','..']
    info=entries['All_Images/'+ref];path=out/ref
    cached=False
    if path.is_file():
        data=path.read_bytes();cached=len(data)==info.file_size and zlib.crc32(data)==info.CRC
    if not cached:
        start=info.header_offset+shift
        header=request_range(start,start+29)
        assert header[:4]==b'PK\x03\x04'
        values=struct.unpack('<4s5H3L2H',header)
        flags,method=values[2],values[3]
        assert not flags&1 and method==info.compress_type,'不支持的加密或格式'
        name_len,extra_len=values[-2:]
        offset=start+30+name_len+extra_len
        packed=request_range(offset,offset+info.compress_size-1)
        if method==8:data=zlib.decompress(packed,-15)
        elif method==0:data=packed
        else:raise ValueError('不支持的压缩方法')
        assert len(data)==info.file_size and zlib.crc32(data)==info.CRC
        assert data.startswith((b'\xff\xd8',b'\x89PNG',b'GIF8')),'图片签名不匹配'
        path.write_bytes(data)
    return {'reference':ref,'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(data).hexdigest(),
            'bytes':len(data),'crc32':f'{info.CRC:08x}','cached_verified':cached,'archive_url':url,
            'archive_member':info.filename,'roles_verified':False}

with ThreadPoolExecutor(max_workers=min(max(args.workers,1),8)) as pool:assets=list(pool.map(fetch,refs))
mapping={a['reference']:a for a in assets}
ready=[{**q,'downloaded_image_assets':[mapping[r] for r in q['image_refs']],
        'image_access_status':'downloaded_crc_verified; diagram roles/answer separation still require source correspondence'} for q in selected]
(BASE/'image_download_batch.jsonl').write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in ready),encoding='utf-8')
print(json.dumps({'selected_questions':len(ready),'unique_images':len(assets),'cached':sum(a['cached_verified'] for a in assets),
                  'full_archive_downloaded':False,'difficulty':'pending','next':'查看题图并确认题干/选项对应，筛选困难、年级与模块'},ensure_ascii=True))
