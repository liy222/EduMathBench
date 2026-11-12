"""收集阶段的可重复结构检查和覆盖统计；不验证数学正确性。"""
import csv
import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ['id', 'question', 'option_a', 'option_b', 'option_c', 'option_d',
            'answer', 'grade', 'module', 'knowledge_point', 'difficulty',
            'source_id', 'source_ref', 'source_type', 'status', 'batch_id']
SOURCE_FIELDS = ['source_title', 'source_url', 'source_material_year', 'source_region',
                 'source_answer_location', 'source_raw_path', 'source_accessed_at',
                 'source_access_status', 'source_reuse_status', 'source_notes']
FIELDS = REQUIRED + SOURCE_FIELDS + ['input_modality', 'image_assets', 'source_exam_grade', 'solution', 'risk_flags', 'family_id',
                     'parent_id', 'verification_note', 'reviewer', 'review_method', 'split',
                     'source_question_kind', 'source_topic', 'provenance', 'label_resolution', 'quality_annotation']
MODULES = {'数与式', '方程与不等式', '函数', '几何', '统计与概率'}
DIFFICULTIES = {'基础', '中等', '困难', 'pending'}
INFORMATION_FLAGS = {'curriculum_version_unconfirmed', 'reuse_unknown', 'reuse_rights_unknown',
                     'math_not_reviewed', 'secondary_source', 'source_reuse_unknown',
                     'near_duplicate_grouped', 'provisional_difficulty', 'not_independently_solved', 'source_analysis_error_reviewed'}


def normalized(value):
    # 只处理空白和Unicode组合字符，保留负号/幂/括号等数学符号。
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', str(value)))


def simple_equation_key(value):
    s = normalized(value)
    if s.startswith('$$') and s.endswith('$$'):
        s = s[2:-2]
    elif s.startswith('$') and s.endswith('$'):
        s = s[1:-1]
    if s.count('=') == 1 and not re.search(r'[<>!≤≥≠]=|=[=]', s):
        left, right = s.split('=')
        if left and right:
            return tuple(sorted((left, right)))
    return None


def source_url_key(s):
    u = urlsplit(s.get('url', ''))
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), unquote(u.path), u.query, ''))


def source_metadata(s):
    mapping = {'source_title':'title', 'source_url':'url', 'source_material_year':'year',
               'source_region':'region', 'source_answer_location':'answer_location',
               'source_raw_path':'raw_path', 'source_accessed_at':'accessed_at',
               'source_access_status':'access_status', 'source_reuse_status':'reuse_status',
               'source_notes':'notes'}
    return {field: s.get(source_field, '') for field, source_field in mapping.items()}


def apply_resolution(q, resolution):
    # 仅记录题族、已核验重复合并或退回，不通过附表修改题干/选项/答案。
    decision = resolution.get('decision')
    if decision not in {'retain_same_family', 'reject', 'merge_verified_duplicate'} or not resolution.get('reason'):
        raise ValueError('invalid resolution decision or missing reason')
    if decision == 'retain_same_family':
        if not resolution.get('family_id'):
            raise ValueError('family_id required for near-duplicate grouping')
        q['risk_flags'] = [f for f in q.get('risk_flags', []) if f != 'near_duplicate_candidate']
        if 'near_duplicate_grouped' not in q['risk_flags']:
            q['risk_flags'].append('near_duplicate_grouped')
        q['family_id'] = resolution['family_id']
    elif decision == 'merge_verified_duplicate':
        if not resolution.get('primary_id'):
            raise ValueError('primary_id required for duplicate merge')
        q['risk_flags'] = [f for f in q.get('risk_flags', []) if f != 'exact_duplicate_candidate']
        if q.get('status') == 'needs_review':
            q['status'] = 'collected'
    else:
        q['status'] = 'rejected'
        q['rejection_reason'] = resolution['reason']
    q['resolution'] = resolution
    q['verification_note'] = resolution['reason']
    q['reviewer'] = resolution.get('reviewer', '')
    q['review_method'] = resolution.get('review_method', 'issue_triage')


