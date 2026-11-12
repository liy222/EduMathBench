"""Detect likely duplicate wording across LaTeX delimiter and image encodings.

This report does not merge figures or assume two different diagrams are identical.
"""
import hashlib,json,re
from collections import defaultdict
from pathlib import Path
from check_collection import normalized,write_jsonl
from prepare_completion import read
ROOT=Path(__file__).resolve().parents[1]

def key_text(text):
 s=normalized(re.sub(r'\\\s+', '', text)).replace('<ImageHere>','').replace('$','')
 s=re.sub(r'\\(?:mathrm|text|textrm)\{([A-Za-z0-9]+)\}',r'\1',s)
 s=re.sub(r'\\(?:left|right|quad|qquad)', '', s)
 s=re.sub(r'\\[,;! ]', '', s)
 s=s.replace('{}', '')
 s=s.replace('（','(').replace('）',')').replace('，',',').replace('．','.')
 s=re.sub(r'[。]|(?<!\d)\.(?!\d)', '', s)
 s=re.sub(r'[；;](?=其中正确)', '', s)
 s=re.sub(r'\((?:\\quad|\\qquad)?\)', '()', s)
 return re.sub(r'[。.]$', '', s)

def presentation_key(q):
 return tuple(key_text(q[f]) for f in ['question','option_a','option_b','option_c','option_d'])

rows=read(ROOT/'data/public_draft/questions.jsonl')
groups=defaultdict(list)
for q in rows:groups[presentation_key(q)].append(q)
suspects=[]
for k,group in groups.items():
 if len(group)<2:continue
 suspects.append({'ids':[q['id'] for q in group], 'answer_letters':[q['answer'] for q in group],
                  'source_refs':[q['source_ref'] for q in group],
                  'image_sha256s':[[a['sha256'] for a in q.get('image_assets',[])] for q in group],
                  'canonical_wording_hash':hashlib.sha256(json.dumps(k,ensure_ascii=False).encode()).hexdigest(),
                  'decision':'requires_source_figure_comparison'})
write_jsonl(ROOT/'data/reports/presentation_duplicate_candidates.jsonl',suspects)
print(json.dumps({'checked':len(rows),'likely_duplicate_groups':len(suspects),'groups':suspects},ensure_ascii=True))
