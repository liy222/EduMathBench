"""Validate and archive actual user-browser observations for the current input snapshot."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/reports/luna_render_audit'


def main():
    provided = Path('C:/Users/liyh/Downloads/EduMathBench_render_check (1).json')
    report = json.loads(provided.read_text(encoding='utf-8-sig'))
    input_path = ROOT / 'data/normalized/questions.jsonl'
    questions = {q['id']: q for q in map(json.loads, input_path.read_text(encoding='utf-8').splitlines())}
    sha = hashlib.sha256(input_path.read_bytes()).hexdigest()
    items = report['items']
    assert report['inputSha256'] == sha and report['status'] == 'completed'
    assert len(items) == len(questions) == 1500 and len({r['id'] for r in items}) == 1500
    assert set(questions) == {r['id'] for r in items}
    assert report['questionsChecked'] == report['uniqueQuestionIds'] == report['renderedQuestionStates'] == 1500
    for row in items:
        q = questions[row['id']]
        assert row['renderedId'] == q['id'] and row['status'] == 'checked' and not row['issues']
        assert row['questionPresent'] and row['optionCount'] == 4 and all(row['optionsPresent'])
        assert row['katexErrorCount'] == row['residualDollarCount'] == 0 and not row['residualMathCommands']
        assert len(row['images']) == row['expectedImageCount'] == len(q.get('image_assets', []))
        assert all(a['loaded'] and a['naturalWidth'] > 0 and a['naturalHeight'] > 0 and a['renderedWidth'] > 0 and a['renderedHeight'] > 0 for a in row['images'])
        assert not row['horizontalOverflow'] and not row['possibleClippingNeedsReview']
    assert sum(r['katexNodeCount'] for r in items) == report['katexNodeCount'] == 7703
    assert sum(len(r['images']) for r in items) == report['imageElementsObserved'] == 219
    assert sum(len(r['tables']) for r in items) == report['tablesObserved'] == 9
    assert sum(t['cells'] for r in items for t in r['tables']) == report['tableCellsObserved'] == 152
    assert report['issueQuestionCount'] == 0 and not report['executionErrors'] and not report['externalResourceRequests']
    old_summary_path = BASE / 'browser_report_verified_summary.json'
    old = json.loads(old_summary_path.read_text(encoding='utf-8'))
    if old.get('browser_retest_pending_ids'):
        (BASE / 'browser_report_verified_summary_v1.json').write_bytes(old_summary_path.read_bytes())
    (BASE / 'browser_report_20261014_v1_1.json').write_bytes(provided.read_bytes())
    summary = {'validated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
               'report_path': 'data/reports/luna_render_audit/browser_report_20261014_v1_1.json',
               'report_sha256': hashlib.sha256(provided.read_bytes()).hexdigest(),
               'report_snapshot_sha256': sha, 'current_snapshot_sha256': sha,
               'user_browser_report_verified': True, 'browser_name': 'Microsoft Edge',
               'browser_user_agent': report['browserUserAgent'], 'viewport_width': report['viewportWidth'],
               'browser_started_at': report['startedAt'], 'browser_finished_at': report['finishedAt'],
               'unique_questions_rendered': 1500, 'katex_nodes': 7703, 'image_references': 219,
               'tables': 9, 'table_cells': 152, 'execution_errors': 0, 'formula_errors': 0,
               'image_load_errors': 0, 'horizontal_overflow_records': 0, 'possible_clipping_records': 0,
               'reported_prose_format_anomalies': 0, 'historical_repaired_input_records': 5,
               'unchanged_render_input_records': 1500, 'browser_retest_pending_ids': [],
               'current_snapshot_full_browser_retest_complete': True,
               'scope': '用户提供的真实浏览器全库逐题DOM检查；当前Edge/1409px下通过，不是逐题人工像素检查、数学验算或所有视口保证。'}
    old_summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (BASE / 'browser_report_current_result.md').write_text(f'''# 修复版全库浏览器DOM检查通过

2026-10-14收到用户第二份浏览器运行报告，输入摘要与当前question-format-v1.1完全一致：{sha}。

实际覆盖1500个唯一题号，逐题DOM ID与预期一致，四选项均存在；7703个KaTeX节点、219次图片引用、9张表格152格对应。当前Edge浏览器、1409px视口下，题面命令残留、公式解析错误、图片加载失败、容器横向溢出、疑似裁切、执行异常和外部请求均为0。先前5题已补验通过，待补验清单为空。

报告已原样归档为browser_report_20261014_v1_1.json，主代理逐题及聚合核对通过。Luna独立复核见browser_report_review_v1_1.md。初次报告及5题修复记录保留，不覆盖历史证据。

这是实际浏览器DOM检查结论，只适用于所记录的浏览器和宽度；不等于逐题人工视觉审阅、其他视口或数学正确性保证。可从完整1500题中开展下一阶段母题筛选，当前仍未生成变式。
''', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
