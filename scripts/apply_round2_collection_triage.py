"""应用本轮人工分诊；只修正知识标签，保留源题与源答案。"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXES = {
    '5446': (8, '数与式', '二次根式因式移入根号', '需先由根式有意义确定a为负，再将外部因式移入根号并保留负号，主要知识为二次根式性质。'),
    '1113': (9, '几何', '相似三角形面积比', '以相似三角形面积比等于相似比的平方解答，属于相似知识。'),
    '1116': (9, '几何', '相似三角形对应边', '两个形状相同的三角形框架按对应边成比例缩放，属于相似知识。'),
    '5813': (8, '数与式', '非负数性质与二次根式运算', '由平方、根式、绝对值的非负性确定三个数再求和，主要知识为数与式；三角形周长为求和情境。'),
    '0': (9, '函数', '二次函数图像平移', '题干给出y=2x²并求抛物线平移后的解析式，主要知识是二次函数，而非一般图形平移。'),
    '1231': (9, '函数', '二次函数图像平移', '题干给出y=3x²并求平移后的新函数解析式，主要知识是二次函数。'),
    '322': (9, '几何', '圆内接四边形', '题干四边形内接于圆，利用对角互补确定比值关系，属圆的知识。'),
    '1173': (9, '函数', '二次函数与新定义最值', '需比较二次函数与一次函数并求min构成的最值；根号仅为结果形式，不能归七年级实数。'),
    '940': (9, '函数', '二次函数与一次函数综合', '题干抛物线与直线上的同高三点关系，核心是二次函数对称轴和一次函数，不能仅按坐标归七年级几何。'),
    '23956': (8, '函数', '一次函数交点与整数条件', '两条直线交点需联立一次函数关系并施加整点条件，主要知识属一次函数。'),
    '2549': (8, '方程与不等式', '分式方程与整数解', '未知数出现在分母，需去分母、检验并结合整数解条件，不能归一元一次方程。'),
    '1206': (9, '函数', '函数增减性综合辨析', '题目比较一次、反比例与二次函数在给定区间的增减性，属于函数知识综合。'),
    '227': (9, '函数', '二次函数增减性', '由y=(x−1)²+3随x增大而减小确定区间，主要知识是二次函数的增减性。'),
    '23732': (8, '数与式', '分式有意义的条件', '分母x−4不得为零是分式的定义域条件，不是解不等式。'),
    '23883': (8, '数与式', '分式加减', '题干化简x/(x−1)+x/(1−x)，主要知识是分式加减。'),
    '2779': (8, '数与式', '二次根式与分式的整体代入', '需平方根式与倒数之和、利用完全平方恒等式整体代入，超出直接求平方根。'),
    '5436': (8, '数与式', '二次根式与分式有意义的条件', '需同时满足根号内非负和分母不为零，主要考查根式/分式有意义的条件。'),
    '1638': (7, '方程与不等式', '一元一次方程建模', '把两式互为相反数转化为和为零，再解一元一次方程；相反数是辅助条件。'),
    '1813': (7, '方程与不等式', '一元一次方程建模', '把两式互为相反数转化为和为零，再解一元一次方程；相反数是辅助条件。'),
}


def read(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()] if path.exists() else []


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in rows), encoding='utf-8')


def main():
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    path = ROOT / 'data/batches/bulk_001/questions.jsonl'
    rows = read(path)
    edits = []
    for q in rows:
        suffix = q['id'].removeprefix('EMB-P-BULK-CMM-')
        if q['id'].startswith('EMB-P-BULK-CMM-') and suffix in FIXES:
            grade, module, kp, reason = FIXES[suffix]
            original = {k: q[k] for k in ['grade', 'module', 'knowledge_point']}
            content = [q[k] for k in ['question', 'option_a', 'option_b', 'option_c', 'option_d', 'answer']]
            q.update(grade=grade, module=module, knowledge_point=kp,
                     label_resolution={'reviewer': 'primary_agent', 'reason': reason,
                                       'decision': 'correct_curriculum_labels_only', 'reviewed_at': now})
            assert content == [q[k] for k in ['question', 'option_a', 'option_b', 'option_c', 'option_d', 'answer']]
            if original != {k: q[k] for k in original}:
                edits.append({'id': q['id'], 'before': original,
                              'after': {k: q[k] for k in original}, 'reason': reason, 'reviewed_at': now})
    write(path, rows)
    # 同步到可重跑的整包筛选输入，避免未来重建时丢失此次修正。
    p = ROOT / 'data/bulk_work/quality_exclusions.jsonl'
    exclusions = {r['id']: r for r in read(p)}
    for suffix, (grade, module, kp, reason) in FIXES.items():
        key = 'EMB-P-BULK-CMM-' + suffix
        old = exclusions.get(key, {})
        exclusions[key] = {**old, 'id': key,
                           'risk_flags': list(dict.fromkeys(old.get('risk_flags', []) + ['curriculum_label_error'])),
                           'reason': reason, 'disposition': old.get('disposition', 'hold'),
                           'expected_grade': str(grade), 'expected_module': module,
                           'expected_knowledge_point': kp, 'reviewer': 'primary_agent', 'reviewed_at': now}
    write(p, list(exclusions.values()))
    log = ROOT / 'data/difficulty_work/coordinator_curriculum_corrections.jsonl'
    write(log, read(log) + edits)
    resolutions = [
        {'id': 'EMB-P-BULK-CMM-1422', 'decision': 'reject', 'reason':
         '源answer为B，但完整题面中仅π−1是无理数，其他数均有理；同条源解析明确答案A。保留源B并退回，不猜测更改题面。'},
        {'id': 'EMB-P-BULK-CMM-2616', 'decision': 'reject', 'reason':
         '题干第一式为πx+y=0且给出x=1,y=−2，二者矛盾；题干问2m+n却未定义m，源解析使用mx+y=0。保留原题并退回，不将π猜改为m。'},
    ]
    pairs = [('EMB-P-BULK-CMM-1502', 'EMB-P-BULK-CMM-1552'),
             ('EMB-P-BULK-CMM-1500', 'EMB-P-BULK-CMM-1507'),
             ('EMB-P-BULK-CMM-1638', 'EMB-P-BULK-CMM-1813'),
             ('EMB-P-BULK-TAL-0005bdfa24104b999c91bf403480acf4',
              'EMB-P-BULK-TAL-104dc22addc74cd684c45c3444f54fcc')]
    for primary, duplicate in pairs:
        resolutions.append({'id': duplicate, 'decision': 'merge_verified_duplicate',
                            'primary_id': primary, 'comparison': 'math_presentation',
                            'reason': '人工比较题干、四项及源答案一致；差异仅为题末答题空括号/标点或字母的mathrm字体命令。合并来源，不更改任何数字、运算符、指数、原题或答案。'})
    for r in resolutions:
        r.update(reviewer='primary_agent', review_method='visible_source_issue_triage', reviewed_at=now)
    write(ROOT / 'data/resolutions/round2_visible_issues.jsonl', resolutions)
    print(json.dumps({'curriculum_corrections': len(edits), 'confirmed_rejections': 2,
                      'reviewed_duplicate_pairs': len(pairs)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
