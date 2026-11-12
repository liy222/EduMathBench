"""Summarize the collected public draft; verify data and optional portable export."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zipfile import ZipFile
from question_format import canonical_question

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'data/reports'


def read(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main(check_export=False):
    src = ROOT / 'data/public_draft/questions.jsonl'
    rows = read(src)
    quotas = json.loads((ROOT / 'config/quotas.json').read_text(encoding='utf-8'))
    summary = json.loads((REPORTS / 'summary.json').read_text(encoding='utf-8'))
    provenance = json.loads((REPORTS / 'provenance_audit.json').read_text(encoding='utf-8'))
    preview = json.loads((REPORTS / 'main_preview_check.json').read_text(encoding='utf-8'))
    difficulty = Counter(q['difficulty'] for q in rows)
    modality = Counter('text_image' if q.get('image_assets') else 'text' for q in rows)
    hard_modality = Counter('text_image' if q.get('image_assets') else 'text' for q in rows if q['difficulty'] == '困难')
    grade_counts = Counter(q['grade'] for q in rows)
    grade_difficulty = {str(g): dict(Counter(q['difficulty'] for q in rows if q['grade'] == g)) for g in [7,8,9]}
    cells = Counter((q['grade'], q['module']) for q in rows)
    assert len(rows) == quotas['public_target'] == 1500
    assert len({q['id'] for q in rows}) == len(rows)
    assert all(cells[c['grade'], c['module']] == c['target'] for c in quotas['cells'])
    assert dict(difficulty) == quotas['difficulty_targets']
    assert all(q['status'] == 'auto_checked' and q['answer'] in 'ABCD' for q in rows)
    assert all(q.get('difficulty_annotation', {}).get('reason') for q in rows)
    assert all(q.get('difficulty_annotation', {}).get('difficulty', q['difficulty']) == q['difficulty'] for q in rows)
    assert all((ROOT / q['source_raw_path']).is_file() for q in rows)
    assert provenance['draft_sha256'] == digest(src.read_bytes())
    assert all(provenance[k] == 0 for k in ['literal_field_mismatches', 'metadata_issue_count',
               'additional_source_issue_count', 'additional_source_metadata_issue_count'])
    assert preview['count'] == len(rows) and preview['external_runtime_dependencies'] == 0
    assets = [a for q in rows for a in q.get('image_assets', [])]
    image_file_count = len({(a['sha256'], Path(a['path']).suffix.lower()) for a in assets})
    for a in assets:
        assert a['role'] in ['stem', 'option'] and a.get('contains_answer_or_solution', a.get('contains_answer')) is False
        assert digest((ROOT / a['path']).read_bytes()) == a['sha256']
    assert preview['embedded_images_match_archive'] == len(assets)
    assert not (REPORTS / 'presentation_duplicate_candidates.jsonl').read_text(encoding='utf-8').strip()
    baseline = read(ROOT / 'data/hard_collection/completion/baseline_1500.jsonl')
    baseline_by_id = {q['id']: q for q in baseline}
    retained = [q for q in rows if q['id'] in baseline_by_id]
    source_fields = ['question', 'option_a', 'option_b', 'option_c', 'option_d', 'answer', 'source_id', 'source_ref']
    assert all(all(q[k] == baseline_by_id[q['id']][k] for k in source_fields) for q in retained)
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    result = {'generated_at': now, 'count': len(rows), 'quota_remaining': summary['remaining'],
              'grade_counts': dict(grade_counts), 'difficulty_counts': dict(difficulty),
              'grade_difficulty_counts': grade_difficulty, 'input_modality_counts': dict(modality),
              'hard_modality_counts': dict(hard_modality), 'difficulty_basis_records': len(rows),
              'pending': difficulty['pending'], 'image_asset_count': len(assets), 'image_file_count': image_file_count,
              'retained_records_source_content_unchanged': len(retained),
              'newly_selected_records': len(rows) - len(retained), 'draft_sha256': digest(src.read_bytes()),
              'dataset_source_records_compared': provenance['dataset_record_count'],
              'dataset_source_mismatches': provenance['literal_field_mismatches'],
              'presentation_duplicate_groups': 0, 'offline_page_static_checked': True,
              'browser_render_checked': preview['browser_render_checked'],
              'state': '公开题收集初版，难度暂定，年级内部难度分布尚不均衡，未集中数学验算'}
    browser_summary_path = REPORTS / 'luna_render_audit/browser_report_verified_summary.json'
    browser_note = '当前版本尚无实际浏览器渲染报告。'
    if browser_summary_path.exists():
        browser_summary = json.loads(browser_summary_path.read_text(encoding='utf-8'))
        assert browser_summary['current_snapshot_sha256'] == digest((ROOT / 'data/normalized/questions.jsonl').read_bytes())
        result.update(previous_snapshot_browser_rendered=browser_summary['unique_questions_rendered'],
                      browser_verified_unchanged_input_records=browser_summary['unchanged_render_input_records'],
                      current_browser_retest_pending_ids=browser_summary['browser_retest_pending_ids'],
                      current_browser_snapshot_complete=browser_summary['current_snapshot_full_browser_retest_complete'])
        if browser_summary['current_snapshot_full_browser_retest_complete']:
            result.update(browser_report_path=browser_summary['report_path'],
                          browser_viewport_width=browser_summary['viewport_width'])
            browser_note = '用户提供的修复版实际浏览器DOM报告与当前输入摘要完全一致，覆盖1500题、7703个公式节点、219次图片引用、9表152格；Edge的1409px视口下无残留命令、公式错误、缺图、横向溢出、疑似裁切或执行异常，先前5题补验通过。该结论不代替逐题人工视觉审阅、其他视口或数学验算。'
        else:
            browser_note = '用户提供的原规范化版本实际浏览器DOM报告覆盖1500题，在Edge的1045px视口下无公式、图片、表格或溢出异常，但有5处正文宏残留；修复版只改这5题，其余1495题输入不变，5题真实浏览器补验尚未完成。'
    if check_export:
        out = ROOT / 'data/exports'
        manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
        assert manifest['source_draft_sha256'] == result['draft_sha256']
        assert manifest['count'] == 1500 and manifest['difficulty_counts'] == dict(difficulty)
        name = 'EduMathBench_public_draft_v0.1'
        exported = read(out / (name + '.jsonl'))
        with (out / (name + '.csv')).open(encoding='utf-8-sig', newline='') as f:
            csv_rows = list(csv.DictReader(f))
        assert len(exported) == len(csv_rows) == len(rows)
        for q, e, c in zip(rows, exported, csv_rows):
            canonical = canonical_question(q)
            assert q['id'] == e['id'] == c['id']
            assert canonical['question'] == e['question'] == c['question']
            assert q['answer'] == e['answer'] == c['answer']
            for letter in 'ABCD':
                assert canonical['option_' + letter.lower()] == e['options'][letter] == c['option_' + letter.lower()]
            assert e['source_input'] == canonical['source_input'] == json.loads(c['source_input'])
            assert e['format_normalization'] == canonical['format_normalization'] == json.loads(c['format_normalization'])
            assert e['source']['reference'] == q['source_ref'] == c['source_reference']
            for key in ['image_assets', 'difficulty_annotation', 'quality_annotation']:
                assert json.loads(c[key]) == e[key]
            assert len(e['image_assets']) == len(q.get('image_assets', []))
            assert all(a['sha256'] == b['sha256'] for a, b in zip(e['image_assets'], q.get('image_assets', [])))
        with ZipFile(out / (name + '.zip')) as archive:
            assert archive.testzip() is None
            for record in manifest['files'] + manifest['images']:
                data = archive.read(record['name'])
                assert len(data) == record['bytes'] and digest(data) == record['sha256']
                assert data == (out / record['name']).read_bytes()
            for q in exported:
                for a in q['image_assets']:
                    assert digest(archive.read(a['path'])) == a['sha256']
        result.update(roundtrip_verified=1500, zip_crc_passed=True, export_hashes_passed=True,
                      portable_image_files=manifest['image_file_count'])
        format_audit = json.loads((REPORTS / 'canonical_question_format_audit.json').read_text(encoding='utf-8'))
        assert format_audit['question_count'] == len(rows) and format_audit['issue_count'] == 0 and format_audit['font_warning_count'] == 0
        assert format_audit['input_sha256'] == digest((ROOT / format_audit['input_path']).read_bytes())
        result.update(format_fields_checked=format_audit['fields_checked'], formulas_checked=format_audit['formulas_checked'],
                      formula_parse_errors=0, font_warnings=0, source_input_preserved=True)
        (REPORTS / 'final_collection_check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True))
        return

    table = '\n'.join('| ' + ' | '.join(str(v) for v in [g, *[grade_difficulty[str(g)].get(d, 0) for d in ['基础', '中等', '困难']], grade_counts[g]]) + ' |' for g in [7,8,9])
    difficulty_report = f'''# 暂定难度整理结果

2026-10-14完成本轮公开题收集与困难覆盖补充：1500题，基础600、中等600、困难300，待定0；每题均有暂定难度和具体判断依据。各年级500题及全部模块数量配额满足。

| 年级 | 基础 | 中等 | 困难 | 合计 |
|---|---:|---:|---:|---:|
{table}

全库难度比例达到设计目标，各年级内部未达到约200/200/100的分布。困难题包含{hard_modality['text']}道纯文字与{hard_modality['text_image']}道含图。图像题是扩充候选范围的可选项，纯文字补采一直保留。

采用公开整包、公开压轴专题和考试材料采集，同年级、同模块替换过量基础或中等题；不为补足比例抬高旧题标签。来源专题证据、来源原始标签和模型题面判断分开保存，不能把数据集出处冒充逐题官方困难认定。无需教师或学生正确率、用时采集作为本轮前置条件。

难度是暂定标签，未得到学生实测校准，结构与来源核对也不等于全库数学验算。旧版2026-10-13的759/678/63分布及整理记录归档在data/difficulty_work/difficulty_review_20261013.md，不能用于当前统计。

通用导出：data/exports/EduMathBench_public_draft_v0.1.zip。本地页面：可视化/题库浏览.html。完整检查范围见data/reports/completion_report.md及final_collection_check.json。
'''
    (REPORTS / 'difficulty_review.md').write_text(difficulty_report, encoding='utf-8')
    report = f'''# 公开题收集初版完成记录

时间：{now}。本轮完成实施计划中的1500道公开题收集及通用格式交付；300道变式与后续模型评测尚未启动。

1500题，七、八、九年级各500题，所有年级模块数量配额满足。基础600、中等600、困难300，难度待定0。主库包含{modality['text']}道纯文字与{modality['text_image']}道含图，共{image_file_count}个独立原题输入图片文件、{len(assets)}次图片引用；困难题中{hard_modality['text']}道纯文字、{hard_modality['text_image']}道含图。

| 年级 | 基础 | 中等 | 困难 | 合计 |
|---|---:|---:|---:|---:|
{table}

全库难度比例已齐，年级内部难度分布尚不均衡。标签为来源证据支持或模型依据题面任务的暂定判断，没有学生实测校准。各年级的主要知识归属与来源试卷年级分开记录。

每题保留来源标题、网址、题号或页面定位、答案位置、原件路径；数据集题保留锁定版本与原记录定位。原始材料留在项目内，ZIP附带可移植的题目图片。CMM-Math、CMMaTH、TAL、MathBench等二手数据集未逐题核实原试卷；来源复用说明保留。

## 已完成的核对

- 1500题的唯一题号、四选项、答案字母、原件路径、年级模块配额与难度依据检查通过。
- {provenance['dataset_record_count']}道数据集题逐字段对照原记录，题面、选项、源答案差异0；元数据问题0。其余网页/PDF按提取流程及原页抽查核对，未宣称全库逐题独立验算。
- 全库精确去重及选项重排检查完成；额外按公式分隔符、空格和图片占位符归一化查找，当前明显同文组0，不能据此宣称数值改写或题族近重复全部排除。
- 本轮保留原基线{len(retained)}题的题干、四项、源答案与来源定位不变，新入选{len(rows)-len(retained)}题；替换记录保存在data/hard_collection/completion/substitutions.jsonl。
- {len(assets)}个输入图片均存在且SHA-256一致；角色仅为题干或选项，解析图与答案图不作为输入。少数源占位字段错放有专项角色修正记录。
- 对新增CMMaTH批次抽查15题，发现的一组同题已合并并以同年级模块候补补齐；相关但命题不同的题保留共同family_id。两题源解析笔误及一题源解析为空已有专项数学推导记录，保留源答案与原解析；这些处理不要求用户安排教师复核。原抽查报告与处理记录分别在data/reports/final_hard_sample_audit.json、data/resolutions/final_cmmath_sample.jsonl和data/annotations/quality_admission_final_sample.jsonl。
- 本地页面内置1500题、{len(assets)}个输入图片及20个公式字体，无外部运行依赖；静态数据、图片与9段脚本语法检查通过。{browser_note}
- 用户反馈格式问题后，增加全库题干和四选项的逐公式解析及表格结构检查。当前页面与通用导出使用data/normalized/questions.jsonl的同一规范化输入；原始主库及源答案不改写。格式检查范围和逐项规则见data/reports/format_check.md，不能把公式解析通过当成全库数学验算或浏览器逐页视觉检查。
- 通用JSONL/CSV逐题往返核对、ZIP完整性与图片摘要的最终结果见项目data/reports/final_collection_check.json。

## 交付及范围

双击可视化/题库浏览.html可在本地浏览；题目、图片、公式字体已内置，访问外部来源网址需联网。首批4道图像题浏览页仅为历史示例，不另加到1500题数量。

通用包：data/exports/EduMathBench_public_draft_v0.1.zip。含JSONL、CSV、来源索引、images、字段说明、收集报告及SHA-256清单。答案和解析与模型输入分开取用；source_raw_path指向本项目原始材料，并非ZIP内路径。

主库状态为auto_checked，只说明结构、来源字段和已记录的专项问题检查通过。{summary['needs_review']}道异常候选未入主库，{summary['quota_reserve_count']}道结构通过候补未计入完成数；不以下载量或异常候选数量冒充完成量。数学正确性、教材适配、年级内部难度均衡及近重复题族尚未定稿。
'''
    (REPORTS / 'completion_report.md').write_text(report, encoding='utf-8')
    print(json.dumps({k: result[k] for k in ['count', 'difficulty_counts', 'input_modality_counts', 'hard_modality_counts', 'retained_records_source_content_unchanged']}, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-export', action='store_true')
    main(parser.parse_args().check_export)
