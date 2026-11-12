# 当前版本：成员复核修订 v0.3，已具备本地评测程序

2026-11-11最新进度：步骤1补验与步骤2六家开发集运行已完成，输入、提示词和请求参数已冻结。六家各完成同一150题，共900份答题记录；本轮记账922/1000次（含重试及中断预留），此前72次单独列示。6份无有效最终答案的回复按规则计错保留，没有手工补答案。见 [完成说明](runs/campaign_1000/完成说明.txt)、[开发集报告](runs/campaign_1000/reports/development_report.json) 和 [冻结协议](runs/campaign_1000/reports/frozen_protocol.json)。以上是开发集结果，正式测试集未运行。

2026-11-10：按用户确认接收六份成员复核版本，不再安排新一轮人工检查。当前入口为 [v0.3 数据与使用说明](data/benchmark_web_v0.3/使用说明.txt)、[1800题 JSONL](data/benchmark_web_v0.3/questions.jsonl)、[本地浏览页](data/benchmark_web_v0.3/完整题库浏览.html) 和 [运行评测流程.ps1](运行评测流程.ps1)。

本版为1500原题＋300变式，仍含363条历史网页题＋1137条网页采集题。原题每年级500道，模块及600基础/600中等/300困难配额全部满足；变式每年级100道、实际暂定难度120/121/59。开发150、测试1650、调试100，全部变式和母题族在测试侧。

程序从旧爬虫缓存补入87题，替换缺失、错科及复核标签变化产生的配额超额题，没有新增网络爬取或伪造题源。3道变式由助手针对函数任务偏移/近重复分集问题实际重写并程序验算，单独记录，不宣称这些新版本已再次由成员复核。87道缓存题为程序源材料检查，不冒称成员逐题检查。

模型输入保留文字题干和四选项，462题附必要原图，不使用整题审核截图；浏览页已在1280/390两种宽度逐题通过渲染检查。数据、来源、配额、分集、图片及离线双次构建验收通过；300变式的236份可执行规格检查通过，64份沿用成员复核，没有新增人工待办。

评测程序已实现配置、OpenAI兼容请求、多图输入、原始响应、答案提取、失败分类、重试续跑、请求次数限制、分层指标和母题变式指标。2026-11-10完成84项相关测试及开发侧100/150题模拟验证，模拟结果明确标记synthetic，不作为模型能力成绩。

2026-11-11：按用户要求使用六家国产官方接口：DeepSeek-V4.1-Flash、Qwen3.8-Flash、GLM-5.3-Flash、Kimi K3、MiniMax M3.1 Flash、豆包Seed 2.1 Lite。已完成首轮60次请求（每家10次，含重试），见 [预检报告](runs/domestic_six_pilot_report.txt) 和 [机器可读结果](runs/domestic_six_pilot_report.json)。DeepSeek/GLM各10题、千问/豆包各9题、Kimi3题返回可解析答案；MiniMax因余额不足未成功。Kimi另遇账号3 RPM限流，千问/豆包各拒绝同一小图。结果仅用于接口预检，不是正式模型成绩；未调用正式测试集。

已补写图片最短边加白边处理，并准备Kimi每次至少间隔21秒的后续草稿。77项评测相关测试通过；对1800题的1283处必要图片引用完成离线处理检查，742处需补白，源文件摘要不变。见 [后续配置](config/evaluation_domestic_six_followup.json)，上限为0，未API复测。首轮代码及无密钥配置单独保存在`runs/domestic_six_implementation/`，不改已完成运行的配置。使用见 [运行说明](国产六模型运行说明.txt)。GLM/Kimi/MiniMax强制思考，Kimi/MiniMax温度固定1，参数差异如实记录。

同日新增12次定向复测：千问3次、豆包3次、Kimi5次、MiniMax1次，全部收到接口响应。千问/豆包均接受补白后的问题小图；豆包3题、Kimi5题、MiniMax文字1题均给出可解析答案，Kimi未再出现429，实际最小间隔21.000秒。千问2题有最终答案，另1题输出用尽2048 token后被截断。见 [第二轮复测报告](runs/domestic_four_retest_report.txt)。累计72次请求额度已用完；后续千问草稿上限提高至8192、调用上限仍为0，尚未验证。MiniMax图片未在第二轮测试，正式测试集未运行。