def fingerprint(q, sorted_options=False):
    assets = q.get('image_assets', [])
    opts = [normalized(q.get('option_' + c, '')) + ''.join(
        a.get('sha256', '') for a in assets if a.get('role') == 'option' and a.get('option') == c.upper()) for c in 'abcd']
    if sorted_options:
        opts.sort()
    content = [normalized(q.get('question', ''))] + opts
    if assets:
        content.append([a.get('sha256', '') for a in assets if a.get('role') == 'stem'])
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


def verified_duplicate_match(primary, q, comparison='exact', resolution=None):
    if primary['answer'] != q['answer']:
        return False
    if comparison == 'exact':
        return fingerprint(primary) == fingerprint(q)
    if comparison == 'math_presentation':
        return all(presentation_key(primary[field], field == 'question') ==
                   presentation_key(q[field], field == 'question')
                   for field in ['question', 'option_a', 'option_b', 'option_c', 'option_d'])
    if comparison == 'reviewed_stem_same_options':
        r = resolution or {}
        return (fingerprint(primary) == r.get('primary_fingerprint') and
                fingerprint(q) == r.get('duplicate_fingerprint') and
                all(normalized(primary['option_' + c]) == normalized(q['option_' + c]) for c in 'abcd'))
    if comparison != 'chinese_prose_commas' or normalized(primary['question']) != normalized(q['question']):
        return False
    # 仅人工指定的中文叙述选项可忽略逗号；坐标、数字和公式不适用。
    for c in 'abcd':
        left, right = normalized(primary['option_' + c]), normalized(q['option_' + c])
        if left == right:
            continue
        if not all(re.fullmatch(r'[\u4e00-\u9fff，,]+', s) for s in (left, right)):
            return False
        if left.replace('，', '').replace(',', '') != right.replace('，', '').replace(',', ''):
            return False
    return True


def presentation_key(value, stem=False):
    # 仅供已人工指定的重复处置：保留所有运算符、数字、指数和括号结构。
    s = normalized(value)
    s = re.sub(r'\\mathrm\{([A-Za-z]+)\}', r'\1', s)
    if stem:
        s = re.sub(r'(?:\$\((?:\\quad)?\)\$|\(\)|（(?:\\quad)?）|[。．.])+$', '', s)
    return s


def conflicting_answer_ids(questions):
    groups = defaultdict(list)
    for q in questions:
        if q.get('answer') in list('ABCD'):
            groups[fingerprint(q, sorted_options=True)].append(q)
    conflicts = set()
    for group in groups.values():
        meanings = {normalized(q.get('option_' + q['answer'].lower(), '')) for q in group}
        if len(meanings) > 1:
            conflicts.update(q['id'] for q in group)
    return conflicts


def read_jsonl(path):
    rows, issues = [], []
    for line_no, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError('record must be object')
            rows.append(obj)
        except (ValueError, TypeError) as exc:
            issues.append({'id': '', 'file': str(path.relative_to(ROOT)),
                           'line': line_no, 'kind': 'invalid_json', 'detail': str(exc)})
    return rows, issues


def apply_difficulty_annotation(q, annotation):
    if (annotation.get('decision') == 'review_existing_label' and
        q.get('difficulty') == annotation.get('previous_difficulty')):
        q['difficulty'] = annotation['difficulty']
        q['difficulty_annotation'] = annotation
    elif q.get('difficulty') == 'pending':
        q['difficulty'] = annotation['difficulty']
        q['difficulty_annotation'] = annotation
    elif (annotation.get('decision') == 'document_existing_label' and
          q.get('difficulty') == annotation['difficulty']):
        # 补全旧标签依据不改变该标签，也不冒充原始标注记录。
        q['difficulty_annotation'] = annotation


def source_problems(s, batch_dir):
    errors = []
    for field in ['source_id', 'title', 'url', 'answer_location', 'accessed_at', 'raw_path']:
        if not s.get(field):
            errors.append('source_missing:' + field)
    raw = s.get('raw_path')
    if raw:
        candidates = [ROOT / raw, batch_dir / raw]
        if not any(p.is_file() for p in candidates):
            errors.append('source_archive_missing')
    return errors


