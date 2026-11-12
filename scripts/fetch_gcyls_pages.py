"""Archive public source pages and follow only their explicitly linked PDFs."""
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request,urlopen
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'data/hard_collection/public_pdf'
IDS=[73992,73957,73955]
def get(url):
 with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=35) as r:return r.read()
def fetch(item):
 url=f'https://www.gcyls.cn/down/show.php?itemid={item}'
 data=get(url);(OUT/f'source_{item}.html').write_bytes(data)
 s=BeautifulSoup(data,'html.parser')
 links=set(re.findall(r'(?:https?://[^\s\"\'<>]+)?/file/upload/[^\s\"\'<>]+\.pdf',data.decode('utf-8',errors='replace')))
 rows=[]
 for i,link in enumerate(sorted(links)):
  absolute=urljoin(url,link);b=get(absolute)
  if not b.startswith(b'%PDF-'):continue
  p=OUT/f'gcyls_{item}_{i}.pdf';p.write_bytes(b)
  rows.append({'id':f'gcyls_{item}_{i}','url':absolute,'source_page_url':url,'source_page_title':s.title.get_text() if s.title else '',
               'path':str(p.relative_to(ROOT)).replace('\\','/'),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
 return {'itemid':item,'linked_pdfs':rows,'page_title':s.title.get_text() if s.title else '', 'page_text':s.get_text(' ',strip=True)[-7000:]}
with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(fetch,IDS))
(OUT/'linked_pdf_manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(rows,ensure_ascii=True))
