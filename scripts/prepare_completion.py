"""Merge reviewed hard candidates without changing native question text or labels."""
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from check_collection import fingerprint, write_jsonl, source_metadata

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/hard_collection/completion'
BATCH = 'hard_cmm_images_001'

def read(p):
    return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()] if p.is_file() else []

def map_images(c, review=None):
    sections = [('stem', '', 'question', c['question'])] + [('option', letter, 'option_' + letter.lower(), c['options'][letter]) for letter in 'ABCD'] + [('analysis', '', 'solution', c['analysis'])]
    roles = [(role, letter, field, index) for role, letter, field, text in sections for index in range(text.count('<ImageHere>'))]
    if len(roles) != len(c['image_refs']):
        raise ValueError('placeholder count differs from image count')
    assets = []
    reviewed_roles = {a['ref']: a for a in (review or {}).get('image_roles', [])}
    for ref, (role, letter, field, index) in zip(c['image_refs'], roles):
        requested = reviewed_roles.get(ref, {})
        if role == 'analysis' and requested.get('role') in {'stem', 'option'}:
            raise ValueError('review proposes promoting analysis image; requires original-question proof')
        role = requested.get('role', role)
        letter = requested.get('option', letter) if role == 'option' else ''
        if role == 'analysis':
            continue
        a = IMAGES[ref]
        assets.append({'path': a['path'], 'sha256': a['sha256'], 'role': role,
                       **({'option': letter} if role == 'option' else {}), 'placeholder_index': index, 'source_placeholder_field': field,
                       'source_url': c['image_package_url'], 'source_ref': a['zip_member'],
                       'alt': '原题配图' if role == 'stem' else letter + '选项原图',
                       'contains_answer_or_solution': False})
    if not assets and ('如图' in c['question'] or '图中' in c['question']):
        raise ValueError('question refers to figure but has no input figure')
    return assets

IMAGES = {a['reference']: a for a in read(BASE / 'image_inventory.jsonl')}

def main():
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    baseline_path = BASE / 'baseline_1500.jsonl'
    if not baseline_path.exists():
        baseline_path.write_bytes((ROOT / 'data/public_draft/questions.jsonl').read_bytes())
    baseline = read(baseline_path)
    sources = {s['source_id']: s for s in read(ROOT / 'data/registry/sources.jsonl')}
    external_source_ids = {s['source_id'] for path in (ROOT / 'data/batches').glob('*/sources.jsonl')
                           if path.parent.name != 'hard_web_completion_001' for s in read(path)}
    pool = read(ROOT / 'data/hard_collection/images_round1/bulk_probe/cmm_image_candidates.jsonl')
    labels = {a['candidate_id']: a for name in ['g7_labels', 'g8_labels', 'g9_labels', 'g9a_labels', 'g9b_labels'] for a in read(BASE / (name + '.jsonl'))}
    for a in read(BASE / 'label_corrections.jsonl'):
        if a['candidate_id'] in labels:
            labels[a['candidate_id']].update(a)
    reviews = {a['candidate_id']: a for a in read(BASE / 'hard_visual_review.jsonl')}
    reviews.update({a['candidate_id']: a for a in read(BASE / 'hard_visual_overrides.jsonl')})
    prepared, held = [], []
    for c in pool:
        label = labels.get(c['candidate_id'])
        if not label or label.get('difficulty') != '困难':
            continue
        review = reviews.get(c['candidate_id'], {})
        if label.get('decision') != 'eligible' and review.get('decision') != 'eligible':
            held.append({'candidate_id': c['candidate_id'], 'reason': label.get('hold_reason', label.get('decision_reason', 'held'))})
            continue
        if review.get('decision') == 'hold' or not (review.get('visual_checked') is True or label.get('visual_checked') is True):
            held.append({'candidate_id': c['candidate_id'], 'reason': review.get('reason', 'awaiting visual check')})
            continue
        try:
            assets = map_images(c, review)
        except ValueError as e:
            held.append({'candidate_id': c['candidate_id'], 'reason': str(e)})
            continue
        q = {'id': 'EMB-P-IMG-CMM-' + c['original_id'], 'question': c['question'],
             **{'option_' + letter.lower(): c['options'][letter] for letter in 'ABCD'},
             'answer': c['answer'], **{key: label[key] for key in ['grade', 'module', 'knowledge_point', 'difficulty']},
             'source_exam_grade': c['provisional_grade'], 'source_id': 'SRC-BULK-CMM-001',
             'source_ref': f"all_data.jsonl；第{c['dataset_line']}行；原ID={c['original_id']}；答案字段=answer",
             'source_type': 'public', 'batch_id': BATCH, 'status': 'collected', 'solution': c['analysis'],
             'risk_flags': ['secondary_source', 'math_not_reviewed', 'curriculum_version_unconfirmed', 'reuse_unknown', 'provisional_difficulty'],
             'input_modality': 'text_image' if assets else 'text', 'image_assets': assets,
             'provenance': {'dataset': c['dataset_id'], 'revision': c['dataset_revision'], 'file': c['dataset_file'],
                            'line': c['dataset_line'], 'original_id': c['original_id'],
                            'local_path': 'data/bulk_probe/raw/ecnu-icalk__cmm-math/all_data.jsonl'},
             'difficulty_annotation': {**label, 'model': label.get('model', 'inherited_task_model'), 'annotated_at': now,
                                      'rule_version': 'difficulty-v0.2', 'review_method': 'question_options_source_analysis_and_original_figure',
                                      'source_difficulty': 'not_provided', 'empirical': False},
             'image_review': review or {'visual_checked': True, 'reviewer': label.get('model')},
             'source_question_kind': 'dataset_exam_with_original_figures'}
        q.update(source_metadata(sources[q['source_id']]))
        prepared.append(q)
    write_jsonl(ROOT / 'data/batches' / BATCH / 'questions.jsonl', prepared)
    write_jsonl(ROOT / 'data/batches' / BATCH / 'sources.jsonl', [])
    write_jsonl(BASE / 'hard_candidates_held.jsonl', held)

    # Previously collected public-preview pilot questions now become reviewable batch records.
    pilots = read(ROOT / 'data/hard_collection/exports/hard_candidates_round1.jsonl') + read(ROOT / 'data/public_image_draft/questions.jsonl')
    new_sources, pilot_rows = {}, []
    for original in pilots:
        q = dict(original)
        q.update(batch_id='hard_web_completion_001', source_type='public', status='collected')
        q['risk_flags'] = ['secondary_source', 'math_not_reviewed', 'source_reuse_unknown', 'provisional_difficulty']
        q['input_modality'] = 'text_image' if q.get('image_assets') else 'text'
        sid = q['source_id']
        if sid not in external_source_ids and sid not in new_sources:
            new_sources[sid] = {'source_id': sid, 'title': q['source_title'], 'url': q['source_url'],
                'year': q['source_material_year'], 'region': q['source_region'], 'answer_location': q['source_answer_location'],
                'raw_path': q['source_raw_path'], 'accessed_at': q['source_accessed_at'], 'access_status': q['source_access_status'],
                'reuse_status': q['source_reuse_status'], 'notes': q['source_notes']}
        pilot_rows.append(q)
    write_jsonl(ROOT / 'data/batches/hard_web_completion_001/questions.jsonl', pilot_rows)
    write_jsonl(ROOT / 'data/batches/hard_web_completion_001/sources.jsonl', list(new_sources.values()))
    print(json.dumps({'labels_completed': len(labels), 'cmm_hard_ready': len(prepared), 'hard_held': len(held), 'web_ready': len(pilot_rows)}, ensure_ascii=True))

if __name__ == '__main__':
    main()