def question_problems(q, sources, source_errors):
    errors = ['missing:' + f for f in REQUIRED if q.get(f) is None or str(q.get(f)).strip() == '']
    for field in ['question'] + ['option_' + c for c in 'abcd']:
        value = q.get(field, '')
        if isinstance(value, str) and re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]', value):
            errors.append('text_encoding_or_control_character:' + field)
    if q.get('answer') not in list('ABCD'):
        errors.append('invalid_answer')
    else:
        correct_option = normalized(q.get('option_' + q['answer'].lower(), ''))
        if correct_option and '<ImageHere>' not in correct_option and sum(normalized(q.get('option_' + c, '')) == correct_option for c in 'abcd') > 1:
            errors.append('duplicate_correct_option')
        equation_key = simple_equation_key(q.get('option_' + q['answer'].lower(), ''))
        directional_transform = bool(re.search(r'由左到右|从左到右|由右到左|从右到左|因式分解|分解因式|展开', str(q.get('question', ''))))
        if equation_key and not directional_transform and any(c != q['answer'].lower() and simple_equation_key(q.get('option_' + c, '')) == equation_key for c in 'abcd'):
            errors.append('equivalent_correct_equation_options')
    if q.get('grade') not in [7, 8, 9, 'pending']:
        errors.append('invalid_grade')
    if q.get('module') not in MODULES | {'pending'}:
        errors.append('invalid_module')
    if q.get('difficulty') not in DIFFICULTIES:
        errors.append('invalid_difficulty')
    if q.get('source_type') != 'public':
        errors.append('non_public_in_collection')
    if q.get('status') not in ['collected', 'auto_checked', 'needs_review', 'rejected']:
        errors.append('invalid_collection_status')
    sid = q.get('source_id')
    if sid not in sources:
        errors.append('unknown_source')
    else:
        errors.extend(source_errors.get(sid, []))
    if not isinstance(q.get('risk_flags', []), list):
        errors.append('risk_flags_not_array')
    assets = q.get('image_assets', [])
    if q.get('input_modality') == 'text_image' and not assets:
        errors.append('image_assets_missing')
    for a in assets:
        p = (ROOT / a.get('path', '')).resolve()
        if not p.is_relative_to(ROOT.resolve()) or not p.is_file():
            errors.append('image_asset_missing_or_outside_project')
        elif hashlib.sha256(p.read_bytes()).hexdigest() != a.get('sha256'):
            errors.append('image_asset_hash_mismatch')
        if a.get('role') not in {'stem', 'option'} or a.get('contains_answer_or_solution') is not False:
            errors.append('image_asset_answer_leakage_or_invalid_role')
        if a.get('role') == 'option' and a.get('option') not in list('ABCD'):
            errors.append('image_asset_option_missing')
        if not a.get('source_url') or not a.get('source_ref'):
            errors.append('image_asset_source_missing')
    for field, role, letter in [('question', 'stem', '')] + [('option_' + c.lower(), 'option', c) for c in 'ABCD']:
        markers = q.get(field, '').count('<ImageHere>')
        matched = sum(a.get('source_placeholder_field') == field if a.get('source_placeholder_field') else
                      a.get('role') == role and (role == 'stem' or a.get('option') == letter) for a in assets)
        if markers and markers != matched:
            errors.append('image_placeholder_mapping_mismatch:' + field)
    return errors


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                        for k, v in row.items()})


