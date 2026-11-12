"""导出公开题初版的通用JSONL/CSV，验证字段和往返一致性；不改变源题。"""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from question_format import canonical_question, VERSION

ROOT = Path(__file__).resolve().parents[1]
NAME = 'EduMathBench_public_draft_v0.1'


def main():
    src = ROOT / 'data/public_draft/questions.jsonl'
    original = [json.loads(line) for line in src.read_text(encoding='utf-8').splitlines()]
    quotas = json.loads((ROOT / 'config/quotas.json').read_text(encoding='utf-8'))
    counts = Counter((q['grade'], q['module']) for q in original)
    assert len(original) == quotas['public_target'], '公开题数量配额尚未完成'
    assert len({q['id'] for q in original}) == len(original), '题号重复'
    for cell in quotas['cells']:
        assert counts[cell['grade'], cell['module']] == cell['target'], '年级模块配额不匹配'
    rows = []
    image_files = {}
    for q in original:
        q = canonical_question(q)
        assert q['status'] == 'auto_checked' and q['answer'] in 'ABCD'
        options = {c: q['option_' + c.lower()] for c in 'ABCD'}
        assert all(isinstance(text, str) and text.strip() for text in options.values())
        source = {'id': q['source_id'], 'title': q['source_title'], 'url': q['source_url'],
                  'reference': q['source_ref'], 'answer_location': q['source_answer_location'],
                  'raw_path': q['source_raw_path'], 'accessed_at': q['source_accessed_at'],
                  'material_year': q['source_material_year'], 'region': q['source_region'],
                  'access_status': q['source_access_status'], 'reuse_status': q['source_reuse_status'],
                  'notes': q['source_notes']}
        assert all(source[k] for k in ['id', 'title', 'url', 'reference', 'answer_location', 'raw_path'])
        assert (ROOT / source['raw_path']).is_file(), '来源原件路径不存在'
        assets = []
        for a in q.get('image_assets', []):
            p = ROOT / a['path']
            assert hashlib.sha256(p.read_bytes()).hexdigest() == a['sha256']
            name = 'images/' + a['sha256'][:16] + p.suffix.lower()
            image_files[name] = p
            assets.append({**a, 'path': name, 'source_project_path': a['path']})
        rows.append({'id': q['id'], 'question': q['question'], 'options': options,
                     'input_modality': q.get('input_modality', 'text_image' if assets else 'text'),
                     'image_assets': assets,
                     'answer': q['answer'], 'grade': q['grade'], 'module': q['module'],
                     'knowledge_point': q['knowledge_point'], 'difficulty': q['difficulty'],
                     'source_type': q['source_type'], 'source_exam_grade': q.get('source_exam_grade', ''),
                     'source': source, 'additional_sources': q.get('additional_sources', []),
                     'solution': q.get('solution', ''), 'family_id': q.get('family_id', ''),
                     'parent_id': q.get('parent_id', ''), 'status': q['status'],
                     'risk_flags': q.get('risk_flags', []), 'batch_id': q['batch_id'],
                     'source_question_kind': q.get('source_question_kind', ''),
                     'provenance': q.get('provenance', {}),
                     'difficulty_annotation': q.get('difficulty_annotation', {}),
                     'quality_annotation': q.get('quality_annotation', {}),
                     'source_input': q['source_input'],
                     'format_normalization': q['format_normalization'],
                     'label_resolution': q.get('label_resolution', {})})
    out = ROOT / 'data/exports'
    out.mkdir(exist_ok=True)
    json_path = out / (NAME + '.jsonl')
    json_path.write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in rows), encoding='utf-8')
    flat_rows = []
    for q in rows:
        flat_rows.append({**{k: v for k, v in q.items() if k not in {'options', 'source'}},
                          **{'option_' + c.lower(): q['options'][c] for c in 'ABCD'},
                          **{'source_' + k: v for k, v in q['source'].items()}})
    fields = ['id', 'question', 'option_a', 'option_b', 'option_c', 'option_d', 'answer',
              'grade', 'module', 'knowledge_point', 'difficulty']
    fields += [k for k in flat_rows[0] if k not in fields]
    csv_path = out / (NAME + '.csv')
    with csv_path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                         for k, v in q.items()} for q in flat_rows)
    # 逐题确认JSONL/CSV转换没有损失题干、公式、选项、源答案及来源定位。
    loaded = [json.loads(s) for s in json_path.read_text(encoding='utf-8').splitlines()]
    assert loaded == rows
    with csv_path.open(encoding='utf-8-sig', newline='') as f:
        csv_rows = list(csv.DictReader(f))
    assert len(csv_rows) == len(rows)
    for q, c, raw in zip(rows, csv_rows, original):
        canonical = canonical_question(raw)
        for field in ['id', 'question', 'answer', 'source_ref', 'source_title', 'source_url', 'source_raw_path']:
            exported = c['source_reference'] if field == 'source_ref' else c[field]
            assert exported == (canonical[field] if field == 'question' else raw[field]), (q['id'], field)
        for letter in 'abcd':
            assert c['option_' + letter] == canonical['option_' + letter]
        assert json.loads(c['source_input']) == {k:raw[k] for k in ['question','option_a','option_b','option_c','option_d']}
        assert json.loads(c['format_normalization']) == q['format_normalization']
        assert json.loads(c['additional_sources']) == q['additional_sources']
        assert json.loads(c['risk_flags']) == q['risk_flags']
        assert json.loads(c['difficulty_annotation']) == q['difficulty_annotation']
        assert json.loads(c['label_resolution']) == q['label_resolution']
        assert json.loads(c['image_assets']) == q['image_assets']
    pending = [q for q in csv_rows if q['difficulty'] == 'pending']
    with (out / 'difficulty_pending.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'grade', 'module', 'knowledge_point', 'difficulty'])
        writer.writeheader()
        writer.writerows({k: q[k] for k in writer.fieldnames} for q in pending)
    (out / 'question_sources.csv').write_bytes((ROOT / 'data/registry/question_sources.csv').read_bytes())
    guide = '''# EduMathBench 公开题初版通用格式

公开题1500道，七、八、九年级各500道。状态为初版、待集中复核。

JSONL使用UTF-8，每行一个独立题目对象；CSV使用带BOM的UTF-8，遵循标准引号与换行转义，可由表格软件或通用CSV读取器导入。两种格式题目顺序及内容一致，选项不重排，答案不重算。question及options使用规范化Unicode和LaTeX；原转换后的题面逐字保留在source_input，规范化规则与摘要在format_normalization。原始来源归档与主库原文保持不变。

| 字段 | 含义 |
|---|---|
| id / question | 稳定题号 / 完整题干 |
| options | JSONL对象，固定A、B、C、D四个键；CSV对应option_a至option_d |
| input_modality / image_assets | text或text_image / 原题输入图片及来源、角色、文件路径、SHA-256 |
| answer | 来源给出的A/B/C/D字母；未声明全库数学正确 |
| grade / source_exam_grade | 主要知识归属年级 / 原材料试卷年级，后者允许空值 |
| module / knowledge_point | 主要知识模块 / 知识点 |
| difficulty | 基础、中等、困难或pending；标签暂定 |
| source | 标题、网址、本题定位、答案位置、原件路径、取得时间与复用说明；CSV展平为source_前缀列 |
| additional_sources | 已合并重复题的其他来源，保留各自定位 |
| solution | 来源解析，可为空 |
| family_id / parent_id | 已知题族 / 母题；本版仅公开题，母题为空 |
| status / risk_flags | auto_checked仅指结构通过；保留未完成数学复核、教材版本、来源复用等提示 |
| batch_id / source_type | 收集批次 / public |
| source_question_kind / provenance | 数据集题类及锁定版本、原记录定位等，可为空 |
| difficulty_annotation / label_resolution | 暂定难度的具体依据、标注者与时间 / 知识分类修正依据，可为空 |
| quality_annotation | 已知质量问题的专项处置依据，可为空；不等于全库数学验算 |
| source_input / format_normalization | 规范化前完整题干、四选项 / 逐字段格式转换规则与前后摘要，不作为评测输入 |

CSV的additional_sources、risk_flags、provenance、difficulty_annotation、label_resolution、quality_annotation、image_assets、source_input和format_normalization数组或对象以JSON文本存储；其余列是标量。缺失的可选字段使用空字符串，不猜测数值。source_material_year是资料年份，不自动等于原试卷年份。

question_sources.csv覆盖初版、候补、异常题及已合并来源；用题号和“合并到题号”关联。difficulty_pending.csv列出本次1500题中难度待定的题号。manifest.json记录数据数量与各文件SHA-256；ZIP包含全部上述交付文件。

source_raw_path相对D:/EduMathBench项目根目录。原始HTML/PDF/数据集材料仍保存在项目内，未放入轻量导出包；在其他电脑可按来源网址、题号和provenance定位。二手数据集、改写试题、概念题和来源复用限制均保留说明。

年级模块数量配额已满足；暂定难度实际数量及各年级分布见manifest.json和completion_report.md。全库达到600基础/600中等/300困难，各年级内部未达到同一比例；没有通过抬高旧题标签补足数量。教材适配、数学正确性和近重复题族仍未定稿。本版未划分dev/test，也不是最终冻结集。
'''
    guide += '\n图像题的image_assets只含题干图和选项图，role为stem或option，选项图有option字母。path相对于导出目录/ZIP根目录；sha256校验图片。题面保留原<ImageHere>占位符，通常按出现次序对应同role、同option的图片；没有占位符的stem图显示在题干之后。少数来源将题干图误放在选项字段，本版保留源文本，source_placeholder_field记录原占位字段，但展示与输入按复核后的role放置图片，不将该图误作选项。解析图不放入image_assets。评测输入应只取question、options及image_assets；answer与solution另行保存，不传给模型。\n'
    (out / 'FORMAT.md').write_text(guide, encoding='utf-8')
    files = [json_path, csv_path, out / 'question_sources.csv', out / 'difficulty_pending.csv', out / 'FORMAT.md']
    for name in ['provenance_audit.md', 'raw_integrity_audit.json',
                 'difficulty_review.md', 'difficulty_annotation_audit.json', 'completion_report.md',
                 'format_check.md', 'canonical_question_format_audit.json', 'format_normalization_summary.json']:
        p = ROOT / 'data/reports' / name
        if p.is_file():
            target = out / name
            target.write_bytes(p.read_bytes())
            files.append(target)
    for name in ['browser_report_resolution.md', 'browser_report_verified_summary.json',
                 'browser_report_current_result.md', 'browser_report_review_v1_1.md', 'browser_report_20261014_v1_1.json']:
        p = ROOT / 'data/reports/luna_render_audit' / name
        if p.is_file():
            target = out / name
            target.write_bytes(p.read_bytes())
            files.append(target)
    manifest = {'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
                'collection_revision': '2026-10-14-input-format-v1.1',
                'stage': '公开题初版，待集中复核', 'count': len(rows),
                'grade_counts': dict(Counter(q['grade'] for q in rows)),
                'difficulty_counts': dict(Counter(q['difficulty'] for q in rows)),
                'grade_difficulty_counts': {str(g): dict(Counter(q['difficulty'] for q in rows if q['grade'] == g)) for g in [7,8,9]},
                'input_modality_counts': dict(Counter(q['input_modality'] for q in rows)),
                'hard_modality_counts': dict(Counter(q['input_modality'] for q in rows if q['difficulty'] == '困难')),
                'source_draft_sha256': hashlib.sha256(src.read_bytes()).hexdigest(),
                'input_format_version': VERSION,
                'roundtrip_verified_records': len(rows),
                'image_question_count': sum(bool(q['image_assets']) for q in rows),
                'image_file_count': len(image_files),
                'images': [{'name': name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size} for name, p in sorted(image_files.items())],
                'files': [{'name': p.name, 'bytes': p.stat().st_size,
                           'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
    mp = out / 'manifest.json'
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    files.append(mp)
    with ZipFile(out / (NAME + '.zip'), 'w', ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.name)
        for name, p in sorted(image_files.items()):
            target = out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
            z.write(p, name)
    print(json.dumps({'exported': len(rows), 'roundtrip_verified': len(csv_rows),
                      'difficulty_pending': len(pending), 'package': str(out / (NAME + '.zip'))}, ensure_ascii=True))


if __name__ == '__main__':
    main()
