"""Collect the published, rewritten CJEval math MCQs with immutable source provenance."""
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from check_collection import write_jsonl, INFORMATION_FLAGS

ROOT = Path(__file__).resolve().parents[1]
BATCH = 'bulk_cjeval_001'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def split_choices(content):
    if not isinstance(content, str):
        return json.dumps(content, ensure_ascii=False), [''] * 4, ['source_content_type_unexpected']
    markers = list(re.finditer(r'选项\s*[:：]', content))
    if not markers:
        return content, [''] * 4, ['option_separator_missing']
    marker = markers[-1]
    question, options = content[:marker.start()].strip(), content[marker.end():]
    bullets = list(re.finditer(r'(?<![A-Za-z])([A-D])[.．、:：]\s*', options))
    if len(bullets) != 4 or set(m.group(1) for m in bullets) != set('ABCD'):
        return question, [''] * 4, ['four_option_parse_uncertain']
    by_label = {m.group(1): options[m.end():bullets[i + 1].start() if i < 3 else len(options)].strip()
                for i, m in enumerate(bullets)}
    choices = [by_label[c] for c in 'ABCD']
    return question, choices, []


def main():
    classifier = load_module('cmm_curriculum', ROOT / 'data/bulk_work/cmm_label_rules.py')
    auditor = load_module('structural_audit', ROOT / 'data/bulk_work/structure_audit_rules.py')
    manifests = json.loads((ROOT / 'data/bulk_probe/cjeval_manifest.json').read_text(encoding='utf-8'))
    sources, candidates, labels = [], [], []
    for manifest in manifests:
        if not manifest['file'].endswith('.json'):
            continue
        split = manifest['file'].split('/')[-2].upper()
        sid = 'SRC-CJEVAL-' + split
        sources.append({'source_id': sid, 'title': 'CJEval 初中数学 / ' + split,
                        'url': manifest['url'], 'year': 'unknown', 'region': 'unknown',
                        'source_exam_grade': '初中，未公布具体试卷年级',
                        'answer_location': '对应原JSON行ques_answer数组（单选单字母）',
                        'raw_path': manifest['local_path'], 'accessed_at': manifest['accessed_at'],
                        'access_status': 'downloaded_public_dataset',
                        'reuse_status': 'academic_research_only_noncommercial',
                        'revision': manifest['revision'], 'sha256': manifest['sha256'],
                        'notes': '官方公开数据集，基于实际初中试题经改写审核；仅学术研究，禁止商业使用。不是原试卷原文，未逐题追溯原试卷。保留原数据集题目与答案，知识和难度尚待复核。'})
        raw = ROOT / manifest['local_path']
        for line_no, line in enumerate(raw.read_text(encoding='utf-8-sig').splitlines(), 1):
            original = json.loads(line)
            if original.get('ques_type') != '单选题':
                continue
            question, choices, flags = split_choices(original['ques_content'])
            answers = original.get('ques_answer', [])
            answer = answers[0] if len(answers) == 1 and answers[0] in list('ABCD') else 'pending'
            q = {'id': f'EMB-P-CJEVAL-{split}-{line_no:06}', 'question': question,
                 **dict(zip(['option_' + c for c in 'abcd'], choices)), 'answer': answer,
                 'difficulty': 'pending', 'source_difficulty': original.get('ques_difficulty'),
                 'source_id': sid, 'source_ref': f"{manifest['file']}；原第{line_no}行；ques_answer字段",
                 'source_type': 'public', 'batch_id': BATCH, 'source_exam_grade': 'pending',
                 'source_question_kind': 'dataset_rewritten_exam', 'source_original_paper_verified': False,
                 'source_knowledge_points': original.get('ques_knowledges', []),
                 'solution': original.get('ques_analyze', ''),
                 'provenance': {**manifest, 'line': line_no, 'original_record': original}}
            label = classifier.classify(q)
            # Source knowledge tags are recorded as an independent classification cue.
            knowledge = '；'.join(q['source_knowledge_points'])
            stronger = None
            if '分式方程' in knowledge and ('方程' in question or '方程' in knowledge):
                stronger = (8, '方程与不等式', '分式方程')
            elif '二次函数' in knowledge or '抛物线' in knowledge:
                stronger = (9, '函数', '二次函数')
            elif '反比例函数' in knowledge:
                stronger = (9, '函数', '反比例函数')
            elif '一次函数' in knowledge or '正比例函数' in knowledge:
                stronger = (8, '函数', '一次函数')
            elif '一元二次方程' in knowledge:
                stronger = (9, '方程与不等式', '一元二次方程')
            elif '二次根式' in knowledge:
                stronger = (8, '数与式', '二次根式')
            if stronger:
                label.update(grade=str(stronger[0]), module=stronger[1], knowledge_point=stronger[2])
                label['risk_flags'] = [f for f in label['risk_flags'] if f != 'primary_or_competition_scope']
                label['reason'] = '结合来源知识标签暂定主知识：' + knowledge
            q.update(grade=int(label['grade']) if label['grade'] in ['7', '8', '9'] else 'pending',
                     module=label['module'], knowledge_point=label['knowledge_point'])
            audit = auditor.audit(q)
            flags += label['risk_flags'] + audit['risk_flags']
            if re.search(r'<ImageHere>|图略|由图可知|下列.*图形|以下.*图形|如图|下图|图中|见图', q['question'] + ' '.join(choices)):
                flags.append('figure_dependency_unverified')
            if answer in list('ABCD') and sum(choice == choices[list('ABCD').index(answer)] for choice in choices) > 1:
                flags.append('duplicate_correct_options')
            q['risk_flags'] = list(dict.fromkeys(flags + ['secondary_source', 'math_not_reviewed', 'curriculum_version_unconfirmed']))
            q['classification_annotation'], q['structure_annotation'] = label, audit
            q['status'] = 'collected' if not flags and q['grade'] != 'pending' else 'needs_review'
            q['review_method'] = 'source_knowledge_and_text_rules_with_structure_audit'
            candidates.append(q)
            labels.append(label)
    work = ROOT / 'data/cjeval_work'
    write_jsonl(work / 'inventory.jsonl', candidates)
    write_jsonl(work / 'labels.jsonl', labels)
    exclusions_path = work / 'quality_exclusions.jsonl'
    exclusions = {r['id']: r for r in [json.loads(x) for x in exclusions_path.read_text(encoding='utf-8').splitlines() if x.strip()]} if exclusions_path.exists() else {}
    for q in candidates:
        e = exclusions.get(q['id'])
        if not e:
            continue
        q['quality_annotation'] = e
        remaining_flags = list(e['risk_flags'])
        if 'curriculum_label_error' in remaining_flags and str(e.get('expected_grade')) in ['7', '8', '9'] and e.get('expected_module') and e.get('expected_knowledge_point'):
            q.update(grade=int(e['expected_grade']), module=e['expected_module'], knowledge_point=e['expected_knowledge_point'])
            q['label_resolution'] = {'decision': 'correct_curriculum_labels_only', 'reason': e['reason'], 'reviewer': 'independent_quality_review'}
            remaining_flags.remove('curriculum_label_error')
            q['risk_flags'] = [f for f in q['risk_flags'] if f not in {'primary_or_competition_scope', 'subject_text_mismatch', 'out_of_scope'}]
        q['risk_flags'] = list(dict.fromkeys(q['risk_flags'] + remaining_flags))
        q['status'] = 'rejected' if e.get('disposition') == 'reject' else ('needs_review' if any(f not in INFORMATION_FLAGS for f in q['risk_flags']) or q['grade'] == 'pending' else 'collected')
    write_jsonl(ROOT / 'data/batches' / BATCH / 'sources.jsonl', sources)
    write_jsonl(ROOT / 'data/batches' / BATCH / 'questions.jsonl', candidates)
    summary = {'single_choice_candidates': len(candidates), 'status': dict(Counter(q['status'] for q in candidates)),
               'source_files': len(sources), 'source_kind': 'published_rewritten_exam_dataset'}
    (work / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