以下保留此前过程记录与旧版说明。

# 历史版本：网页题源重建 v0.2 草稿

2026-10-22：1137道网站爬取题与363条历史网页题保持不变，已完成第二轮300道变式重生成及全部300道助手逐题自查，修正1道条件矛盾并完善另外14道表述。母题来源标签及变式暂定难度均为120/120/60，各年级100道，全部待用户独立复核。请打开[当前1800题浏览页](可视化/完整题库浏览.html)、[变式自查报告](data/benchmark_web_v0.2/变式自查报告.md)、[阶段实施报告](data/benchmark_web_v0.2/阶段实施报告.md)和[人工复核对照](data/benchmark_web_v0.2/人工复核对照.html)。统一程序入口为运行网页题库流程.ps1；只交付普通文件。尚有来源语义疑点和人工复核，不能视为正式冻结题库。本次没有运行模型评测。

以下为旧版历史记录，旧ZIP引用和旧分布不代表本轮交付。

---

# EduMathBench

研究中文初中数学四选一题的模型解题表现。1500道公开题与300道变式初版已汇总，开发集/测试集暂定划分完成，下一阶段为本地评测程序。

2026-10-14已完成1500道公开题初版，七、八、九年级各500道，年级模块配额全部满足。暂定难度为基础600、中等600、困难300。全库1298道纯文字、202道含图；困难题包括98道纯文字和202道含图，图形题只是可选范围的一部分。通用交付见data/exports/EduMathBench_public_draft_v0.1.zip；本轮记录见[data/reports/completion_report.md](data/reports/completion_report.md)。

难度标签为题面任务判断或来源专题证据支持的暂定标签，没有教师或学生正确率、用时校准。各年级困难题分别26、91、183道，年级内部未达到约200基础/200中等/100困难的设计分布；不抬高简单题标签凑数。数学正确性、教材适配和近重复题族仍未定稿。

本地可视化：双击[题库浏览.html](可视化/题库浏览.html)，用Edge或Chrome打开。页面内置1500题、图表与公式字体，离线可筛选、翻页及查看来源答案；来源网站链接需要联网。此页面为当前题库快照，后续题库更新需重新导出。

2026-10-14格式修复：全库7500个题面字段、7703段公式及9张表格已检查。页面与通用导出使用规范化输入，来源原文保留于source_input及原主库。评测请用data/exports的规范化question/options/image_assets，直接使用原主库会重新遇到来源公式命令兼容问题。修复范围见[data/reports/format_check.md](data/reports/format_check.md)。

随后收到两份实际浏览器报告：首次发现的5处正文排版命令残留已修复，第二份报告与当前question-format-v1.1摘要一致，1500题全覆盖、问题记录0。Edge的1409px视口下，7703公式节点、219图引用、9表152格完整，未报残留命令、缺图或溢出；5题补验限制已解除。详情见[data/reports/luna_render_audit/browser_report_current_result.md](data/reports/luna_render_audit/browser_report_current_result.md)。

全部300道变式草稿已生成，各年级100道，全部纯文字。实际暂定难度123基础/122中等/55困难。来源关联、结构、显式计算和独立题面初核通过，仍待正式复核与冻结。双击[可视化/变式题库浏览.html](可视化/变式题库浏览.html)离线浏览全部题对；[data/exports/EduMathBench_variants_300_draft.zip](data/exports/EduMathBench_variants_300_draft.zip)包含JSONL、CSV、母题来源及复核记录。新页公式/模拟控制检查完成，真实浏览器实测尚未补验。1500公开题＋300变式的1800题数量门槛齐；题库汇总与暂定划分见下，尚未运行模型评测。进度见[data/variants/batches/b003/completion_report.md](data/variants/batches/b003/completion_report.md)。

