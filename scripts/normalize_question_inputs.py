"""Produce the canonical input view and a source-to-input transformation ledger."""
import json
from collections import Counter
from pathlib import Path
from question_format import canonical_question, VERSION

ROOT = Path(__file__).resolve().parents[1]


def main():
    native = [json.loads(s) for s in (ROOT / 'data/public_draft/questions.jsonl').read_text(encoding='utf-8').splitlines()]
    rows = [canonical_question(q) for q in native]
    out = ROOT / 'data/normalized'
    out.mkdir(exist_ok=True)
    (out / 'questions.jsonl').write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in rows), encoding='utf-8')
    records = [{'id': q['id'], **q['format_normalization']} for q in rows if q['format_normalization']['field_rules']]
    (out / 'format_changes.jsonl').write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in records), encoding='utf-8')
    summary = {'version': VERSION, 'count': len(rows), 'changed_questions': len(records),
               'rule_counts': dict(Counter(rule for q in records for rules in q['field_rules'].values() for rule in rules)),
               'source_draft_modified': False}
    (ROOT / 'data/reports/format_normalization_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
