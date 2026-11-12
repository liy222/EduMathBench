"""分诊附表报告的后续候选，明确保留、暂停、退回或合并。"""
import importlib.util
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()] if path.exists() else []


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in rows), encoding='utf-8')


def main():
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    path = ROOT / 'data/batches/bulk_001/questions.jsonl'
    rows = read(path)
    by_id = {q['id']: q for q in rows}
    fixes = {
        'EMB-P-BULK-TAL-0523dddad54b46dcbd91a6080961c740': (8, '数与式', '整式配方与整数取值', '对x²+y²≤2x+2y配方后依据整数平方枚举，未考查函数关系；坐标仅为整数对表示。'),
        'EMB-P-BULK-TAL-776ddede051a4c98a91c3af01f6dd50c': (8, '数与式', '整式配方与整数取值', '对x²+y²≤2x+2y配方后依据整数平方枚举，未考查函数关系；坐标仅为整数对表示。'),
        'EMB-P-BULK-TAL-c6172be053ad450689cf3e890189f697': (7, '几何', '象限与坐标符号', '题干仅由第二象限横负纵正确定参数范围，没有函数关系，按纯坐标题归七年级几何。'),
    }
    edits = []
    for key, (grade, module, kp, reason) in fixes.items():
        q = by_id[key]
        before = {k: q[k] for k in ['grade', 'module', 'knowledge_point']}
        q.update(grade=grade, module=module, knowledge_point=kp,
                 label_resolution={'reviewer': 'primary_agent', 'reason': reason,
                                   'decision': 'correct_curriculum_labels_only', 'reviewed_at': now})
        edits.append({'id': key, 'before': before, 'after': {k: q[k] for k in before}, 'reason': reason, 'reviewed_at': now})
    held_id = 'EMB-P-BULK-TAL-1c6465c07ec14243a9df061efcde60a0'
    by_id[held_id]['status'] = 'needs_review'
    by_id[held_id]['risk_flags'] = list(dict.fromkeys(by_id[held_id]['risk_flags'] + ['conditions_incomplete']))
    by_id[held_id]['quality_annotation'] = {'reason': '直角三角形可能为等腰直角、也可能非等腰，未给边长或图形，无法确定是否轴对称；保留来源A并暂停。', 'reviewer': 'primary_agent'}
    write(path, rows)
    quality_path = ROOT / 'data/bulk_work/quality_exclusions.jsonl'
    quality = {q['id']: q for q in read(quality_path)}
    for key, (grade, module, kp, reason) in fixes.items():
        quality[key] = {'id': key, 'risk_flags': ['curriculum_label_error'], 'disposition': 'hold',
                        'expected_grade': str(grade), 'expected_module': module,
                        'expected_knowledge_point': kp, 'reason': reason, 'reviewer': 'primary_agent', 'reviewed_at': now}
    quality[held_id] = {'id': held_id, 'risk_flags': ['conditions_incomplete'], 'disposition': 'hold',
                        'reason': by_id[held_id]['quality_annotation']['reason'], 'reviewer': 'primary_agent', 'reviewed_at': now}
    write(quality_path, list(quality.values()))
    p = ROOT / 'data/difficulty_work/coordinator_curriculum_corrections.jsonl'
    write(p, read(p) + edits)
    reasons = {
        'EMB-P-BULK-CMM-23727': '题干“都扩大 大倍”缺失倍数，不能根据源解析猜补为3；选项缩放描述也不完整，保留源C并退回。',
        'EMB-P-BULK-CMM-5350': '声称一个数据被污损，却列出完整7数且其和25与平均数4要求总和28矛盾；解析改第二个2为未知数，不能猜改题面，保留源A并退回。',
        'EMB-P-BULK-CMM-5495': '数据变换多项写成x_{1−2}等未定义下标，源解析使用3x_i−2，当前题面与解析不一致，保留源D并退回。',
        'EMB-P-BULK-CMM-5584': '源C给k=±1会令二次项系数k²−1为零，与一元二次方程条件矛盾；正确范围k≠±1未提供，保留源C并退回。',
        'EMB-P-BULK-CMM-5852': '源D的嵌套分式1/(1/(3x))化简为3x，不是反比例函数；当前四项无正确选项，源解析公式也有损坏，保留源D并退回。',
    }
    p = ROOT / 'data/resolutions/round2_additional_issues.jsonl'
    resolutions = [{'id': key, 'decision': 'reject', 'reason': reason} for key, reason in reasons.items()]
    spec = importlib.util.spec_from_file_location('collection', ROOT / 'scripts/check_collection.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    primary = by_id['EMB-P-BULK-TAL-0523dddad54b46dcbd91a6080961c740']
    duplicate = by_id['EMB-P-BULK-TAL-776ddede051a4c98a91c3af01f6dd50c']
    resolutions.append({'id': duplicate['id'], 'decision': 'merge_verified_duplicate', 'primary_id': primary['id'],
                        'comparison': 'reviewed_stem_same_options',
                        'primary_fingerprint': mod.fingerprint(primary), 'duplicate_fingerprint': mod.fingerprint(duplicate),
                        'reason': '完整人工比对：条件同为x²+y²≤2x+2y；整数坐标点(x,y)个数与整数对(x,y)对数为同一任务；四选项10/9/7/5及源B一致。两个确切文本版本摘要锁定，合并并保留源。'})
    for key in ['EMB-P-BULK-CMM-2436', 'EMB-P-BULK-CMM-3416']:
        resolutions.append({'id': key, 'decision': 'retain_same_family', 'family_id': 'EMB-F-CIRCLE-AXES-2-1-R1',
                            'reason': '同一圆心(2,1)、半径1情境；一题判断必与哪个轴相切，另一题判断两个轴的完整位置关系，四项任务不同，保留两题到共同题族。'})
    for r in resolutions:
        r.update(reviewer='primary_agent', review_method='visible_source_issue_triage', reviewed_at=now)
    write(p, resolutions)
    dismissed = [
        {'ids': ['EMB-P-BULK-CMM-5563'], 'decision': 'retain', 'reason': 'ab<0不单独推出a<0；结合根式有意义得到a>0、b<0，源A=−b√a正确，已纠正误报。'},
        {'ids': ['EMB-P-BULK-TAL-ff8080814db3e529014dd125654f5317'], 'decision': 'retain', 'reason': '题干明确一次函数；m=2令第一式斜率零，不满足条件，源D=−1正确。'},
        {'ids': ['EMB-P-BULK-TAL-02b66527a4e948e1b3e11a7d31653947'], 'decision': 'retain', 'reason': '选项B是故意错误的干扰项，不能因其不等于正确勾股公式认定转录缺根号。'},
        {'ids': ['EMB-P-BULK-CMM-4506', 'EMB-P-BULK-TAL-c6172be053ad450689cf3e890189f697'], 'decision': 'not_duplicate', 'reason': '前者考查两点关于x轴对称，后者考查点在第二象限；条件、所问参数和四项均不同，重复候选误配ID。'},
        {'ids': ['EMB-P-BULK-CMM-1200', 'EMB-P-CJEVAL-TEST-000193'], 'decision': 'not_duplicate', 'reason': '前者给开口向下抛物线上四点并比较m,p,q，后者给相切x轴抛物线上两点求n，数学条件和任务不同，重复候选误配ID。'},
        {'ids': ['EMB-P-BULK-CMM-23778'], 'decision': 'retain_source_text', 'reason': '源D写02，按整数2读也是干扰项；不能自行猜改为0.2。题干和源B=5一致，保留源文本。'},
        {'ids': ['EMB-P-BULK-CMM-5813'], 'decision': 'retain_source_text', 'reason': '等式链“表达式=0=0”有冗余但等价于表达式=0，未造成条件矛盾；保留源文本，主要知识已修正为非负数与根式运算。'},
    ]
    for r in dismissed:
        r.update(reviewer='primary_agent', reviewed_at=now)
    write(ROOT / 'data/difficulty_work/coordinator_quality_dispositions.jsonl', dismissed)
    print(json.dumps({'additional_curriculum_corrections': len(edits), 'additional_rejections': len(reasons),
                      'held': 1, 'semantic_duplicate_merged': 1, 'family_grouped': 2,
                      'dismissed_or_retained_candidates': len(dismissed)}))


if __name__ == '__main__':
    main()
