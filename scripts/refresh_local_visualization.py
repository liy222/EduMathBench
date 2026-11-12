"""刷新本地展示用的可编辑源；不改聊天中此前展示的可视化。"""
import json
import base64
import re
from pathlib import Path
from question_format import canonical_question

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = Path('C:/Users/liyh/.codex/visualizations/2026/10/09/01a11f19-ee8b-7ec0-b820-72511aebd0e2/edumathbench-explorer.html')


def main():
    rows = [json.loads(s) for s in (ROOT / 'data/public_draft/questions.jsonl').read_text(encoding='utf-8').splitlines()]
    data = []
    for native in rows:
        q = canonical_question(native)
        assets = []
        for a in q.get('image_assets', []):
            p = ROOT / a['path']
            mime = 'image/jpeg' if p.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png'
            assets.append({'role': a['role'], 'option': a.get('option', ''), 'alt': a.get('alt', '原题配图'),
                           'src': 'data:' + mime + ';base64,' + base64.b64encode(p.read_bytes()).decode('ascii')})
        data.append([q['id'], q['question'], *[q['option_' + c] for c in 'abcd'], q['answer'],
             q['grade'], q['module'], q['difficulty'], q['knowledge_point'], q['source_id'], q['source_ref'], assets, q['source_notes']])
    sources = {q['source_id']: [q['source_title'], q['source_url'], q['source_notes']] for q in rows}
    text = ORIGINAL.read_text(encoding='utf-8')
    payload = json.dumps([data, sources], ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    pattern = r'(<script type="application/json" id="emb-data">)[\s\S]*?(</script>)'
    text, count = re.subn(pattern, lambda m: m[1] + payload + m[2], text)
    assert count == 1 and len(rows) == 1500
    text = text.replace('#emb-explorer .emb-stem {', '#emb-explorer .emb-figure {display:block;max-width:100%;height:auto;margin:12px 0}\n#emb-explorer .emb-stem {')
    picture = "function picture(a){const img=element('img','emb-figure');img.src=a.src;img.alt=a.alt;img.setAttribute('data-question-image','');return img;} function inputContent(container,text,assets){const parts=text.split('<ImageHere>');parts.forEach((part,i)=>{if(part)container.append(document.createTextNode(part));if(i<parts.length-1&&assets[i])container.append(picture(assets[i]));});assets.slice(parts.length-1).forEach(a=>container.append(picture(a)));} "
    text = text.replace('function charts(){', picture + 'function charts(){')
    table_renderer = (ROOT / 'data/visualization/question_content.js').read_text(encoding='utf-8')
    text = text.replace('function picture(a){', table_renderer + '\nfunction picture(a){')
    text = text.replace('container.append(document.createTextNode(part))', 'embAppendText(container,part)')
    text = text.replace('#emb-explorer .katex-display {', '#emb-explorer .emb-input-table {white-space:normal;margin:12px 0}\n#emb-explorer .katex-display {')
    text = text.replace("const stem=element('div','emb-stem',q[1]);", "const stem=element('div','emb-stem');inputContent(stem,q[1],(q[13]||[]).filter(a=>a.role==='stem'));")
    opts = "'ABCD'.split('').forEach((c,i)=>opts.append(element('div','emb-option',c+'. '+q[2+i])));"
    replacement = "'ABCD'.split('').forEach((c,i)=>{const option=element('div','emb-option');inputContent(option,c+'. '+q[2+i],(q[13]||[]).filter(a=>a.role==='option'&&a.option===c));opts.append(option);});"
    assert opts in text
    text = text.replace(opts, replacement)
    text = text.replace("source[2]||'未登记补充说明'", "q[14]||source[2]||'未登记补充说明'")
    out = ROOT / 'data/visualization/local-source.html'
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding='utf-8')
    # This is the user's standalone offline page, not an inline visualization fragment.
    print(json.dumps({'count': len(rows), 'editable_local_source': str(out)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