2026-10-14：1800题通用草稿已交付。开发集150题（全为公开题）、测试集1650题（1350公开＋300变式），每年级分别50/550题；调试100题全为开发集公开题。按用户要求采用split-policy-v0.2，全部变式和300道母题及关联题族均在测试集。已识别题族同侧，来源/原题内容保留，Luna独立结构审计通过。双击[完整题库浏览.html](可视化/完整题库浏览.html)可离线筛选全部1800题，支持有解析/无解析/异常解析片段筛选和逐题状态展示；[1800题数据包](data/exports/EduMathBench_1800_draft_v0.1.zip)包含通用JSONL/CSV、分集、无答案模型输入、独立答案表、全部图片及摘要。详见[data/benchmark_draft/使用说明.md](data/benchmark_draft/使用说明.md)。新页公式引擎和模拟控制检查通过，41道原解析异常片段明确标记并原样显示；未取得新页真实浏览器报告，题库仍未正式冻结，自动筛查不保证排除全部语义近重复。下一阶段见[评测程序计划](docs/evaluation_stage_plan.md)。

- [收集规范](COLLECTION_SPEC.md)：字段、来源、配额和状态规则。
- [子智能体及模型分工](docs/agent_assignments.md)：简单任务优先Luna，复杂验证用Sol，按阶段启动。
- [当前进度](data/reports/progress.md)：只统计来源可追溯、结构通过且去重后的初版题。
- `data/batches/`：原始批次，代理分别保存，不相互覆盖。
- `data/registry/sources.jsonl`：来源总表；`data/public_draft/`：公开题初版。
- `data/registry/question_sources.csv`：中文逐题来源索引；初版题目表也直接包含来源名称、链接、答案位置和原材料路径。
- `data/exports/`：通用JSONL、CSV、逐题来源索引、原题输入图片、字段说明、收集报告与文件摘要；ZIP可直接解压使用。
- `data/candidates/needs_review.jsonl`：异常候选；`data/reports/`：重复、问题、配额和来源分布。
- `data/resolutions/`：已知问题的处置与证据；`data/candidates/rejected.jsonl`：已退回题，保留稳定题号和来源答案。
- `data/bulk_probe/raw/`：锁定版本与摘要校验的公开数据包；`data/bulk_work/`：分类规则、审核记录和候选清单。
- `data/bulk_prepared/reserve.jsonl`、`data/mathbench_prepared/reserve.jsonl`、`data/candidates/quota_reserve.jsonl`：超出当前模块配额的候补题，保留题目及来源。
- `templates/`：统一录入CSV模板（由检查脚本生成）。

重新汇总：`python scripts/check_collection.py`。检查回归：`python -m unittest discover -s tests`。仅使用Python标准库，不调用模型或付费接口。批次原件保持不变，重复运行会重新生成派生表。

通用导出：`python scripts/export_collection.py`。要求1500题及全部年级模块配额匹配，再逐题核对JSONL/CSV往返转换。题干、公式、选项顺序和来源答案保持一致；导出格式详见`data/exports/FORMAT.md`。原始资料仍保存在项目内，不放入轻量ZIP。

`auto_checked`仅表示来源字段、四选项和答案字母等结构检查通过，数学正确性未集中复核。近重复检查当前能识别选项重排；数值轻微改变和文字改写仍需后续聚类检查，不能宣称已排除全部近重复。

收集方式已改为整包/整份资料提取，然后按主要知识、结构和配额筛选。CMM-Math、TAL-SCQ5K与MathBench属于可追溯的公开数据集来源，未逐题核实原试卷；MathBench概念题另保留来源题类。复核发现的错误题保留源答案并暂停使用，明确分类错误只更正标签。初版题量以进度表计入数为准，下载量与候补量不计为完成。

教材版本尚未指定，以暂定知识归属收集首批；年级与章节迁移不明确的记录留待处理。正式发布范围需依据每个来源的实际复用条件确认。

暂定难度及依据已补齐，待定0，每题可在本地页面展开判断依据。最新分布见[data/reports/difficulty_review.md](data/reports/difficulty_review.md)，历史整理快照另存，不冒充当前数量。
# 图像题补采

2026-10-14文字题与图像题已按同年级、同模块替换并合入1500题主库，主库通用ZIP包含218个独立原题输入图片文件（219次引用），本地题库浏览页内置全部图片。data/public_image_draft/、可视化/图像题浏览.html及EduMathBench_image_draft_v0.1.zip只保留首批4道图像题的历史示例，不另加到1500题统计。输入规则见config/input_policy.json。
