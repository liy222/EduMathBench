"""批量题源可用性探查：只形成候选池，不自动计入正式初版配额。"""
import hashlib
import json
import re
import urllib.request
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/bulk_probe'
DATASETS = {
    'math-eval/TAL-SCQ5K': ['TAL-SCQ5K-CN/train.jsonl', 'TAL-SCQ5K-CN/test.jsonl'],
    'ecnu-icalk/cmm-math': ['all_data.jsonl']}
FIGURE = re.compile(r'如图|下图|上图|右图|左图|图中|图示|看图|<img|includegraphics|!\[|\.(?:png|jpg|jpeg|svg)', re.I)


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'EduMathBench-bulk-source-probe'})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read()


def download(task):
    dataset, revision, filename = task
    url = f'https://huggingface.co/datasets/{dataset}/resolve/{revision}/{filename}'
    path = OUT / 'raw' / dataset.replace('/', '__') / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    content = fetch(url)
    # 先确认逐行JSON可解析，避免把下载错误页面作为原始题库。
    rows = [json.loads(line) for line in content.decode('utf-8-sig').splitlines() if line.strip()]
    path.write_bytes(content)
    return {'dataset':dataset, 'revision':revision, 'filename':filename, 'url':url,
            'local_path':str(path.relative_to(ROOT)), 'bytes':len(content),
            'sha256':hashlib.sha256(content).hexdigest(), 'rows':rows}


def cmm_options(value):
    if not isinstance(value, str):
        return None
    matches = list(re.finditer(r'(?:^|\n)\s*([A-F])\s*[.．、:：)）]\s*', value))
    if [m.group(1) for m in matches] != list('ABCD'):
        return None
    opts = [value[m.end(): matches[i+1].start() if i+1 < len(matches) else len(value)].strip()
            for i, m in enumerate(matches)]
    return opts if all(opts) else None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tasks, revisions = [], {}
    for dataset, filenames in DATASETS.items():
        metadata = json.loads(fetch('https://huggingface.co/api/datasets/' + dataset))
        revisions[dataset] = metadata['sha']
        for filename in filenames:
            tasks.append((dataset, metadata['sha'], filename))
    manifests, statistics, pool, tal_pool = [], {}, [], []
    with ThreadPoolExecutor(max_workers=3) as executor:
        for result in executor.map(download, tasks):
            rows = result.pop('rows')
            manifests.append(result)
            dataset = result['dataset']
            stat = statistics.setdefault(dataset, {'total':0, 'levels':Counter(), 'dataset_names':Counter(),
                                                   'subjects':Counter(), 'four_choice_valid_answer':0,
                                                   'junior_records':0, 'junior_text_structural_candidates':0,
                                                   'candidate_levels':Counter(), 'candidate_subjects':Counter(),
                                                   'candidate_counts_by_source':Counter()})
            stat['total'] += len(rows)
            for number, row in enumerate(rows, 1):
                if dataset == 'ecnu-icalk/cmm-math':
                    level = row.get('level', '')
                    stat['levels'][level] += 1
                    stat['subjects'][str(row.get('subject', ''))] += 1
                    options = cmm_options(row.get('options'))
                    answer = row.get('answer')
                    valid = options is not None and answer in list('ABCD')
                    stat['four_choice_valid_answer'] += bool(valid)
                    junior = level in {'初一','初二','初三','七年级','八年级','九年级'}
                    stat['junior_records'] += junior
                    if not (junior and valid and row.get('image') == []):
                        continue
                    text = row.get('question', '') + '\n' + '\n'.join(options)
                    if not row.get('question') or FIGURE.search(text):
                        continue
                    stat['junior_text_structural_candidates'] += 1
                    stat['candidate_levels'][level] += 1
                    stat['candidate_subjects'][str(row.get('subject', ''))] += 1
                    pool.append({**row, 'bulk_provenance':{
                        'dataset':dataset, 'revision':result['revision'], 'file':result['filename'],
                        'line':number, 'url':result['url'], 'local_path':result['local_path'],
                        'original_id':row.get('id'),
                        'status':'bulk_candidate_requires_deduplication_and_curriculum_tagging'}})
                else:
                    stat['junior_records'] = None
                    stat['junior_text_structural_candidates'] = None
                    stat['dataset_names'][str(row.get('dataset_name', ''))] += 1
                    nested = row.get('answer_option_list', [])
                    valid = (len(nested) == 4 and all(isinstance(o, list) and len(o) == 1 for o in nested)
                             and [o[0].get('aoVal') for o in nested] == list('ABCD')
                             and all(o[0].get('content') for o in nested)
                             and row.get('answer_value') in list('ABCD'))
                    stat['four_choice_valid_answer'] += bool(valid)
                    # TAL样本没有独立年级字段，不能把竞赛知识点或内部dataset_name猜成年级。
                    if valid and str(row.get('dataset_name', '')).startswith('mid_'):
                        text = row.get('problem', '') + '\n' + '\n'.join(o[0]['content'] for o in nested)
                        if row.get('problem') and not FIGURE.search(text):
                            tal_pool.append({**row, 'bulk_provenance':{
                                'dataset':dataset, 'revision':result['revision'], 'file':result['filename'],
                                'line':number, 'url':result['url'], 'local_path':result['local_path'],
                                'original_id':row.get('queId'),
                                'scope_hint':'mid_dataset_name_only_not_final_curriculum_grade',
                                'status':'bulk_candidate_requires_scope_completeness_and_deduplication_checks'}})
    groups = defaultdict(list)
    for row in pool + tal_pool:
        p = row['bulk_provenance']
        question = row.get('question', row.get('problem', ''))
        options = cmm_options(row.get('options')) if 'options' in row else [o[0]['content'] for o in row['answer_option_list']]
        content = [re.sub(r'\s+', '', unicodedata.normalize('NFC', v)) for v in [question] + options]
        key = hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()
        groups[key].append({'dataset':p['dataset'], 'original_id':p['original_id'], 'file':p['file'], 'line':p['line']})
    (OUT / 'exact_duplicate_groups.jsonl').write_text(''.join(
        json.dumps({'fingerprint':k, 'records':v}, ensure_ascii=False) + '\n' for k, v in groups.items() if len(v) > 1), encoding='utf-8')
    summary = {'probed_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
               'statistics':statistics, 'manifests':manifests,
               'candidate_pool_count_before_deduplication':len(pool),
               'tal_middle_scope_hint_candidates':len(tal_pool),
               'combined_preliminary_candidates':len(pool) + len(tal_pool),
               'conservative_exact_unique_candidates':len(groups),
               'conservative_exact_duplicate_records':sum(len(v) - 1 for v in groups.values()),
               'note':'候选数不是初版完成数；level为来源学段，尚未按主要知识重判年级、模块和配额。无图片字段及图形提示是初步过滤，仍需检查未标注的图依赖和近重复。'}
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'cmm_junior_text_candidates.jsonl').write_text(
        ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in pool), encoding='utf-8')
    (OUT / 'tal_middle_scope_candidates.jsonl').write_text(
        ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in tal_pool), encoding='utf-8')
    print(json.dumps({'downloaded_rows':sum(s['total'] for s in statistics.values()),
                      'cmm_candidates':len(pool), 'tal_provisional_scope_candidates':len(tal_pool),
                      'conservative_exact_unique_candidates':len(groups)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