def main(refresh_selection=False):
    quotas = json.loads((ROOT / 'config/quotas.json').read_text(encoding='utf-8-sig'))
    sources, source_errors, issues, questions = {}, {}, [], []
    for path in sorted((ROOT / 'data/batches').glob('*/sources.jsonl')):
        records, problems = read_jsonl(path)
        issues.extend(problems)
        for s in records:
            s = dict(s)
            raw = s.get('raw_path')
            if raw and not (ROOT / raw).is_file() and (path.parent / raw).is_file():
                s['original_raw_path'] = raw
                s['raw_path'] = str((path.parent / raw).relative_to(ROOT))
            sid = s.get('source_id', '')
            if sid in sources:
                issues.append({'id': sid, 'kind': 'duplicate_source_id', 'detail': str(path)})
                source_errors[sid] = ['duplicate_source_id']
            else:
                sources[sid] = s
                source_errors[sid] = source_problems(s, path.parent)
            issues.extend({'id': sid, 'kind': e, 'detail': s.get('url', '')}
                          for e in source_errors[sid])
    for path in sorted((ROOT / 'data/batches').glob('*/questions.jsonl')):
        records, problems = read_jsonl(path)
        issues.extend(problems)
        questions.extend(records)

    annotations = {}
    known_ids = {q.get('id') for q in questions}
    for path in sorted((ROOT / 'data/annotations').glob('difficulty*.jsonl')):
        records, problems = read_jsonl(path)
        issues.extend(problems)
        for a in records:
            if a.get('id') not in known_ids or a.get('difficulty') not in DIFFICULTIES or not a.get('reason'):
                issues.append({'id': a.get('id', ''), 'kind': 'invalid_difficulty_annotation', 'detail': str(path.relative_to(ROOT))})
                continue
            annotations[a['id']] = a
    for q in questions:
        q.update(source_metadata(sources.get(q.get('source_id'), {})))
        a = annotations.get(q.get('id'))
        if a:
            apply_difficulty_annotation(q, a)

    # Admission reviews can resolve collector holds, but cannot alter native item content.
    question_lookup = {q.get('id'): q for q in questions}
    for path in sorted((ROOT / 'data/annotations').glob('quality_admission*.jsonl')):
        reviews, problems = read_jsonl(path)
        issues.extend(problems)
        for review in reviews:
            q = question_lookup.get(review.get('id'))
            if not q or fingerprint(q) != review.get('original_fingerprint') or not review.get('reason'):
                raise ValueError('Quality admission provenance guard failed: ' + str(review.get('id')))
            if q.get('status') == 'rejected':
                raise ValueError('Cannot admit rejected record through a collector-hold review')
            original_flags = q.get('risk_flags', [])
            unresolved = [f for f in original_flags if f not in INFORMATION_FLAGS and f not in review.get('remove_flags', [])]
            if unresolved:
                raise ValueError('Unresolved collector flags: ' + str(review.get('id')) + ' ' + str(unresolved))
            q.update({k:review[k] for k in ['grade', 'module', 'knowledge_point', 'difficulty']})
            q['status'] = 'collected'
            q['risk_flags'] = [f for f in original_flags if f not in review.get('remove_flags', [])]
            q['quality_annotation'] = {**review, 'original_risk_flags': original_flags}
            q['difficulty_annotation'] = review['difficulty_annotation']
            if 'source_analysis_error' in original_flags:
                q['risk_flags'].append('source_analysis_error_reviewed')

    questions_by_id = {q.get('id'): q for q in questions}
    for path in sorted((ROOT / 'data/resolutions').glob('*.jsonl')):
        records, problems = read_jsonl(path)
        issues.extend(problems)
        for resolution in records:
            q = questions_by_id.get(resolution.get('id'))
            try:
                if q is None:
                    raise ValueError('unknown question id')
                if resolution.get('decision') == 'merge_verified_duplicate':
                    primary = questions_by_id.get(resolution.get('primary_id'))
                    if not primary or primary['id'] == q['id'] or not verified_duplicate_match(primary, q, resolution.get('comparison', 'exact'), resolution):
                        raise ValueError('duplicate content or source answer not verified')
                    q['_verified_duplicate_key'] = fingerprint(primary)
                apply_resolution(q, resolution)
            except (ValueError, TypeError) as exc:
                issues.append({'id': resolution.get('id', ''), 'kind':'invalid_resolution', 'detail':str(exc)})

    id_counts = Counter(q.get('id') for q in questions)
    answer_conflicts = conflicting_answer_ids(questions)
    checked, held, duplicates = [], [], []
    exact, unordered = {}, {}
    # 人工指定的重复记录后处理，确保稳定的主题号先入库。
    for original in sorted(questions, key=lambda q: q.get('resolution', {}).get('decision') == 'merge_verified_duplicate'):
        q = dict(original)
        errs = question_problems(q, sources, source_errors)
        if id_counts[q.get('id')] > 1:
            errs.append('duplicate_id')
        if q.get('id') in answer_conflicts:
            errs.append('source_answer_conflict')
        if q.get('status') in ['needs_review', 'rejected']:
            errs.append('collector_' + q['status'])
        flags = q.get('risk_flags', [])
        if isinstance(flags, list) and flags:
            errs.extend('risk:' + str(f) for f in flags if f not in INFORMATION_FLAGS)
        if q.get('grade') == 'pending' or q.get('module') == 'pending' or q.get('knowledge_point') == 'pending':
            errs.append('pending_coverage_label')
        if errs:
            q['status'] = 'rejected' if original.get('status') == 'rejected' else 'needs_review'
            q['automatic_check_errors'] = errs
            held.append(q)
            issues.extend({'id': q.get('id', ''), 'kind': e, 'detail': q.get('source_ref', ''),
                           'disposition': q['status']} for e in errs)
            continue
        key = q.get('_verified_duplicate_key', fingerprint(q))
        other = exact.get(key)
        if other:
            matching_options = other['answer'] == q['answer']
            provenance = {'id': q['id'], 'source_id': q['source_id'], 'source_ref': q['source_ref'],
                          'batch_id': q['batch_id'], 'answer': q['answer'],
                          'provenance': q.get('provenance', {}),
                          'source_exam_grade': q.get('source_exam_grade', ''),
                          'source_question_kind': q.get('source_question_kind', ''),
                          **{field: q.get(field, '') for field in SOURCE_FIELDS}}
            other.setdefault('additional_sources', []).append(provenance)
            other['additional_sources'].extend(q.get('additional_sources', []))
            kind = 'exact_duplicate' if matching_options else 'answer_conflict'
            duplicates.append({'id': q['id'], 'primary_id': other['id'], 'kind': kind})
            if not matching_options:
                other['status'] = 'needs_review'
                other.setdefault('automatic_check_errors', []).append('answer_conflict')
                q['status'] = 'needs_review'
                held.append(q)
                issues.append({'id': q['id'], 'kind': kind, 'detail': other['id']})
            continue
        unordered_key = fingerprint(q, sorted_options=True)
        if unordered_key in unordered:
            q['status'] = 'needs_review'
            q['automatic_check_errors'] = ['option_order_near_duplicate']
            q['near_duplicate_of'] = unordered[unordered_key]['id']
            held.append(q)
            issues.append({'id': q['id'], 'kind': 'option_order_near_duplicate', 'detail': q['near_duplicate_of']})
            continue
        q['status'] = 'auto_checked'
        q.setdefault('review_method', 'structure_only')
        exact[key] = q
        unordered[unordered_key] = q
        checked.append(q)
    conflict_records = [q for q in checked if q['status'] != 'auto_checked']
    held.extend(conflict_records)
    checked = [q for q in checked if q['status'] == 'auto_checked']
    rejected = [q for q in held if q['status'] == 'rejected']
    held = [q for q in held if q['status'] != 'rejected']
    # Parallel collection may fill the same cell before another batch is merged.
    # Keep the original batches, but cap the derived draft and retain overflow.
    limits = {(c['grade'], c['module']): c['target'] for c in quotas['cells']}
    used, quota_reserve, selected = Counter(), [], []
    selection_path = ROOT / 'config/collection_selection.json'
    preferred = json.loads(selection_path.read_text(encoding='utf-8')).get('ids', []) if selection_path.is_file() and not refresh_selection else []
    positions = {qid: i for i, qid in enumerate(preferred)}
    available_ids = {q['id'] for q in checked}
    if set(preferred) - available_ids:
        raise ValueError('Selected records failed validation: ' + ','.join(sorted(set(preferred) - available_ids)))
    for q in sorted(checked, key=lambda q: (positions.get(q['id'], len(positions)), 'secondary_source' in q.get('risk_flags', []),
                                            q.get('source_question_kind') == 'dataset_rewritten_exam' or q.get('source_question_kind') == 'theoretical_concept',
                                            q.get('source_question_kind') == 'theoretical_concept',
                                            'TAL' in q['id'], q['id'])):
        cell = (q['grade'], q['module'])
        if used[cell] < limits.get(cell, 0):
            selected.append(q)
            used[cell] += 1
        else:
            q['selection_note'] = '结构通过，当前年级/模块配额已满，留作候补。'
            quota_reserve.append(q)
    checked = selected
    progress = []
    for cell in quotas['cells']:
        def matches(q):
            return q.get('grade') == cell['grade'] and q.get('module') == cell['module']
        cands = [q for q in questions if matches(q)]
        usable = [q for q in checked if matches(q)]
        pending = [q for q in held if matches(q)]
        duplicate_ids = {d['id'] for d in duplicates if d['kind'] == 'exact_duplicate'}
        progress.append({**cell, 'candidates': len(cands), 'auto_checked': len(usable),
                         'needs_review': len(pending),
                         'quota_reserve': sum(matches(q) for q in quota_reserve),
                         'duplicate_or_rejected': sum(q.get('id') in duplicate_ids or q.get('status') == 'rejected' for q in cands),
                         'remaining': max(0, cell['target'] - len(usable)),
                         'overflow': max(0, len(usable) - cell['target'])})
    difficulty_counts = Counter(q['difficulty'] for q in checked)
    out = ROOT / 'data/public_draft'
    write_jsonl(out / 'questions.jsonl', checked)
    write_jsonl(ROOT / 'data/candidates/needs_review.jsonl', held)
    write_jsonl(ROOT / 'data/candidates/rejected.jsonl', rejected)
    write_jsonl(ROOT / 'data/candidates/quota_reserve.jsonl', quota_reserve)
    write_jsonl(ROOT / 'data/registry/sources.jsonl', list(sources.values()))
    write_csv(ROOT / 'data/registry/sources.csv', list(sources.values()),
              ['source_id','title','url','year','region','source_exam_grade','answer_location',
               'main_modules','accessed_at','text_extractable','access_status','reuse_status','raw_path','notes'])
    write_jsonl(ROOT / 'data/reports/duplicates.jsonl', duplicates)
    write_jsonl(ROOT / 'data/reports/issues.jsonl', issues)
    write_csv(out / 'questions.csv', checked, FIELDS + ['additional_sources', 'difficulty_annotation', 'resolution'])
    source_view_fields = {'题号':'id', '状态':'status', '来源编号':'source_id',
                          '来源名称':'source_title', '来源链接':'source_url',
                          '题目及答案定位':'source_ref', '资料答案位置':'source_answer_location',
                          '资料年份':'source_material_year', '资料地区':'source_region',
                          '来源试卷年级':'source_exam_grade', '原材料文件':'source_raw_path',
                          '获取时间':'source_accessed_at', '访问状态':'source_access_status',
                          '复用状态':'source_reuse_status', '来源说明':'source_notes',
                          '来源题类':'source_question_kind', '合并到题号':'merged_into'}
    source_view = [{label: q.get(field, '') for label, field in source_view_fields.items()}
                   for q in checked + held + rejected + quota_reserve]
    for q in checked + held + rejected + quota_reserve:
        for extra in q.get('additional_sources', []):
            extra_source = sources.get(extra.get('source_id'), {})
            row = {**source_metadata(extra_source), **extra, 'status': 'merged_duplicate', 'merged_into': q['id'],
                   'source_exam_grade': extra.get('source_exam_grade', '')}
            source_view.append({label: row.get(field, '') for label, field in source_view_fields.items()})
    write_csv(ROOT / 'data/registry/question_sources.csv', source_view, list(source_view_fields))
    write_csv(ROOT / 'data/reports/progress.csv', progress, list(progress[0]))
    write_csv(ROOT / 'templates/questions_template.csv', [], FIELDS)
    write_csv(ROOT / 'templates/sources_template.csv', [], ['source_id','title','url','year','region',
              'source_exam_grade','answer_location','main_modules','accessed_at','text_extractable',
              'access_status','reuse_status','raw_path','notes'])
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    contributing_ids = {q.get('source_id') for q in questions}
    contributing_urls = {source_url_key(s) for sid, s in sources.items() if sid in contributing_ids}
    summary = {'generated_at': now, 'version': quotas['version'], 'stage': '公开题初版，待集中复核',
               'candidate_count': len(questions), 'auto_checked_unique': len(checked),
               'needs_review': len(held), 'rejected_count': len(rejected),
               'quota_reserve_count': len(quota_reserve),
               'duplicate_count': sum(x['kind']=='exact_duplicate' for x in duplicates),
               'source_count': len(sources), 'public_target': quotas['public_target'],
               'distinct_source_urls': len({source_url_key(s) for s in sources.values()}),
               'contributing_source_urls': len(contributing_urls),
               'remaining': sum(p['remaining'] for p in progress),
               'difficulty_counts': dict(difficulty_counts),
               'grade_difficulty_counts': {str(g): dict(Counter(q['difficulty'] for q in checked if q['grade'] == g)) for g in [7,8,9]},
               'input_modality_counts': dict(Counter('text_image' if q.get('image_assets') else 'text' for q in checked)),
               'hard_modality_counts': dict(Counter('text_image' if q.get('image_assets') else 'text' for q in checked if q['difficulty'] == '困难')),
               'progress': progress}
    (ROOT / 'data/reports/summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    source_distribution = []
    for sid, s in sources.items():
        source_distribution.append({'source_id': sid, 'title': s.get('title'),
                                    'year': s.get('year'), 'region': s.get('region'),
                                    'candidates': sum(q.get('source_id') == sid for q in questions),
                                    'auto_checked_primary': sum(q.get('source_id') == sid for q in checked),
                                    'needs_review': sum(q.get('source_id') == sid for q in held),
                                    'rejected': sum(q.get('source_id') == sid for q in rejected)})
    write_csv(ROOT / 'data/reports/source_distribution.csv', source_distribution,
              ['source_id','title','year','region','candidates','auto_checked_primary','needs_review','rejected'])
    lines = ['# 数据收集进度', '', f'生成时间：{now}', '',
             f'候选 {len(questions)} 道；结构检查通过且去重后 {len(checked)} 道；待处理 {len(held)} 道；退回 {len(rejected)} 道。来源登记 {len(sources)} 条（含失败及重复批次记录），实际供题材料 {len(contributing_urls)} 份。',
             '状态：公开题初版，待集中复核。结构检查不验证数学答案。', '',
             '| 年级 | 模块 | 目标 | 候选 | 自动通过 | 待处理 | 重复/退回 | 剩余 |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for p in progress:
        lines.append('| ' + ' | '.join(str(p[k]) for k in ['grade','module','target','candidates','auto_checked','needs_review','duplicate_or_rejected','remaining']) + ' |')
    gaps = [f"{p['grade']}年级{p['module']} {p['remaining']}道" for p in progress if p['remaining']]
    lines += ['', '暂定难度：' + '，'.join(f'{d} {difficulty_counts[d]}' for d in ['基础','中等','困难','pending']),
              '', ('下一批补缺：' + '；'.join(gaps) + '。') if gaps else
              '年级及模块数量配额已齐；全库难度比例以实际统计为准。难度标签暂定，年级内部难度分布、数学正确性、教材版本和近重复题族尚未定稿。',
              '', f'本批次中结构通过但超过配额的候补 {len(quota_reserve)} 道，另有整包筛选候补池；下载题量不计为完成数。']
    (ROOT / 'data/reports/progress.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ['candidate_count','auto_checked_unique','needs_review','rejected_count','duplicate_count','source_count','remaining']}, ensure_ascii=False))


if __name__ == '__main__':
    cli=argparse.ArgumentParser()
    cli.add_argument('--refresh-selection',action='store_true',help='Rebuild eligible inventory before applying reviewed quota selection')
    args=cli.parse_args()
    main(refresh_selection=args.refresh_selection)
