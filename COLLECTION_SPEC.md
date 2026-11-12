# EduMathBench 公开题收集规范 v0.1

依据：用户提供的《EduMathBench_实施计划.md》2026-10-08 修订版。启动日期：2026-10-09（Asia/Shanghai）。

本阶段只做来源检索、公开题提取、格式清洗、去重和配额统计。公开题目标1500，变式300留到下一阶段。不得生成题目冒充公开题，不接待测模型，不提前建设评测系统。

## 配额与暂定教材口径

以人教版初中数学常见知识进阶为暂定口径，按解题主要知识定年级；未指定教材版本，涉及章节迁移的题标记grade_pending，不宣称完成教材版本校准。实际大量采集前确认纯文本几何供给。初始配额沿用计划，不擅自改数。

| 年级 | 数与式 | 方程与不等式 | 函数 | 几何 | 统计与概率 |
|---|---:|---:|---:|---:|---:|
| 7 | 200 | 150 | 0 | 100 | 50 |
| 8 | 100 | 150 | 100 | 100 | 50 |
| 9 | 0 | 50 | 200 | 150 | 100 |

难度暂定基础/中等/困难/pending，目标600/600/300；未知不计难度完成量。

## 采集交付

每位采集代理只写自己的批次目录 `data/batches/g7_001`、`g8_001`、`g9_001`。每批目标约20题，尽可能来自至少两份不同材料；本轮先验证实际题源可用性，再扩到50题。目录包含 questions.jsonl、sources.jsonl、source_notes.md、raw/ 原始资料。

题号格式 EMB-P-G7-000001（其他年级同理），每位本轮保留000001—000200号段，不重排已分配题号。source_id 格式 SRC-G7-001。batch_id使用目录名。

每道记录字段：id, question, option_a, option_b, option_c, option_d, answer, grade（7/8/9或pending）, source_exam_grade, module（数与式/方程与不等式/函数/几何/统计与概率或pending）, knowledge_point, difficulty（基础/中等/困难/pending）, source_id, source_ref, source_type（public）, solution（可空）, risk_flags（数组）, status（collected或needs_review）, batch_id。

來源记录字段：source_id, title, url, year, region, source_exam_grade, answer_location, main_modules（数组）, accessed_at（带+08:00时区）, text_extractable, access_status, reuse_status（默认unknown，除非核实）, raw_path, notes。

必须实际打开题目和参考答案，不以搜索摘要填题。答案按来源录入，不自行求解补答案。来源对应位置要能回查具体题号/页码/锚点，原资料保存本地HTML/文本/PDF，至少保留取得内容和URL。若下载受阻，仅能保存摘录，明确注明为摘录，不称完整原件。每个题目选项必须四个完整且公式不缺失；有缺图、公式抽取丢失、答案不明确放needs_review，不计入可用数。

完全重复以保守文本归一化比较，保留主记录和其他来源，不静默丢弃；近重复仅标记。自动通过只设置auto_checked，不设置approved。本阶段不重新解题、不声称数学正确性已确认。

禁止付费购买、登录绕过、无来源生成、将下载题量算作完成数。遇到不可访问来源登记原因并寻找替代来源。

`reuse_unknown`、`reuse_rights_unknown`、`math_not_reviewed`、`curriculum_version_unconfirmed`和`secondary_source`属于来源/流程提示，本身不阻止结构通过；仍保留在记录中。具体年级待定、缺图、公式丢失、来源答案冲突等则阻止计入可用初版。教材版本未明确不是所有题统一退回的理由，只有年级归属实际不确定的题留待处理。

## 每题显示来源

合并生成的题目CSV/JSONL和待处理池直接带来源名称、链接、资料年份/地区、答案位置、原材料路径、获取时间、访问/复用状态及来源说明。`source_ref`继续保留本题的具体页码和题号；`source_material_year`指登记材料的年份，不自动当作汇编内原试卷年份。原题年份若仅在题干或说明中出现，保留原文，不推断缺失年份。来源说明中的二手汇编、公开预览和仅摘录等信息一并保留。

`data/registry/question_sources.csv`为中文列名的逐题来源索引，包含可用初版和待处理题。原始批次通过source_id和source_ref关联来源表；后续重新汇总会自动补全可见来源信息。

## 已知问题处置

收集阶段发现的可确认问题及时分诊，不等待后期全库复核。近重复候选可保留并设置共同family_id，记录处置后使用near_duplicate_grouped提示，不再作为未解决风险；后续题族划分必须同侧。确认来源答案冲突且无法取得可靠更正的题退回，保留来源答案、证据与稳定题号，不计初版配额。处置写入data/resolutions附表；needs_review只保存未解决项，rejected单独保存已退回项。本次问题处置不自动设approved，也不代表完成全量数学复核。

## 批量扩展与通用交付

原有小批次题号继续保留。整包记录使用EMB-P-BULK-加发布者原ID；网页增补使用EMB-P-WEB-加稳定批次/资源号/原题号。批次目录独立写入，任何标签或可确认源错误的更正均保存处置依据，源题干与源答案不得为凑配额改写。

公开题数量配额完成后统一导出UTF-8 JSONL及CSV。JSONL的options固定为A/B/C/D四键，CSV将其展开为option_a至option_d；answer保持来源字母。年级、模块、难度、状态、来源定位及附加来源一并导出。数学表达式保留Unicode和LaTeX，不通过删除数学符号统一格式。转换后按题号逐题核对题干、四选项、答案及来源，附字段说明、难度未知项清单和SHA-256摘要。通用导出不改变auto_checked状态，不代表正式冻结题库。
