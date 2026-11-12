"""核对本轮暂定难度附表的覆盖、范围与证据字段，不重新解题。"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def main():
    snapshot = read(ROOT / 'data/difficulty_work/input_public_questions_20261013.jsonl')
    expected = {q['id']: q for q in snapshot if q['difficulty'] == 'pending'}
    summary, errors, all_ids = [], [], []
    for grade in [7, 8, 9]:
        path = ROOT / f'data/annotations/difficulty_round2_g{grade}.jsonl'
        if not path.is_file():
            errors.append({'grade': grade, 'problem': 'missing_annotation_file'})
            continue
        rows = read(path)
        ids = [r.get('id') for r in rows]
        wanted = {key for key, q in expected.items() if q['grade'] == grade}
        if len(ids) != len(set(ids)):
            errors.append({'grade': grade, 'problem': 'duplicate_ids'})
        if set(ids) != wanted:
            errors.append({'grade': grade, 'problem': 'coverage_mismatch',
                           'missing': sorted(wanted - set(ids)), 'extra': sorted(set(ids) - wanted)})
        for row in rows:
            if row.get('difficulty') not in {'基础', '中等', '困难', 'pending'}:
                errors.append({'id': row.get('id'), 'problem': 'invalid_difficulty'})
            if not isinstance(row.get('reason'), str) or len(row['reason'].strip()) < 10:
                errors.append({'id': row.get('id'), 'problem': 'missing_specific_reason'})
            for key in ['model', 'annotated_at', 'review_method', 'rule_version', 'confidence']:
                if not row.get(key):
                    errors.append({'id': row.get('id'), 'problem': 'missing_' + key})
            if row.get('confidence') not in {'high', 'medium', 'low'}:
                errors.append({'id': row.get('id'), 'problem': 'invalid_confidence'})
        summary.append({'grade': grade, 'count': len(rows),
                        'difficulty_counts': dict(Counter(r.get('difficulty') for r in rows)),
                        'confidence_counts': dict(Counter(r.get('confidence') for r in rows))})
        all_ids.extend(ids)
    current = read(ROOT / 'data/public_draft/questions.jsonl')
    missing_basis = [q['id'] for q in current if not q.get('difficulty_annotation', {}).get('reason')]
    pending_ids = [q['id'] for q in current if q['difficulty'] == 'pending']
    if missing_basis:
        errors.append({'problem': 'current_missing_basis', 'ids': missing_basis})
    result = {'stage': '暂定难度附表核对，不等同于数学复核',
              'expected': len(expected), 'annotated': len(all_ids),
              'passed': not errors, 'grades': summary, 'errors': errors,
              'current_count': len(current), 'current_basis_count': len(current) - len(missing_basis),
              'current_difficulty_counts': dict(Counter(q['difficulty'] for q in current)),
              'current_pending_ids': pending_ids}
    (ROOT / 'data/reports/difficulty_annotation_audit.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
