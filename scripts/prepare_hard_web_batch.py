"""保存已经逐项对照公开题页的困难候选；不改现有1500题。"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/hard_collection/g9'
now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')

sources = {
    '22702749': {
        'source_id': 'SRC-HC-G9-22702749',
        'title': '2025中考数学二轮微专题03 二次函数含参解析式问题（原卷+解析）',
        'url': 'https://zy.21cnjy.com/22702749', 'year': 2025,
        'region': '福建/贵州等；按每题原标注', 'source_exam_grade': 9,
        'raw_path': 'data/hard_collection/g9/raw/22702749.html',
        'notes': '原专题的前五页公开预览经浏览器读取并归档SVG/PNG；题干公式以预览页为准，答案以公开文字解析的对应题为准。未取得原考试卷。',
        'difficulty_evidence': '含参二次函数专项定位，来源没有逐题困难标签；困难是依据完整题面补充的暂定判断。',
    },
    '25572206': {
        'source_id': 'SRC-HC-G9-25572206',
        'title': '【题型解读与技巧点拨】2026年中考数学二轮复习专题：专题10选题压轴题题型归类（解析版+原卷版）',
        'url': 'https://zy.21cnjy.com/25572206', 'year': 2026,
        'region': '四川/黑龙江等；按每题原标注', 'source_exam_grade': 9,
        'raw_path': 'data/hard_collection/g9/raw/25572206.html',
        'notes': '公开前五页题面预览已归档SVG/PNG，答案来自同专题公开文字解析。原题标注年份/地区保留；原中考试卷未取得。',
        'difficulty_evidence': '原专题明确定位为选择压轴题；此为编者专题筛选证据，没有实测样本或逐题难度系数。',
    },
}

# 原题内容按公开预览转录；来源“如图”保留，只有文字条件充分者入此候选池。
items = [
    ('22702749', 'VAR3', 3, '考点1变式3（2021福建厦门双十中学思明分校二模）',
     r'（2021·福建厦门·厦门双十中学思明分校校考二模）已知二次函数 $y=x^2-2bx+2b^2-4c$（其中 $x$ 是自变量）的图象经过不同两点 $A(1-b,m)$、$B(2b+c,m)$，且该二次函数的图象与 $x$ 轴有公共点，则 $b+c$ 的值（ ）',
     ['−1', '2', '3', '4'], 'C', '函数', '等高点对称关系与判别式约束',
     '由不同等高点建立对称轴关系，再把系数关系代入根的判别式；需要识别非正平方与非负判别式同时成立所形成的参数唯一性，不能直接代入已知数。'),
    ('22702749', 'AREA2', 4, '考点2变式2（2022福建福州教育学院附属中学校考模拟）',
     r'（2022·福建福州·福建省福州教育学院附属中学校考模拟预测）已知抛物线 $y=ax^2+bx+c\ (a\ne0)$ 与 $x$ 轴的交点为 $A(1,0)$ 和 $B(3,0)$，点 $P_1(x_1,y_1)$、$P_2(x_2,y_2)$ 是抛物线上不同于 $A$、$B$ 的两个点，记 $\triangle P_1AB$ 的面积为 $S_1$，$\triangle P_2AB$ 的面积为 $S_2$，有下列结论：①当 $x_1>x_2+2$ 时，$S_1>S_2$；②当 $x_1<2-x_2$ 时，$S_1<S_2$；③当 $|x_1-2|>|x_2-2|>1$ 时，$S_1>S_2$；④当 $|x_1-2|>|x_2+2|>1$ 时，$S_1<S_2$。其中正确结论的序号是（ ）',
     ['②③', '①③', '①②③④', '③'], 'D', '函数', '抛物线与三角形面积的绝对值比较',
     '面积取决于纵坐标绝对值，需区分根之间与根外的情况，再比较到对称轴的距离；逐项命题的条件并非都能保证面积顺序，需要排除缺乏位置约束的结论。'),
    ('25572206', 'SUIHUA', 1, '题型一例题1（2025黑龙江绥化中考）',
     r'（2025·黑龙江绥化·中考真题）如图，二次函数 $y=ax^2+bx+c$ 与 $x$ 轴交于点 $A(3,0)$、$B(-1,0)$，与 $y$ 轴交于点 $C(0,m)$，其中 $-4<m<-3$。则下列结论：① $a-c>0$；②方程 $ax^2+bx+c-5=0$ 没有实数根；③ $-\frac83<b<-2$；④ $\frac{a+b+c}{b-a}>0$。其中错误的个数有（ ）',
     ['1个', '2个', '3个', '4个'], 'A', '函数', '交点、系数范围与方程根的综合判断',
     '需由两个零点同时建立三系数之间的比例，再用纵截距范围求系数范围，并把带常数的方程转换为直线与抛物线交点问题，综合判断四个不同形式的命题。'),
    ('25572206', 'DEYANG', 2, '题型一变式训练1（2025四川德阳中考）',
     r'（2025·四川德阳·中考真题）已知抛物线 $y=ax^2+bx+c$（$a,b,c$ 是常数，$a>0$）过点 $(1,0)$、$(m,0)$，且 $2<m<3$，该抛物线与直线 $y=kx+c$（$k,c$ 是常数，$k\ne0$）相交于 $A(x_1,y_1)$、$B(x_2,y_2)$ 两点（点 $A$ 在点 $B$ 左侧）。下列说法：① $bc<0$；② $3a+b>0$；③点 $A\prime$ 是点 $A$ 关于直线 $x=-\frac{b}{2a}$ 的对称点，则 $3<AA\prime<4$；④当 $x_2=4$ 时，不等式 $ax^2+(b-k)x<0$ 的解集为 $0<x<4$。其中正确的结论个数是（ ）',
     ['1', '2', '3', '4'], 'B', '函数', '含参交点位置分类与根区间综合',
     '同截距直线保证一个交点的横坐标为0，但它未必是左侧交点A；判断对称点距离必须区分另一个交点在0左右的两种情况，再结合根的范围和不等式符号判断其他结论。'),
    ('25572206', 'GUANGYUAN', 3, '题型一变式训练4（2024四川广元二模）',
     r'（2024·四川广元·二模）如图，抛物线 $y=ax^2+bx+c\ (a<0)$ 与 $x$ 轴交于 $A,B$ 两点，与 $y$ 轴正半轴交于点 $C$，对称轴是直线 $x=-1$，其顶点在第二象限，给出以下结论：①当 $m\ne-1$ 时，$a-b>am^2+bm$；②若 $ax_1^2+bx_1=ax_2^2+bx_2$ 且 $x_1\ne x_2$，则 $x_1+x_2=2$；③若 $OA=OC$，则 $OB=-\frac1a$；④若 $B(1,0),C(0,3)$，连接 $AC$，点 $P$ 在抛物线的对称轴上，且 $\angle PCA=90^\circ$，则 $P(-1,4)$。其中正确的有（ ）',
     ['①③④', '①②③', '①②④', '②③④'], 'A', '函数', '抛物线性质、截距关系与垂直几何综合',
     '除顶点最大值与等高点对称关系外，还需把OA=OC转为系数与截距约束；最后一个命题需联立固定交点求坐标，再用垂直条件求对称轴上的点，跨函数与几何逐项推理。'),
    ('25572206', 'HARBIN', 4, '题型二变式训练2（2025黑龙江哈尔滨三模）',
     r'（2025·黑龙江哈尔滨·三模）如图，在正方形 $ABCD$ 中，$AC$ 与 $BD$ 交于点 $O$，$H$ 为 $AB$ 延长线上的一点，$BH=BD$，连接 $DH$，分别交 $AC,BC$ 于点 $E,F$，连接 $BE$，则下列结论：① $\frac{CF}{BF}=\sqrt2$；② $\tan\angle H=2\sqrt2-2$；③ $BE$ 平分 $\angle CBD$；④ $2AB^2=DE\cdot DH$。其中正确结论的个数是（ ）',
     ['1', '2', '3', '4'], 'B', '几何', '正方形、相似、角平分线与三角函数综合',
     '要先从延长线和对角线长度构造含根号的边长关系，再通过相似/垂直平分线判定角平分关系与线段乘积；四个命题含不同几何转化，主要知识含锐角三角函数，归九年级。'),
]

rows=[]
for src, key, page, ref, question, options, answer, module, knowledge, reason in items:
    s=sources[src]
    rows.append({
        'id':f'HC-G9-{src}-{key}', 'question':question,
        **{f'option_{letter.lower()}':v for letter,v in zip('ABCD',options)},
        'answer':answer, 'grade':9, 'source_exam_grade':9,
        'module':module, 'knowledge_point':knowledge, 'difficulty':'困难',
        'source_id':s['source_id'], 'source_ref':f'公开原卷预览第{page}页；{ref}',
        'source_type':'public', 'solution':'',
        'source_title':s['title'], 'source_url':s['url'],
        'source_material_year':s['year'], 'source_region':s['region'],
        'source_answer_location':f'公开文字解析中“{ref.split("（")[0]}”对应【答案】{answer}；原解析含公式缺失，不复制为完整解析',
        'source_raw_path':s['raw_path'], 'source_accessed_at':now,
        'source_access_status':'public_text_and_first_five_preview_pages',
        'source_reuse_status':'unknown', 'source_notes':s['notes'],
        'source_image_files':[f'data/hard_collection/g9/raw/{src}-page{page}.svg',f'data/hard_collection/g9/raw/{src}-page{page}.png'],
        'source_difficulty_evidence':s['difficulty_evidence'],
        'difficulty_evidence':{'kind':'capstone_topic' if src=='25572206' else 'provisional_task_review',
                               'source_label':'选择压轴题' if src=='25572206' else '',
                               'source_value':None,'url':s['url'],'reference':f'专题说明及{ref}',
                               'empirical':False},
        'hardness_rationale':reason,
        'difficulty_annotation':{'difficulty':'困难','reason':reason,'model':'primary_agent',
                                 'annotated_at':now,'review_method':'public_preview_correspondence_and_task_review',
                                 'rule_version':'source-hard-v0.1','confidence':'medium'},
        'risk_flags':['secondary_source','provisional_difficulty','source_reuse_unknown','not_independently_solved'],
        'text_conditions_sufficient':True,'status':'candidate_for_review','batch_id':'hard_g9_web_001',
    })
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'candidates.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
(OUT/'source_manifest.jsonl').write_text(''.join(json.dumps({**s,'accessed_at':now,'reuse_status':'unknown'},ensure_ascii=False)+'\n' for s in sources.values()),encoding='utf-8')
print(json.dumps({'saved':len(rows),'sources':len(sources),'main_draft_unchanged':True}))
