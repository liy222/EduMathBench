"""将整包候选转为稳定的工作条目，不自动入初版。"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('probe', ROOT / 'scripts/probe_bulk_sources.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def main():
    out = ROOT / 'data/bulk_work'
    out.mkdir(parents=True, exist_ok=True)
    inventory = []
    for filename in ['cmm_junior_text_candidates.jsonl', 'tal_middle_scope_candidates.jsonl']:
        for line in (ROOT / 'data/bulk_probe' / filename).read_text(encoding='utf-8-sig').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            provenance = row['bulk_provenance']
            cmm = provenance['dataset'] == 'ecnu-icalk/cmm-math'
            options = probe.cmm_options(row['options']) if cmm else [o[0]['content'] for o in row['answer_option_list']]
            original_id = str(provenance['original_id'])
            record_id = 'EMB-P-BULK-' + ('CMM-' if cmm else 'TAL-') + original_id
            exam_grade = {'七年级':7,'八年级':8,'九年级':9}.get(row.get('level'), 'pending')
            inventory.append({'id':record_id, 'question':row.get('question', row.get('problem')),
                **{'option_'+c:opt for c,opt in zip('abcd',options)},
                'answer':row.get('answer',row.get('answer_value')), 'source_exam_grade':exam_grade,
                'source_subject':row.get('subject',''), 'knowledge_routes':row.get('knowledge_point_routes',[]),
                'competition_sources':row.get('competition_source_list',[]),
                'source_difficulty':row.get('difficulty'), 'source_level':row.get('level',''),
                'solution':row.get('analysis','') if cmm else '\n'.join(row.get('answer_analysis',[])),
                'provenance':provenance})
    for label, dataset in [('cmm','ecnu-icalk/cmm-math'), ('tal','math-eval/TAL-SCQ5K')]:
        rows = [q for q in inventory if q['provenance']['dataset'] == dataset]
        (out / (label + '_inventory.jsonl')).write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in rows),encoding='utf-8')
    (out / 'inventory.jsonl').write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in inventory),encoding='utf-8')
    counts = {'cmm':sum(q['provenance']['dataset']=='ecnu-icalk/cmm-math' for q in inventory),
              'tal':sum(q['provenance']['dataset']=='math-eval/TAL-SCQ5K' for q in inventory)}
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
