"""Verify the offline checker package, without claiming a browser execution."""
import base64
import hashlib
import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from bs4 import BeautifulSoup
from question_format import canonical_question

ROOT = Path(__file__).resolve().parents[1]


class FrameParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag == 'iframe':
            values = dict(attrs)
            if 'data-srcdoc' in values:
                self.inner = values['data-srcdoc']


def inner_document(path):
    text = path.read_text(encoding='utf-8')
    parser = FrameParser()
    parser.feed(text)
    return getattr(parser, 'inner', text)


def main():
    main_page = ROOT / '可视化/题库浏览.html'
    checker = ROOT / '可视化/渲染检查.html'
    checker_frame = FrameParser()
    checker_frame.feed(checker.read_text(encoding='utf-8'))
    assert 'allow-downloads' in checker.read_text(encoding='utf-8'), 'Report download needs the checker iframe permission'
    main_html, checker_html = inner_document(main_page), inner_document(checker)
    main_soup, checker_soup = BeautifulSoup(main_html, 'html.parser'), BeautifulSoup(checker_html, 'html.parser')
    original_styles = [s.get_text() for s in main_soup.find_all('style')]
    checker_styles = [s.get_text() for s in checker_soup.find_all('style')]
    assert all(style in checker_styles for style in original_styles), 'Checker must preserve actual question-page styles'
    assert checker_html.count('data:font/woff2;base64,') == 20
    assert not checker_soup.select('script[src],link[href^="http"]')
    embedded = json.loads(checker_soup.find('script', id='emb-data').string)[0]
    native = [json.loads(s) for s in (ROOT / 'data/public_draft/questions.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(embedded) == len(native) == 1500
    image_count = 0
    for displayed, q in zip(embedded, native):
        expected = canonical_question(q)
        assert displayed[:10] == [expected['id'], expected['question'], *[expected['option_' + c] for c in 'abcd'], q['answer'], q['grade'], q['module'], q['difficulty']]
        assert len(displayed[13]) == len(q.get('image_assets', []))
        for d, a in zip(displayed[13], q.get('image_assets', [])):
            assert hashlib.sha256(base64.b64decode(d['src'].split(',', 1)[1])).hexdigest() == a['sha256']
            assert d['role'] == a['role']
            image_count += 1
    scripts = [e.get_text() for e in checker_soup.find_all('script') if e.get('type') != 'application/json']
    for script in scripts:
        result = subprocess.run(['node', '-e', 'new Function(require("fs").readFileSync(0,"utf8"));'], input=script, text=True, capture_output=True, encoding='utf-8')
        assert result.returncode == 0, result.stderr
    code = '\n'.join(scripts)
    assert '__lunaRenderAudit' in code and '__embAuditDraw' in code and 'document.fonts.ready' in code
    assert 'requestAnimationFrame' in code and 'naturalWidth' in code
    assert '.katex-mathml' in code and '.sr-only' in code
    static = json.loads((ROOT / 'data/reports/luna_render_audit/luna_render_audit_static.json').read_text(encoding='utf-8'))
    browser_evidence_path = ROOT / 'data/reports/luna_render_audit/browser_report_verified_summary.json'
    browser_evidence = json.loads(browser_evidence_path.read_text(encoding='utf-8')) if browser_evidence_path.exists() else {}
    current_sha = hashlib.sha256((ROOT / 'data/normalized/questions.jsonl').read_bytes()).hexdigest()
    user_render_verified = browser_evidence.get('current_snapshot_full_browser_retest_complete', False) and browser_evidence.get('current_snapshot_sha256') == current_sha
    assert static['table_question_count'] == 9 and static['table_cells_static_count'] == 152
    summary = {'checker_package_verified': True, 'snapshot_questions': len(embedded), 'embedded_image_references': image_count,
               'main_question_styles_preserved': len(original_styles), 'offline_fonts': 20,
               'inline_scripts_syntax_checked': len(scripts), 'table_questions': 9, 'table_cells': 152,
               'actual_browser_execution': 'user_report_verified' if user_render_verified else 'not_run',
               'actual_browser_questions_checked': 1500 if user_render_verified else 0,
               'agent_direct_browser_execution': False,
               'checker_sha256': hashlib.sha256(checker.read_bytes()).hexdigest()}
    (ROOT / 'data/reports/luna_render_audit/checker_package_verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
