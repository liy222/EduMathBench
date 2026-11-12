"""Validate the user-provided browser observations against their exact input snapshot."""
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/reports/luna_render_audit'


def rows(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]


def main():
    report_path = BASE / 'browser_report_20261014_v1.json'
    report = json.loads(report_path.read_text(encoding='utf-8-sig'))
    old_path = ROOT / 'data/normalized/history/questions_question-format-v1.jsonl'
    current_path = ROOT / 'data/normalized/questions.jsonl'
    old = {q['id']: q for q in rows(old_path)}
    current = {q['id']: q for q in rows(current_path)}
    assert hashlib.sha256(old_path.read_bytes()).hexdigest() == report['inputSha256']
    items = report['items']
    assert report['status'] == 'completed' and len(items) == 1500
    assert set(old) == set(current) == {item['id'] for item in items}
    assert len({item['id'] for item in items}) == len(items)
    assert all(item.get('renderedId') == item['id'] for item in items)
    assert all(item['questionPresent'] and item['optionCount'] == 4 and all(item['optionsPresent']) for item in items)
    assert sum(item['katexNodeCount'] for item in items) == report['katexNodeCount'] == 7703
    assert sum(len(item['images']) for item in items) == report['imageElementsObserved'] == 219
    assert all(image['loaded'] and image['naturalWidth'] > 0 and image['renderedWidth'] > 0 for item in items for image in item['images'])
    assert sum(len(item['tables']) for item in items) == report['tablesObserved'] == 9
    assert sum(table['cells'] for item in items for table in item['tables']) == report['tableCellsObserved'] == 152
    assert not report['executionErrors'] and not report['externalResourceRequests']
    assert not any(item['katexErrorCount'] or item['horizontalOverflow'] or item['possibleClippingNeedsReview'] for item in items)
    affected = {item['id'] for item in items if item['issues']}
    assert len(affected) == report['issueQuestionCount'] == 5
    fields = ['question', 'option_a', 'option_b', 'option_c', 'option_d']
    changed = {qid for qid in current if any(current[qid][k] != old[qid][k] for k in fields)}
    assert changed == affected, 'Only the five reported prose-format anomalies may change'
    assert all(current[qid]['answer'] == old[qid]['answer'] for qid in current)
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    summary = {'validated_at': now, 'report_snapshot_sha256': report['inputSha256'],
               'current_snapshot_sha256': hashlib.sha256(current_path.read_bytes()).hexdigest(),
               'user_browser_report_verified': True, 'browser_name': 'Microsoft Edge',
               'browser_user_agent': report['browserUserAgent'], 'viewport_width': report['viewportWidth'],
               'browser_started_at': report['startedAt'], 'browser_finished_at': report['finishedAt'],
               'unique_questions_rendered': 1500, 'katex_nodes': 7703, 'image_references': 219,
               'tables': 9, 'table_cells': 152, 'execution_errors': 0, 'formula_errors': 0,
               'image_load_errors': 0, 'horizontal_overflow_records': 0, 'possible_clipping_records': 0,
               'reported_prose_format_anomalies': len(affected), 'repaired_input_records': len(changed),
               'unchanged_render_input_records': len(current) - len(changed),
               'browser_retest_pending_ids': sorted(changed), 'current_snapshot_full_browser_retest_complete': False,
               'scope': '用户提供的真实浏览器逐题DOM检查，主代理与Luna核对；不是逐题人工像素检查或数学验算。'}
    (BASE / 'browser_report_verified_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    table = '\n'.join('| ' + ' | '.join([qid, '正文排版命令已规范化', '需补验']) + ' |' for qid in sorted(changed))
    text = f'''# 浏览器报告核对与5题修复

2026-10-14收到用户实际运行的报告，已原样归档到browser_report_20261014_v1.json；报告输入摘要与旧快照严格匹配。Luna独立复核记录见browser_report_review.md。

Edge浏览器、1045px视口下实际覆盖1500个唯一题号，逐题DOM题号一致；7703个KaTeX节点、219次图片引用、9张表格152格全部对应。报告中公式错误、图片加载失败、横向溢出、疑似裁切、执行异常和外部请求均为0。1495题未报异常，5题报告正文命令残留。

修复：3个uline空白改为可见填空线____；emph中的变量x保留为x；正文中的ldots改为省略号……。只修正文，不改数学公式中的合法ldots，不改条件、数值、选项顺序和源答案。实际只修改这5题的题干，其他1495题的输入字段逐字不变；原文和规则仍单独保留。

| 题号 | 处置 | 当前浏览器状态 |
|---|---|---|
{table}

旧实测输入摘要：{report['inputSha256']}。

当前修复输入摘要：{summary['current_snapshot_sha256']}。

修复版全库自动格式检查已通过，5题仍需真实浏览器补验，不能将旧报告当作修复版全库无异常证明。更新后的可视化/渲染检查.html可用于补验；运行报告只覆盖实际浏览器版本和视口，不保证其他宽度或数学正确性。下一步母题计划可先从其余1495题中开展，暂不选这5题。
'''
    (BASE / 'browser_report_resolution.md').write_text(text, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
