"""Archive and classify official MathBench middle-level CN records; no generated questions."""
import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path
from select_bulk_collection import deduplicate, fill_quotas, read, answer_text
from check_collection import fingerprint, write_jsonl, INFORMATION_FLAGS

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://github.com/open-compass/MathBench/files/15384594/mathbench_v1.zip'


def label(q):
    topic = q['source_topic'].split('--')[-1]
    text = q['question']
    mapping = {
        'Real Numbers': (7, '数与式', '实数与有理数'),
        'Linear Equations in One Variable': (7, '方程与不等式', '一元一次方程'),
        'Linear Equations in Two Variables': (7, '方程与不等式', '二元一次方程及方程组'),
        'Basic Concepts of Inequalities': (7, '方程与不等式', '不等式及不等式组'),
        'Quadratic Equations in One Variable': (9, '方程与不等式', '一元二次方程'),
        'Linear Functions': (8, '函数', '一次函数'),
        'Inverse Proportion Functions': (9, '函数', '反比例函数'),
        'Quadratic Functions': (9, '函数', '二次函数'),
        'Basic Concepts of Geometry': (7, '几何', '几何初步'),
        'Basics of Triangles': (8, '几何', '三角形'),
        'Quadrilaterals': (8, '几何', '四边形'),
        'Basic Concepts of Circles': (9, '几何', '圆'),
        'Data Collection and Organization': (7, '统计与概率', '数据收集整理与描述'),
        'Data Analysis': (8, '统计与概率', '数据分析'),
        'Polynomials and Factorization': (8, '数与式', '整式乘除与因式分解'),
        'Fractions': (8, '数与式', '分式'),
    }
    grade, module, kp = mapping.get(topic, ('pending', 'pending', 'pending'))
    flags = []
    if topic == 'Polynomials and Factorization' and re.search('单项式|多项式|同类项|去括号|合并', text) and not re.search('因式分解|整式乘|整式除|相乘|相除|乘法|除法|乘以|除以|乘积|积的|商的', text):
        grade, kp = 7, '整式及整式加减'
    if topic == 'Fractions' and re.search('方程', text):
        if re.search(r'分式方程|\\frac\{[^}]*\}\{[^}]*[xy][^}]*\}', text):
            grade, module, kp = 8, '方程与不等式', '分式方程'
        else:
            grade, module, kp = 7, '方程与不等式', '一元一次方程'
    elif topic == 'Fractions' and not re.search(r'分式|[a-zA-Z]', text):
        flags.append('primary_scope_uncertain')
        grade = 'pending'
    if topic == 'Real Numbers' and re.search('质数|合数|最小公倍数|最大公约数|约数|倍数', text):
        flags.append('primary_scope_uncertain')
        grade = 'pending'
    if topic == 'Data Analysis' and re.search('概率|随机事件|摸球|掷骰|硬币', text):
        grade, kp = 9, '概率'
    if topic == 'Basics of Triangles' and re.search('内角和|外角', text) and not re.search('全等|勾股|等腰|等边|相似', text):
        grade, kp = 7, '三角形内角与外角'
    if re.search('相似|位似', text):
        grade, module, kp = 9, '几何', '相似与位似'
    if re.search(r'关于\s*轴|的坐标是\s*[，。]', text):
        flags.append('missing_math_content')
    return grade, module, kp, flags


