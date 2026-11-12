"""Import only C-Eval rows whose preview revision matches the archived publisher files."""
import json
from collections import Counter
from pathlib import Path
from prepare_cjeval_collection import load_module
from check_collection import write_jsonl, INFORMATION_FLAGS

ROOT = Path(__file__).resolve().parents[1]


def main():
    classifier = load_module('curriculum', ROOT / 'data/bulk_work/cmm_label_rules.py')
    auditor = load_module('structural_audit', ROOT / 'data/bulk_work/structure_audit_rules.py')
    manifests = json.loads((ROOT / 'data/bulk_probe/ceval_row_manifest.json').read_text(encoding='utf-8'))
    sources, questions = [], []
    for m in manifests:
        split = m['split'].upper()
        sid = 'SRC-CEVAL-MIDDLE-' + split
        sources.append({'source_id': sid, 'title': 'C-Eval 初中数学 / ' + split,
                        'url': f"https://huggingface.co/datasets/ceval/ceval-exam/resolve/{m['revision']}/{m['source_parquet_path']}",
                        'year': 'unknown', 'region': 'unknown', 'source_exam_grade': '初中',
                        'answer_location': 'middle_school_mathematics对应split的原id与answer字段',
                        'raw_path': m['local_path'], 'accessed_at': m['accessed_at'],
                        'reuse_status': 'CC-BY-NC-SA-4.0', 'access_status': 'downloaded_public_dataset',
                        'revision': m['revision'], 'sha256': m['sha256'], 'preview_pages': m['pages'],
                        'notes': '官方数学题与参考答案。原Parquet另有存档；逐页官方预览x-revision与锁定版本一致。' +
                                 m.get('subset_note', '仅该split成功读取的完整预览行；没有补猜未取得内容。') +
                                 '不声称原试卷来源逐题已验证；原字段不修改，数学正确性待复核。'})
        for line in (ROOT / m['local_path']).read_text(encoding='utf-8').splitlines():
            original = json.loads(line)
            q = {'id': f"EMB-P-CEVAL-{split}-{original['id']:06}", 'question': original['question'],
                 **{'option_' + c.lower(): original[c] for c in 'ABCD'}, 'answer': original['answer'],
                 'difficulty': 'pending', 'source_id': sid, 'source_type': 'public', 'source_exam_grade': 'pending',
                 'source_ref': f"{m['source_parquet_path']}；原id={original['id']}；answer字段",
                 'source_question_kind': 'published_exam_dataset', 'batch_id': 'bulk_ceval_001',
                 'solution': original.get('explanation', ''), 'provenance': {**m, 'original_record': original}}
            label, audit = classifier.classify(q), auditor.audit(q)
            q.update(grade=int(label['grade']) if label['grade'] in ['7', '8', '9'] else 'pending',
                     module=label['module'], knowledge_point=label['knowledge_point'])
            flags = label['risk_flags'] + audit['risk_flags']
            q['risk_flags'] = list(dict.fromkeys(flags + ['secondary_source', 'math_not_reviewed', 'curriculum_version_unconfirmed']))
            q['classification_annotation'], q['structure_annotation'] = label, audit
            q['status'] = 'needs_review' if flags or q['grade'] == 'pending' else 'collected'
            q['review_method'] = 'source_snapshot_with_rule_based_curriculum_and_structure_checks'
            questions.append(q)
    target = ROOT / 'data/batches/bulk_ceval_001'
    quality_path = ROOT / 'data/bulk_work/ceval_quality_exclusions.jsonl'
    exclusions = {e['id']: e for e in [json.loads(line) for line in quality_path.read_text(encoding='utf-8').splitlines() if line.strip()]} if quality_path.exists() else {}
    for q in questions:
        e = exclusions.get(q['id'])
        if not e:
            continue
        flags = list(e['risk_flags'])
        if 'curriculum_label_error' in flags and str(e.get('expected_grade')) in ['7', '8', '9'] and e.get('expected_module') and e.get('expected_knowledge_point'):
            q.update(grade=int(e['expected_grade']), module=e['expected_module'], knowledge_point=e['expected_knowledge_point'])
            q['label_resolution'] = {'decision': 'correct_curriculum_labels_only', 'reason': e['reason'], 'reviewer': 'independent_quality_review'}
            flags.remove('curriculum_label_error')
            q['risk_flags'] = [f for f in q['risk_flags'] if f not in {'primary_or_competition_scope', 'subject_text_mismatch', 'out_of_scope'}]
        q['quality_annotation'] = e
        q['risk_flags'] = list(dict.fromkeys(q['risk_flags'] + flags))
        q['status'] = 'rejected' if e.get('disposition') == 'reject' else ('needs_review' if any(f not in INFORMATION_FLAGS for f in q['risk_flags']) or q['grade'] == 'pending' else 'collected')
    write_jsonl(target / 'sources.jsonl', sources)
    write_jsonl(target / 'questions.jsonl', questions)
    (target / 'notes.md').write_text('# C-Eval初中数学补充来源\n\n'
        '仅导入已成功读取且返回版本号与原Parquet锁定版本相同的19条val和77条test尾部行。前100条test与dev预览临时502，不补猜。\n\n'
        '与MathBench/CMM存在内容重合，合并器处理完全重复并保留来源；近重复仍待集中审核。当前为规则标签和结构检查，未完成数学逐题复核。\n', encoding='utf-8')
    print(json.dumps({'verified_source_rows': len(questions), 'sources': len(sources), 'status': dict(Counter(q['status'] for q in questions))}, ensure_ascii=True))


if __name__ == '__main__':
    main()
