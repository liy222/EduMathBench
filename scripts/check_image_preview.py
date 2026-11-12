"""静态核对本地页数据、内置题图与离线依赖；不启动受限浏览器。"""
import base64
import hashlib
import json
import re
import subprocess
import argparse
from pathlib import Path
from html.parser import HTMLParser
from bs4 import BeautifulSoup
from question_format import canonical_question

ROOT=Path(__file__).resolve().parents[1]
cli=argparse.ArgumentParser()
cli.add_argument('--main', action='store_true')
args=cli.parse_args()
page=ROOT/('可视化/题库浏览.html' if args.main else '可视化/图像题浏览.html')
class FrameParser(HTMLParser):
    def handle_starttag(self,tag,attrs):
        if tag=='iframe':self.inner=dict(attrs)['data-srcdoc']
fp=FrameParser();fp.feed(page.read_text(encoding='utf-8'))
s=BeautifulSoup(fp.inner,'html.parser')
embedded=json.loads(s.find('script',id='emb-data').string)[0]
questions=[json.loads(line) for line in (ROOT/('data/public_draft/questions.jsonl' if args.main else 'data/public_image_draft/questions.jsonl')).read_text(encoding='utf-8').splitlines()]
assert len(embedded)==len(questions)
for row,q in zip(embedded,questions):
    display_q = canonical_question(q) if args.main else q
    assert row[:10]==[display_q['id'],display_q['question'],*[display_q['option_'+c] for c in 'abcd'],q['answer'],q['grade'],q['module'],q['difficulty']]
    assert row[14]==q['source_notes']
    assert len(row[13])==len(q.get('image_assets', []))
    for display,asset in zip(row[13],q.get('image_assets', [])):
        data=base64.b64decode(display['src'].split(',',1)[1])
        assert data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8')
        assert hashlib.sha256(data).hexdigest()==asset['sha256'].lower()
        assert display['role']==asset['role'] and display['alt']
assert not s.select('script[src],link[href^="http"]')
assert 'cdn.jsdelivr.net/npm/katex@0.16.11/dist/fonts/' not in fp.inner
assert fp.inner.count('data:font/woff2;base64,')==20
scripts=[e.get_text() for e in s.find_all('script') if e.get('type')!='application/json']
for code in scripts:
    result=subprocess.run(['node','-e','new Function(require("fs").readFileSync(0,"utf8"));'],input=code,text=True,capture_output=True,encoding='utf-8')
    assert result.returncode==0,result.stderr
core=next(code for code in scripts if 'function picture(a)' in code)
assert "a.role==='stem'" in core and "a.role==='option'&&a.option===c" in core
assert 'max-width:100%;height:auto' in fp.inner
summary={'count':len(questions),'embedded_images_match_archive':sum(len(q.get('image_assets', [])) for q in questions),'individual_source_notes_match':True,
         'javascript_syntax_passed':len(scripts),'offline_fonts':20,'external_runtime_dependencies':0,
         'browser_render_checked':False,'browser_preview_limit':'Codex浏览器不允许file协议；采用静态页面、数据及图片完整性检查。'}
browser_summary_path = ROOT / 'data/reports/luna_render_audit/browser_report_verified_summary.json'
if args.main and browser_summary_path.is_file():
    browser = json.loads(browser_summary_path.read_text(encoding='utf-8'))
    normalized_hash = hashlib.sha256((ROOT / 'data/normalized/questions.jsonl').read_bytes()).hexdigest()
    if browser.get('current_snapshot_full_browser_retest_complete') and browser['current_snapshot_sha256'] == normalized_hash:
        summary.update(browser_render_checked=True, browser_evidence='user_supplied_actual_browser_DOM_report',
                       browser_questions_checked=browser['unique_questions_rendered'],
                       browser_viewport_width=browser['viewport_width'], browser_report_path=browser['report_path'],
                       browser_preview_limit='工具未直接读取file协议页面；实际DOM检查证据来自用户浏览器报告，并已按题号、摘要及计数复核。')
(ROOT/('data/reports/main_preview_check.json' if args.main else 'data/reports/image_preview_check.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True))
