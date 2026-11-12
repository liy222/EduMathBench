"""将技能导出的本地页面补齐离线字体；保持题库数据不变。"""
import base64
import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / '可视化/题库浏览.html'
ASSETS = ROOT / 'data/reports/visualization_assets'


class FrameParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag == 'iframe':
            self.frame = dict(attrs)['data-srcdoc']


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--page', type=Path, default=PAGE)
    cli.add_argument('--questions', type=Path, default=ROOT / 'data/public_draft/questions.jsonl')
    cli.add_argument('--instructions', type=Path)
    args = cli.parse_args()
    page = args.page
    text = page.read_text(encoding='utf-8')
    parser = FrameParser()
    parser.feed(text)
    inner = parser.frame
    pattern = r'src:url\(https://cdn\.jsdelivr\.net/npm/katex@0\.16\.11/dist/fonts/([^()]+\.woff2)\)\s*format\("woff2"\)(?:,[^;}]+)?'
    count = 0

    def replace(match):
        nonlocal count
        count += 1
        font = (ASSETS / 'fonts' / match.group(1)).read_bytes()
        encoded = base64.b64encode(font).decode('ascii')
        return 'src:url(data:font/woff2;base64,' + encoded + ')format("woff2")'

    inner = re.sub(pattern, replace, inner)
    assert count == 20, '离线字体数不匹配'
    inner = re.sub(r'<script\b[^>]*\bsrc="https://unpkg\.com/[^"\n]+"[^>]*>\s*</script>', '', inner)
    assert 'cdn.jsdelivr.net/npm/katex@0.16.11/dist/fonts/' not in inner
    assert not re.search(r'<(?:script|link)[^>]+(?:src|href)="https?://', inner)
    questions = [json.loads(line) for line in args.questions.read_text(encoding='utf-8').splitlines()]
    evidence = {q['id']: q.get('difficulty_annotation', {}) for q in questions}
    payload = json.dumps(evidence, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    script = (ROOT / 'data/visualization/difficulty_detail.js').read_text(encoding='utf-8')
    extra = '<script type="application/json" id="emb-difficulty-evidence">' + payload + '</script><script>' + script + '</script>'
    inner = inner.replace('</body>', extra + '</body>')
    original = re.search(r'data-srcdoc="[^"]*"', text)
    assert original
    text = text[:original.start()] + 'data-srcdoc="' + html.escape(inner, quote=True) + '"' + text[original.end():]
    text = text.replace('sandbox="allow-scripts"', 'sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"')
    license_text = (ASSETS / 'KaTeX-LICENSE.txt').read_text(encoding='utf-8').replace('--', '—')
    text += '\n<!-- KaTeX 0.16.11 license\n' + license_text + '\n-->\n'
    if page == PAGE and (page.parent / '图像题浏览.html').is_file():
        nav = '<nav id="emb-local-nav" style="padding:12px 16px;font-family:system-ui"><a href="图像题浏览.html">首批4道图像题历史示例</a></nav>'
        text = re.sub(r'(<body\b[^>]*>)', lambda m: m[1] + nav, text, count=1)
    page.write_text(text, encoding='utf-8')
    (args.instructions or page.parent / '使用说明.txt').write_text(
        'EduMathBench 本地题库\n\n'
        f'双击“{page.name}”，用 Edge 或 Chrome 打开即可。\n'
        f'页面内置{len(questions)}道题、图表、公式排版及字体，可离线使用，无需安装程序或启动服务。\n'
        '可按年级、模块、难度筛选，翻页查看题目，展开来源答案及暂定难度依据。点击来源网址时需要联网。\n'
        '题目状态为初版、待集中复核，来源答案不等于已经独立数学验算。\n'
        '题图随页面内置；这是当前所选题的快照，后续更新时需要重新导出页面。\n', encoding='utf-8')
    print({'local_page': str(page), 'embedded_fonts': count, 'bytes': page.stat().st_size})


if __name__ == '__main__':
    main()
