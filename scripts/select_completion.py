"""Use only checked, source-preserving substitutions within the same grade/module cell."""
import json
from collections import Counter
from pathlib import Path
from check_collection import fingerprint, write_jsonl
from prepare_completion import read

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/hard_collection/completion'

def main():
    baseline = read(BASE / 'baseline_1500.jsonl')
    available = read(ROOT / 'data/public_draft/questions.jsonl') + read(ROOT / 'data/candidates/quota_reserve.jsonl')
    byid = {q['id']: q for q in available}
    selected = {q['id']: byid[q['id']] for q in baseline if q['id'] in byid}
    assert len(selected) == 1500, 'baseline unexpectedly failed checks'
    changes = []
    counts = Counter(q['difficulty'] for q in selected.values())
    keys = {fingerprint(q, True) for q in selected.values()}
    candidates = [q for q in available if q['difficulty'] == '困难' and q['id'] not in selected]
    for q in sorted(candidates, key=lambda q: (bool(q.get('image_assets')), q['batch_id'] not in {'hard_web_completion_001', 'hard_cmm_images_001', 'hard_text_completion_001'}, q['id'])):
        if counts['困难'] >= 300:
            break
        key = fingerprint(q, True)
        if key in keys:
            continue
        samecell = [v for v in selected.values() if (v['grade'], v['module']) == (q['grade'], q['module']) and v['difficulty'] != '困难']
        if not samecell:
            continue
        old = min(samecell, key=lambda v: (-(counts[v['difficulty']] - 600), v['id']))
        del selected[old['id']]
        selected[q['id']] = q
        counts[old['difficulty']] -= 1
        counts['困难'] += 1
        keys.remove(fingerprint(old, True)); keys.add(key)
        changes.append({'removed_id': old['id'], 'added_id': q['id'], 'grade': q['grade'], 'module': q['module'],
                        'removed_difficulty': old['difficulty'], 'added_difficulty': q['difficulty'],
                        'reason': 'same-cell substitution with reviewed hard candidate; original labels retained'})
    payload = {'version': '2026-10-14', 'ids': list(selected), 'difficulty_counts': dict(counts),
               'hard_target': 300, 'hard_remaining': max(0, 300-counts['困难'])}
    (ROOT / 'config/collection_selection.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    write_jsonl(BASE / 'substitutions.jsonl', changes)
    print(json.dumps({k:v for k,v in payload.items() if k != 'ids'}, ensure_ascii=True))

if __name__ == '__main__':
    main()
