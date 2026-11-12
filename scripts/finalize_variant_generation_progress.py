"""Final generation milestone only; no formal freeze, split, or evaluation."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
progress=json.loads((ROOT/'data/reports/variant_collection_progress.json').read_text(encoding='utf-8'))
assert progress['variant_count']==300 and progress['remaining_variants']==0
assert progress['independent_reviewed_variants']==300 and progress['independent_review_pending']==0
difficulty=progress['difficulty_counts']
report=f'''# 300道变式生成完成

2026-10-14，用户要求先完成全部变式。本批B003补齐210道，每年级70道；累计300道，每年级100道。全部纯文字，几何题用完整文字条件定义点、线、角和运动规则；必要母题原图在生成时查看，仍保留来源资产。

## 数据与检查

年级与模块配额全部达标。实际暂定难度：基础{difficulty.get('基础',0)}、中等{difficulty.get('中等',0)}、困难{difficulty.get('困难',0)}。原120/120/60是覆盖目标；按实际推理如实调整标签，不将简单题强标困难，没有教师或学生正确率校准。

300题一题一个母题，parent_id和family_id齐全，source_type=variant；每题有四选项、候选答案、修改说明、推导、难度理由和生成岗位/时间。全部通过来源关联、结构及显式计算检查，独立题面初核完成300题，最终文字/选项/答案/推导与复核哈希绑定。显式计算/代表点检查不充当通用定理证明器，独立初核仍不等于正式数学批准。

首批90道内容及1500公开题源记录保持不变。本批发现一处原母题误将文具单价题标成九年级几何/圆，已同格替换为真实圆周角分类题；原候选快照与替换账本保留。B003各年级generation_notes记录源解析算术/条件问题和修正，不修改来源原文。交叉初核修正集合完整性、等价干扰项、定理退化和位置指代等问题，详见review_g*.json。

## 交付

- 通用JSONL：data/variants/collection/questions.jsonl
- UTF-8带BOM CSV：data/variants/collection/questions.csv
- 全部题对：data/variants/collection/pairs.json
- 离线浏览：可视化/变式题库浏览.html
- 数据包：data/exports/EduMathBench_variants_300_draft.zip

页面内置必要母题原图、公式库和字体，不需要联网加载这些资源。公式引擎及模拟控制检查另报；尚未取得新页面实际浏览器运行报告，不借用1500公开题的旧报告冒充新页面通过。

1500公开题＋300变式的数量门槛已齐，共1800道草稿记录。尚未正式合并冻结、划分开发/测试或运行评测实验。生成阶段不再有未完成题目；后续任务是全库质量整理、题族同侧划分和冻结。
'''
(ROOT/'data/variants/batches/b003/completion_report.md').write_text(report,encoding='utf-8')
overview=f'''最新进度（2026-10-14）：全部300道变式草稿已生成，各年级100道，全部纯文字；实际暂定难度{difficulty.get('基础',0)}基础/{difficulty.get('中等',0)}中等/{difficulty.get('困难',0)}困难。来源关联、显式计算检查与独立题面初核完成300题，仍未正式批准或冻结。1500公开题＋300变式数量门槛齐，共1800道草稿；尚未划分或评测。最新数据包data/exports/EduMathBench_variants_300_draft.zip，本地可视化/变式题库浏览.html，通用data/variants/collection/questions.jsonl与questions.csv。详情data/variants/batches/b003/completion_report.md。
'''
for rel in ['docs/variant_stage_plan.md','docs/next_batches.md','data/reports/variant_stage_progress.md']:
    p=ROOT/rel;t=p.read_text(encoding='utf-8')
    # Replace only the current overview; retain historical milestones below it.
    lines=t.splitlines();lines=[line for line in lines if not line.startswith('最新进度（2026-10-14）：')]
    title=lines[0];t=title+'\n\n'+overview+'\n'+'\n'.join(lines[1:])+'\n';p.write_text(t,encoding='utf-8')
p=ROOT/'README.md';t=p.read_text(encoding='utf-8')
start=t.index('变式阶段已启动：');end=t.index('\n',start)
t=t[:start]+f'全部300道变式草稿已生成，各年级100道，全部纯文字。实际暂定难度{difficulty.get("基础",0)}基础/{difficulty.get("中等",0)}中等/{difficulty.get("困难",0)}困难。来源关联、结构、显式计算和独立题面初核通过，仍待正式复核与冻结。双击[可视化/变式题库浏览.html](可视化/变式题库浏览.html)离线浏览全部题对；[data/exports/EduMathBench_variants_300_draft.zip](data/exports/EduMathBench_variants_300_draft.zip)包含JSONL、CSV、母题来源及复核记录。新页公式/模拟控制检查完成，真实浏览器实测尚未补验。1500公开题＋300变式的1800题数量门槛齐，尚未划分或评测。进度见[data/variants/batches/b003/completion_report.md](data/variants/batches/b003/completion_report.md)。'+t[end:]
p.write_text(t,encoding='utf-8')
print('Final 300-variant generation milestone recorded; freeze and experiments not started')
