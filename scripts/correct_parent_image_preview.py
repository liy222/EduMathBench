from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'data/visualization/variant_pairs_template.html';t=p.read_text(encoding='utf-8')
t=t.replace('block(node,q.question);const list=',"block(node,q.question);for(const asset of q.image_data||[]){const img=document.createElement('img');img.src=asset.data_url;img.alt=asset.alt||'原题配图';img.style='max-width:100%;height:auto;display:block;margin:12px 0';node.append(img)}const list=")
p.write_text(t,encoding='utf-8')
p=ROOT/'data/variants/pilot/g7_generation_notes.md'
note='更正：2026-10-14后续原图核对发现s_04446已有image_assets配图，先前仅看题干和has_image筛选值误认缺图。原图文件完整，已解除母题缺图限制；首批公交替代题仍保留。'
if note not in p.read_text(encoding='utf-8'):
    with p.open('a',encoding='utf-8') as f:f.write('\n\n'+note+'\n')
