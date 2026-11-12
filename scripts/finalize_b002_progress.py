import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
progress=json.loads((ROOT/'data/reports/variant_collection_progress.json').read_text(encoding='utf-8'))
assert progress['variant_count']==90 and progress['independent_reviewed_variants']==90 and progress['independent_review_pending']==0
note='''# B002变式草稿交付

2026-10-14。本批新增60道，七、八、九年级各20道；暂定难度24基础/24中等/12困难。累计90道，各年级30道，暂定难度36基础/36中等/18困难，全部纯文字。

60个新母题均来自冻结300候选，不重复使用首批30母题；source_type=variant，四选项、母题题族、source定位、修改说明和推导完整。Luna的来源字段核对60/60通过。主代理独立初核七八年级40题，八年级生成岗位独立初核主代理接续生成的九年级20题，最终题面哈希逐题绑定。90个累计草稿全部通过结构、显式计算和独立初核，仍待正式复核与冻结。

生成子代理曾返回使用额度限制。七、八年级脚本/数据已保存，主代理接续执行并补齐九年级。之后普通使用权限恢复，补完独立复核，不将期间的生成者自检当作独立审查。没有新增付费API调用。

主代理修正了G7-014候选答案字母（计算值6，对应D）及G7方程组排版。G8缩放分式明确非零分子，避免零值比例的边界歧义；新素数题使用完整平方差与因数分类证明。G9旋转题补充顶点坐标、转角和第二交点定义，几何文字条件可独立构图，无需变式配图。源题原始记录未改。

累计交付：data/variants/collection/questions.jsonl、questions.csv、pairs.json；可视化/变式题库浏览.html；data/exports/EduMathBench_variants_90_draft.zip。首批30的历史交付继续保留，使用最新合集时不再重复合并首批。

浏览页包含90题对、633段公式、20个内嵌字体和3个母题原图引用（变式无图）。公式引擎与全部题对的模拟筛选/翻页检查通过；这不替代真实浏览器、像素布局或所有屏宽检查，新页面尚未取得实际浏览器报告。

1500公开题与冻结300母题清单不变，公开题＋90变式共1590道草稿。下一批继续纯文字优先，尚需210道变式；达到300后再汇总1800并按题族同侧划分，尚未进行评测实验。
'''
(ROOT/'data/variants/batches/b002/completion_report.md').write_text(note,encoding='utf-8')
overview='''最新进度（2026-10-14）：累计90道纯文字变式草稿，各年级30道；来源、显式计算和独立题面初核已通过，未最终批准。新增B002为60道，首批30已包含在合集内，不重复合并。还需210道变式。通用合集见data/variants/collection/questions.jsonl与questions.csv，数据包data/exports/EduMathBench_variants_90_draft.zip，本地预览可视化/变式题库浏览.html；检查范围见data/variants/batches/b002/completion_report.md。
'''
for rel in ['docs/variant_stage_plan.md','docs/next_batches.md','data/reports/variant_stage_progress.md']:
    path=ROOT/rel;text=path.read_text(encoding='utf-8')
    if overview not in text:
        first,rest=text.split('\n',1);text=first+'\n\n'+overview+'\n'+rest
    path.write_text(text,encoding='utf-8')
p=ROOT/'README.md';t=p.read_text(encoding='utf-8')
heading='变式阶段已启动：300道母题候选已选出'
pos=t.index(heading);end=t.index('\n',pos)
t=t[:pos]+'变式阶段已启动：冻结300母题候选，累计生成90道纯文字变式草稿，各年级30道，暂定难度36基础/36中等/18困难。来源关联、显式计算和独立题面初核通过，仍待正式复核与冻结。双击[可视化/变式题库浏览.html](可视化/变式题库浏览.html)可离线浏览90个题对；通用交付为[data/exports/EduMathBench_variants_90_draft.zip](data/exports/EduMathBench_variants_90_draft.zip)。新页面633段公式和模拟控制检查通过，真实浏览器运行尚未补验。剩余210道变式，后续继续纯文字优先，几何任务保留完整条件。此前7道缺图提示已更正为筛选漏读image_assets误报。进度见[data/reports/variant_collection_progress.json](data/reports/variant_collection_progress.json)及[data/variants/batches/b002/completion_report.md](data/variants/batches/b002/completion_report.md)。'+t[end:]
p.write_text(t,encoding='utf-8')
p=ROOT/'data/visualization/variant_pairs_template.html';t=p.read_text(encoding='utf-8')
old="block(change,'状态：变式草稿，显式计算与独立题面推导已初核，待正式复核。');"
new="block(change,'状态：变式草稿。'+(['independent_draft_review','independent_reviewer_checked'].includes((variant.verification_note||{}).prose_derivation_review)?'显式计算与独立题面推导已初核，待正式复核。':'显式计算与生成者自检通过，独立复核待完成。'));"
if old in t:t=t.replace(old,new)
p.write_text(t,encoding='utf-8')
print('B002 progress and local review-state display finalized')
