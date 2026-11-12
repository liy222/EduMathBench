"""Crop public-source four-choice questions before their printed answers.

Keep equations in the source image when PDF text extraction loses symbols.
Every crop remains pending a visual check; no answer or solution enters inputs.
"""
import hashlib,json,re,subprocess,sys
from pathlib import Path
import pdfplumber
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/hard_collection/public_pdf/additional'
OUT=BASE/'question_images';OUT.mkdir(exist_ok=True)
rows=[json.loads(x) for x in (BASE/'firststep.jsonl').read_text(encoding='utf-8').splitlines()]
sources={x['filename']:x for x in json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))}
prepared,held=[],[]
cache={}
for q in rows:
 answer=q.get('source_answer','')
 text=q.get('question_text_extracted','')
 if answer not in list('ABCD') or not all(re.search(letter+r'[．.、]',text) for letter in 'ABCD'):
  held.append({'candidate_id':q['candidate_id'],'reason':'not source four-choice single-answer question'});continue
 src=BASE/q['sourcefile'];start=q['question_start_page'];end=q['answer_page']
 pieces=[];boxes=[]
 try:
  with pdfplumber.open(src) as pdf:
   for number in range(start,end+1):
    page=pdf.pages[number-1];lines=page.extract_text_lines(return_chars=False)
    top=35;bottom=page.height-35
    if number==start:
     starts=[line for line in lines if re.match(r'^\s*'+re.escape(str(q['qnumber']))+r'[．.、]',line['text'])]
     if not starts:raise ValueError('question number not located')
     top=starts[0]['top']-5
    if number==end:
     endings=[line for line in lines if '【答案】' in line['text'] and line['top']>top]
     if not endings:raise ValueError('printed answer boundary not located')
     bottom=endings[0]['top']-4
    if bottom<=top:raise ValueError('invalid crop interval')
    png=OUT/f"{src.stem}-page-{number}.png"
    if not png.exists():
     subprocess.run(['pdftoppm','-f',str(number),'-l',str(number),'-scale-to','1800','-singlefile','-png',str(src),str(png.with_suffix(''))],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    image=Image.open(png).convert('RGB');sx=image.width/page.width;sy=image.height/page.height
    box=(20,top,page.width-20,bottom);pixels=tuple(round(x*sx if i%2==0 else x*sy) for i,x in enumerate(box))
    pieces.append(image.crop(pixels));boxes.append({'page':number,'pdf_points_box':list(box),'pixel_box':list(pixels),'page_image_path':str(png.relative_to(ROOT)).replace('\\','/')})
  width=max(p.width for p in pieces);height=sum(p.height for p in pieces)+10*(len(pieces)-1)
  result=Image.new('RGB',(width,height),'white');offset=0
  for p in pieces:result.paste(p,(0,offset));offset+=p.height+10
  path=OUT/(q['candidate_id']+'.png');result.save(path)
  prepared.append({**q,'image_path':str(path.relative_to(ROOT)).replace('\\','/'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                   'source_url':sources[q['sourcefile']]['source_url'],'source_title':sources[q['sourcefile']]['title'],
                   'source_raw_path':str(src.relative_to(ROOT)).replace('\\','/'),'crop_boxes':boxes,
                   'visual_checked':False,'status':'question_crop_pending_visual_review','image_content_scope':'question_and_four_options'})
 except Exception as e:held.append({'candidate_id':q['candidate_id'],'reason':str(e)})
(BASE/'mcq_image_candidates.jsonl').write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in prepared),encoding='utf-8')
(BASE/'pdf_triage.jsonl').write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in held),encoding='utf-8')
print(json.dumps({'four_choice_crops':len(prepared),'other_or_held':len(held)}))
