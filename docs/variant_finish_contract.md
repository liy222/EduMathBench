# 最后210道变式（B003）执行约定

用户要求“把所有变式题先完成”。当前90道已完成独立初核；本批每年级70道，完成后合计300。优先纯文字，不将教师校准、正式评测或全屏宽浏览器检查作为先生成的阻塞条件，但不将未做检查标记为通过。

## 输入与输出

读取data/variants/batches/b003/parents_g{grade}.jsonl完整70条，只读有用字段避免整条raw/provenance的大量输出。按该冻结顺序一母题一变式，ID EMB-V-B003-G{grade}-001..070。只写data/variants/batches/b003/g{grade}.jsonl及自身辅助脚本/说明/自检，分段及时落盘，每完成10至20题报root进度；不能只生成少数后结束。

source_type=variant、parent_id/family_id沿用母题、grade/module保留知识归属。尽量保留现有28基础28中等14困难覆盖，但标签按实际任务暂定，不能将简化为一步的题强标困难。换父题或难度冲突要先报root，不擅改冻结清单。90个已有变式和1500公开题原件不改。

## 数学生成

- 必须改变数值、关系或条件，并保留主要知识与推理。不能只换姓名、句式或选项顺序；不能从完全不同知识点另写一道题配同parent_id。
- 生成新条件之前核母题结构和关键数学关系，有错误/条件不足要报告，避免复制源解析错误。新答案独立推导，每题简短完整solution，尤其说明定义域、非零、端点、退化、整数/实数全部根、单位和解的存在性。
- 四选项只有一个正确且互不等价。集合/区间答案要写完整，不漏根；方程选项防止整体倍乘但同解集。科学记数法要符合形式条件，不能仅比数字等值。
- 本批目标纯文字，input_modality=text,image_assets=[]。母题附图但文字完整时可直接纯文字变式；若必要关系在图里，先用view_image看本地image_assets原图，再把所有必需点位、线/角/边/运动规则写完整，不能仅删除图。若难以合理转为纯文字，及时报root请求同格纯文字母题替换；图片不是最低配额，也不可编造原图条件。
- 字段与verification_spec详见docs/variant_batch_agent_contract.md（B002编号/数量仅适用旧批，本批以此70规则为准）。必需字段id,parent_id,family_id,source_type,question,options{A,B,C,D},answer,grade,module,knowledge_point,difficulty,input_modality,image_assets,solution,change_description,generation_metadata{agent:实际岗位名,model:inherited_parent_model除非确知,generated_at带+08:00},difficulty_annotation{reason,empirical:false},risk_flags[variant_draft,math_review_pending],status=variant_draft_pending_review,verification_spec。
- 母题source_id/title/url/ref保存到source对象，不能冒充公开原题。说明修改的实际数值/关系及所保留知识，补充的歧义消除条件要记录。
- verification_spec从新条件表达目标值/特征，不直接抄正确选项；safe AST和支持kind见scripts/verify_pilot_variants.py。数值允许+-*/**//%、sqrt/abs/min/max/sum、比较/布尔、tuple/list；有限整数枚举必须说明完整界限。不装SymPy/依赖，不用付费API。公式Python字面量用raw字符串。
- 允许用符号表达式的系数元组、根集合、区间端点等有数学含义的特征检验，但不得用任意编号/标签代替验证；新类型先报root。对于机器不易验证的题，先给完整推导并提出结构化验证方案，不停下其余题。
- 保存selfcheck_g{grade}.json、generation_notes_g{grade}.md，记录发现和修正。生成自检不是独立复核；风险状态不移除，正式批准仍未完成。

## 后续交叉复核

root另行指定后，只读另一年级70题题面和选项独立推导，再核对候选答案与推导；审数学条件、实际改动、主要推理和难度依据。写review_g{被审年级}.json，顶层reviewer_agent/reviewer_model/method/records。每条id、independently_derived_answer、independent_derivation、boundary_and_uniqueness_checks、status(pass/issue)、issues、content_sha256。

最终题面绑定hashlib.sha256(json.dumps({k:q[k] for k in ['question','options','answer','solution']},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()。发现问题先回报，不改别人文件，修正后复核最终版本；只给确实复核的版本pass。
