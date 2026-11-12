"""沿用本地题库浏览方式，图像题展示原题图而非来源答案整页。"""
import base64
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
questions=[json.loads(s) for s in (ROOT/'data/public_image_draft/questions.jsonl').read_text(encoding='utf-8').splitlines()]
rows=[]
for q in questions:
    assets=[]
    for a in q['image_assets']:
        data=(ROOT/a['path']).read_bytes()
        assets.append({'role':a['role'],'option':a.get('option',''),'alt':a.get('alt','原题配图'),
                       'src':'data:image/png;base64,'+base64.b64encode(data).decode('ascii')})
    rows.append([q['id'],q['question'],*[q['option_'+c] for c in 'abcd'],q['answer'],q['grade'],q['module'],q['difficulty'],q['knowledge_point'],q['source_id'],q['source_ref'],assets,q['source_notes']])
sources={q['source_id']:[q['source_title'],q['source_url'],q['source_notes']] for q in questions}
text=(ROOT/'data/visualization/local-source.html').read_text(encoding='utf-8')
payload=json.dumps([rows,sources],ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
text,n=re.subn(r'(<script type="application/json" id="emb-data">)[\s\S]*?(</script>)',lambda m:m[1]+payload+m[2],text)
assert n==1
text=text.replace('<h2>EduMathBench 题库</h2>','<h2>EduMathBench 图像题</h2>')
text=text.replace('<span>公开题初版</span><span>1500 道</span>','<span>新增图像题初版</span><span>'+str(len(questions))+' 道</span>')
text=text.replace('#emb-explorer .emb-stem {','#emb-explorer .emb-figure {display:block;max-width:100%;height:auto;margin:12px 0}\n#emb-explorer .emb-stem {')
anchor='function charts(){'
picture="function picture(a){const img=element('img','emb-figure');img.src=a.src;img.alt=a.alt;img.setAttribute('data-question-image','');return img;} "
assert anchor in text;text=text.replace(anchor,picture+anchor)
opts="'ABCD'.split('').forEach((c,i)=>opts.append(element('div','emb-option',c+'. '+q[2+i])));"
opts_new="'ABCD'.split('').forEach((c,i)=>{const option=element('div','emb-option',c+'. '+q[2+i]);(q[13]||[]).filter(a=>a.role==='option'&&a.option===c).forEach(a=>option.append(picture(a)));opts.append(option);});"
assert opts in text;text=text.replace(opts,opts_new)
append='article.append(meta,stem,opts,detail,sourceBlock);'
new_append="article.append(meta,stem);(q[13]||[]).filter(a=>a.role==='stem').forEach(a=>article.append(picture(a)));article.append(opts,detail,sourceBlock);"
assert append in text;text=text.replace(append,new_append)
text=text.replace("source[2]||'未登记补充说明'", "q[14]||source[2]||'未登记补充说明'")
out=ROOT/'data/visualization/image-source.html';out.write_text(text,encoding='utf-8')
assert out.stat().st_size<1000000
print(json.dumps({'questions':len(questions),'source':str(out),'embedded_images':sum(len(q['image_assets']) for q in questions)},ensure_ascii=True))
