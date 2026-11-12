"""Fetch publicly linked capstone worksheets and retain full source hashes."""
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/hard_collection/public_pdf'
OUT.mkdir(parents=True,exist_ok=True)
SOURCES=[
 ('g7_midterm_50','https://www.gcyls.cn/file/upload/202406/01/161436661.pdf'),
 ('g9_quadratic_30','https://www.gcyls.cn/file/upload/202409/01/103033541.pdf'),
]
def fetch(item):
 name,url=item;path=OUT/(name+'.pdf')
 if not path.is_file():
  req=Request(url,headers={'User-Agent':'Mozilla/5.0'})
  with urlopen(req,timeout=40) as r:data=r.read()
  assert data.startswith(b'%PDF-'),url
  path.write_bytes(data)
 data=path.read_bytes()
 return {'id':name,'url':url,'path':str(path.relative_to(ROOT)).replace('\\','/'),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(fetch,SOURCES))
(OUT/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(rows))
