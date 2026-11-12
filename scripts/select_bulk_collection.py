"""Prepare traceable bulk candidates and fill curriculum quotas without overcounting downloads."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from check_collection import fingerprint, normalized, source_metadata, write_jsonl, INFORMATION_FLAGS

ROOT = Path(__file__).resolve().parents[1]
BATCH = 'bulk_001'


def read(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def answer_text(q):
    return normalized(q.get('option_' + str(q.get('answer', '')).lower(), ''))


def deduplicate(rows):
    """Same stem/options with different source answers must never enter the usable pool."""
    groups = defaultdict(list)
    for q in rows:
        groups[fingerprint(q, sorted_options=True)].append(q)
    unique, conflicts, duplicate_groups = [], [], []
    for group in groups.values():
        if len({answer_text(q) for q in group}) > 1:
            for q in group:
                q['status'] = 'needs_review'
                q['risk_flags'] = list(dict.fromkeys(q['risk_flags'] + ['source_answer_conflict']))
            conflicts.extend(group)
            continue
        # A clear classification/structure takes precedence over an uncertain copy.
        group.sort(key=lambda q: (q['status'] != 'collected', 'TAL' in q['id'], q['id']))
        primary = group[0]
        if len(group) > 1:
            primary['additional_sources'] = [provenance(q) for q in group[1:]]
            duplicate_groups.append({'primary_id': primary['id'], 'member_ids': [q['id'] for q in group],
                                     'reason': '题干及四个选项相同（含选项重排），答案所指选项一致。'})
        unique.append(primary)
    return unique, conflicts, duplicate_groups


def provenance(q):
    return {k: q.get(k) for k in ['id', 'source_id', 'source_ref', 'answer', 'batch_id',
                                  'provenance', 'source_title', 'source_url', 'source_raw_path']}


def fill_quotas(rows, cells, existing):
    used = Counter((q['grade'], q['module']) for q in existing)
    targets = {(c['grade'], c['module']): c['target'] for c in cells}
    selected, reserve = [], []
    for q in sorted(rows, key=lambda q: ('TAL' in q['id'], q['id'])):
        cell = (q['grade'], q['module'])
        if used[cell] < targets.get(cell, 0):
            selected.append(q)
            used[cell] += 1
        else:
            reserve.append(q)
    return selected, reserve


def main():
    work = ROOT / 'data/bulk_work'
    inventory = read(work / 'inventory.jsonl')
    labels = {q['id']: q for name in ['cmm_labels', 'tal_labels'] for q in read(work / (name + '.jsonl'))}
    audits = {q['id']: q for q in read(work / 'structure_audit.jsonl')}
    exclusions = {q['id']: q for q in read(work / 'quality_exclusions.jsonl')}
    assert len(labels) == len(audits) == len(inventory) == 2138, 'incomplete bulk annotations'
    probe = json.loads((ROOT / 'data/bulk_probe/summary.json').read_text(encoding='utf-8'))
    sources, source_lookup = [], {}
    for i, m in enumerate(probe['manifests'], 1):
        sid = 'SRC-BULK-CMM-001' if 'cmm-math' in m['dataset'] else 'SRC-BULK-TAL-' + ('001' if 'train' in m['filename'] else '002')
        source_lookup[(m['dataset'], m['filename'])] = sid
        sources.append({'source_id': sid, 'title': m['dataset'] + ' / ' + m['filename'],
                        'url': m['url'], 'year': 'unknown', 'region': 'unknown',
                        'source_exam_grade': 'mixed', 'answer_location': '原JSONL对应行的answer（CMM）或answer_value（TAL）字段',
                        'accessed_at': probe['probed_at'], 'access_status': 'downloaded_public_dataset',
                        'text_extractable': True, 'reuse_status': 'unknown', 'raw_path': m['local_path'],
                        'revision': m['revision'], 'sha256': m['sha256'],
                        'notes': '公开数据集二手来源；题目另有原记录ID与行号。原试卷页面未逐题验证；年级按主要知识暂定，数学答案待集中复核。'})
    source_by_id = {s['source_id']: s for s in sources}
    prepared = []
    for original in inventory:
        q = dict(original)
        label, audit = labels[q['id']], audits[q['id']]
        p = q['provenance']
        grade = label.get('grade', 'pending')
        q.update({k: label.get(k, 'pending') for k in ['module', 'knowledge_point', 'difficulty']})
        q['grade'] = int(grade) if str(grade) in ['7', '8', '9'] else 'pending'
        q['source_id'] = source_lookup[(p['dataset'], p['file'])]
        q['source_ref'] = f"{p['file']}；第{p['line']}行；原ID={p['original_id']}；答案字段=" + ('answer' if 'CMM' in q['id'] else 'answer_value')
        q['source_type'], q['batch_id'] = 'public', BATCH
        q['risk_flags'] = list(dict.fromkeys(label.get('risk_flags', []) + audit['risk_flags'] +
                                           ['secondary_source', 'math_not_reviewed', 'curriculum_version_unconfirmed', 'reuse_unknown']))
        q['classification_annotation'] = label
        q['structure_annotation'] = audit
        q['review_method'] = 'bulk_structure_and_rule_based_curriculum_labels'
        q['source_original_paper_verified'] = False
        q.update(source_metadata(source_by_id[q['source_id']]))
        q['status'] = 'collected'
        if q['id'] in exclusions:
            e = dict(exclusions[q['id']])
            resolved_label = (e.get('expected_grade') in ['7', '8', '9'] and
                              e.get('expected_module') and e.get('expected_knowledge_point') and
                              'curriculum_label_error' in e['risk_flags'])
            if resolved_label:
                q.update(grade=int(e['expected_grade']), module=e['expected_module'],
                         knowledge_point=e['expected_knowledge_point'])
                q['label_resolution'] = {'reviewer_model': 'gpt-6.1-sol', 'reason': e['reason'],
                                         'decision': 'correct_curriculum_labels_only'}
                q['risk_flags'] = [f for f in q['risk_flags'] if f not in
                                   {'primary_or_competition_scope', 'out_of_scope', 'subject_text_mismatch'}]
                e['risk_flags'] = [f for f in e['risk_flags'] if f != 'curriculum_label_error']
            q['risk_flags'] = list(dict.fromkeys(q['risk_flags'] + e['risk_flags']))
            q['quality_annotation'] = e
            if e['risk_flags']:
                q['status'] = 'rejected' if e['disposition'] == 'reject' else 'needs_review'
        if q['status'] != 'rejected' and (audit['disposition'] != 'pass' or
                any(q[k] == 'pending' for k in ['grade', 'module', 'knowledge_point']) or
                any(f not in INFORMATION_FLAGS for f in q['risk_flags'])):
            q['status'] = 'needs_review'
        prepared.append(q)
    unique, conflicts, duplicates = deduplicate(prepared)
    eligible = [q for q in unique if q['status'] == 'collected']
    held = [q for q in unique if q['status'] != 'collected'] + conflicts
    # The baseline comes from the checked draft, excluding a previous run of this batch.
    baseline = [q for q in read(ROOT / 'data/public_draft/questions.jsonl') if q['batch_id'] != BATCH]
    baseline_groups = {fingerprint(q, True): q for q in baseline}
    new, baseline_duplicates = [], []
    for q in eligible:
        prior = baseline_groups.get(fingerprint(q, True))
        if prior is None:
            new.append(q)
        elif answer_text(prior) != answer_text(q):
            q['risk_flags'].append('source_answer_conflict')
            q['status'] = 'needs_review'
            held.append(q)
        else:
            baseline_duplicates.append(q)
    quotas = json.loads((ROOT / 'config/quotas.json').read_text(encoding='utf-8-sig'))
    selected, reserve = fill_quotas(new, quotas['cells'], baseline)
    target = ROOT / 'data/batches' / BATCH
    # Exact baseline duplicates can be merged by the existing checker while retaining sources.
    exact_baseline_duplicates = [q for q in baseline_duplicates if fingerprint(q) == fingerprint(baseline_groups[fingerprint(q, True)])]
    write_jsonl(target / 'sources.jsonl', sources)
    write_jsonl(target / 'questions.jsonl', selected + held + exact_baseline_duplicates)
    archive = ROOT / 'data/bulk_prepared'
    write_jsonl(archive / 'all_candidates.jsonl', prepared)
    write_jsonl(archive / 'reserve.jsonl', reserve)
    write_jsonl(archive / 'duplicate_groups.jsonl', duplicates)
    write_jsonl(archive / 'baseline_duplicates.jsonl', baseline_duplicates)
    summary = {'raw_candidates': len(prepared), 'unique_candidate_groups': len(unique),
               'answer_conflict_records': len(conflicts), 'eligible_unique': len(eligible),
               'selected_new': len(selected), 'reserve_unique': len(reserve), 'held_or_rejected': len(held),
               'duplicate_records_grouped': sum(len(d['member_ids']) - 1 for d in duplicates),
               'baseline_duplicates': len(baseline_duplicates), 'source_files': len(sources)}
    (archive / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (target / 'notes.md').write_text('# 批量公开题入库\n\n' +
        '候选来自已锁定版本并存档的CMM-Math与TAL-SCQ5K；按主要知识年级和模块填配额，超出配额的有效题保留在候补池。\n\n' +
        '标签由Luna规则初标，结构由Sol规则筛查；并未完成逐题数学、难度和教材适配审核。存在来源答案冲突的整组暂停。\n\n' +
        '\n'.join(f'- {k}: {v}' for k, v in summary.items()) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