def main():
    spec = importlib.util.spec_from_file_location('structural_audit', ROOT / 'data/bulk_work/structure_audit_rules.py')
    audit_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit_module)
    archive = ROOT / 'data/bulk_probe/raw/mathbench_v1.zip'
    batch = 'bulk_mathbench_001'
    sources, candidates = [], []
    from datetime import datetime, timezone, timedelta
    prior_sources = {s['source_id']: s for s in read(ROOT / 'data/batches' / batch / 'sources.jsonl')}
    # Reprocessing a local archive is not a new network acquisition.
    acquired_at = datetime.fromtimestamp(archive.stat().st_mtime, timezone(timedelta(hours=8))).isoformat()
    with zipfile.ZipFile(archive) as z:
        for subset in ['middle', 'middle_knowledge']:
            name = f'mathbench_v1/{subset}/single_choice_cn.jsonl'
            raw = ROOT / 'data/bulk_probe/raw' / name
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(z.read(name))
            sid = 'SRC-MATHBENCH-' + ('APP' if subset == 'middle' else 'THEORY')
            accessed_at = prior_sources.get(sid, {}).get('accessed_at') or acquired_at
            sources.append({'source_id': sid, 'title': 'MathBench v0.1.0 / ' + subset + ' / 中文四选题',
                            'url': URL, 'year': 2024, 'region': 'unknown', 'source_exam_grade': '初中（数据集学段）',
                            'raw_path': str(raw.relative_to(ROOT)), 'answer_location': name + '各行answer字段',
                            'accessed_at': accessed_at, 'access_status': 'downloaded_public_dataset',
                            'reuse_status': 'unknown', 'sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
                            'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                            'notes': '官方发布包。' + ('应用题，未逐题追溯原试卷。' if subset == 'middle' else '官方概念题子集，记录为理论/概念来源；未按考试题来源处理。') +
                                     '按主要知识暂定年级，来源分类不代表逐题校准；原答案不改。'})
            for i, line in enumerate(raw.read_text(encoding='utf-8').splitlines(), 1):
                original = json.loads(line)
                q = {'id': f'EMB-P-MATHBENCH-{subset.upper()}-{i:04}', 'question': original['question'],
                     **dict(zip(['option_' + c for c in 'abcd'], original['options'])),
                     'answer': original['answer'], 'source_topic': original['topic'], 'difficulty': 'pending',
                     'source_id': sid, 'source_ref': f'{name}；第{i}行；answer字段',
                     'source_type': 'public', 'source_exam_grade': 'pending', 'batch_id': batch,
                     'source_question_kind': 'application' if subset == 'middle' else 'theoretical_concept',
                     'provenance': {'dataset': 'MathBench', 'release': 'v0.1.0', 'file': name, 'line': i,
                                    'url': URL, 'original_record': original},
                     'solution': '', 'review_method': 'dataset_topic_mapping_and_structural_rules'}
                grade, module, kp, flags = label(q)
                q.update(grade=grade, module=module, knowledge_point=kp)
                audit = audit_module.audit(q)
                flags.extend(audit['risk_flags'])
                correct = q.get('option_' + q['answer'].lower())
                if sum(q.get('option_' + c) == correct for c in 'abcd') > 1:
                    flags.append('duplicate_correct_option')
                q['risk_flags'] = list(dict.fromkeys(flags + ['secondary_source', 'math_not_reviewed', 'curriculum_version_unconfirmed', 'reuse_unknown']))
                q['status'] = 'needs_review' if flags or grade == 'pending' else 'collected'
                q['structure_annotation'] = audit
                candidates.append(q)
    exclusions = {q['id']: q for q in read(ROOT / 'data/bulk_work/mathbench_quality_exclusions.jsonl')}
    for q in candidates:
        if q['id'] in exclusions:
            e = dict(exclusions[q['id']])
            if e.get('expected_grade') in ['7', '8', '9', 7, 8, 9] and e.get('expected_module') and e.get('expected_knowledge_point') and 'curriculum_label_error' in e['risk_flags']:
                q.update(grade=int(e['expected_grade']), module=e['expected_module'], knowledge_point=e['expected_knowledge_point'])
                q['label_resolution'] = {'reviewer_model': 'gpt-6.1-sol', 'reason': e['reason'], 'decision': 'correct_curriculum_labels_only'}
                e['risk_flags'] = [f for f in e['risk_flags'] if f != 'curriculum_label_error']
            q['quality_annotation'] = e
            q['risk_flags'] += e['risk_flags']
            if e['risk_flags']:
                q['status'] = 'rejected' if e['disposition'] == 'reject' else 'needs_review'
    unique, conflicts, duplicates = deduplicate(candidates)
    eligible = [q for q in unique if q['status'] == 'collected']
    held = [q for q in unique if q['status'] != 'collected'] + conflicts
    baseline = [q for q in read(ROOT / 'data/public_draft/questions.jsonl') if q['batch_id'] != batch]
    prior = {fingerprint(q, True): q for q in baseline}
    new, baseline_duplicates = [], []
    for q in eligible:
        previous = prior.get(fingerprint(q, True))
        if not previous:
            new.append(q)
        elif answer_text(previous) != answer_text(q):
            q['risk_flags'].append('source_answer_conflict')
            q['status'] = 'needs_review'
            held.append(q)
        else:
            baseline_duplicates.append(q)
    quotas = json.loads((ROOT / 'config/quotas.json').read_text(encoding='utf-8-sig'))
    selected, reserve = fill_quotas(new, quotas['cells'], baseline)
    exact_duplicates = [q for q in baseline_duplicates if fingerprint(q) == fingerprint(prior[fingerprint(q, True)])]
    target = ROOT / 'data/batches' / batch
    write_jsonl(target / 'sources.jsonl', sources)
    write_jsonl(target / 'questions.jsonl', selected + held + exact_duplicates)
    output = ROOT / 'data/mathbench_prepared'
    write_jsonl(output / 'all_candidates.jsonl', candidates)
    write_jsonl(output / 'reserve.jsonl', reserve)
    write_jsonl(output / 'duplicate_groups.jsonl', duplicates)
    write_jsonl(output / 'baseline_duplicates.jsonl', baseline_duplicates)
    summary = {'raw_candidates': len(candidates), 'selected_new': len(selected), 'reserve_unique': len(reserve),
               'held_or_rejected': len(held), 'baseline_duplicates': len(baseline_duplicates), 'source_files': len(sources)}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
