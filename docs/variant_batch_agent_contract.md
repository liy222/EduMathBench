# B002生成与复核约定

工作目录D:/EduMathBench。用户要求继续变式阶段，尽量纯文字，简单整理Luna、数学生成复杂岗位，所有草稿需来源可回查。公开题库和首批30、300母题ID固定；仅新批输出。

## 生成

- 读data/variants/batches/b002/parents_g{grade}.jsonl，按已冻结行序一母题一变式，每级20题。输出data/variants/batches/b002/g{grade}.jsonl，ID依次EMB-V-B002-G{grade}-001至020。生成者只写自己的文件和辅助脚本/说明，不改其他年级或母题列表。
- 实质改变数值、关系或条件，保留主要知识和推理。单改名字、选项顺序或仅换说法不算。每题新答案从新条件独立推导，不照搬源答案。
- 仅纯文字变式，input_modality=text、image_assets=[]。几何题文字必须定义所有点、边、角、关系，不能留“如图”等指向未提供图的词。母题有image_assets但文字充分时可以改成纯文字；不能删图导致条件不足。
- 四选项唯一正确且互不等价（注意比例系数不同但同解集也可能等价）。定义域、整根、正负、端点、退化、单位逐题检查。源题有问题必须报告，不能把错误解析直接改数字复用。
- 实际任务难度目标仍每级8基础8中等4困难；若变式变容易，要重新构造或报告同格换题，不强抬难度。
- 字段：id,parent_id,family_id(沿用母题),source_type=variant,question,options={A,B,C,D},answer,grade,module,knowledge_point,difficulty,input_modality,image_assets,solution,change_description,generation_metadata={agent:实际任务名,model:inherited_parent_model,generated_at:带+08:00},difficulty_annotation={reason,empirical:false},risk_flags=[variant_draft,math_review_pending],status=variant_draft_pending_review,verification_spec。
- 来源从母题source_*保存于source对象或保留平铺字段；说明变式是生成草稿，源链接用于回查母题。
- verification_spec使用scripts/verify_pilot_variants.py的check_spec；优先derived_value算式应从题目新条件得到目标数/特征tuple，不能只是抄正确选项。option_exprs编码四个选项，derivation说明表达式对应题面。
- AST允许数值+-*/**//%、sqrt/abs/min/max/sum、比较/布尔、tuple/list；不允许任意eval、模块、属性、推导式或lambda。有限整数搜索kind=finite_integer_search含variable,lower,upper,predicate_expr,aggregate(sum/count/min/max),option_exprs,derivation，必须说明有限范围完整。
- 还支持option_sign、equality_chain_count、statement_count、affine_inequality_implication、statistical_statement_count、increasing_integer_optimization、ray_parameter_range，读代码确认字段。需要新类型先通知root。区间/符号函数选项可用数值特征tuple，但要说明编码含义及推导，不用任意标签数字冒充数学验证。
- Python公式字符串采用raw字面量，防止\f、\t、\b等误转义。C:/python/python.exe只有标准库；SymPy未安装，不安装依赖、不调用收费API。
- 先逐条落盘再自检20题，写selfcheck_g{grade}.json和generation_notes_g{grade}.md。报告问题与任何修正。最终仍保留草稿状态，不声称正式数学批准。

## 交叉复核（另接通知后执行）

- 先从另一年级题干和四选项独立求解，之后比对答案、solution及验证表达式。不要把生成者的推导/option表达式当已知条件。
- 每题审实质修改、母题主要推理是否保留、定义域与边界、选项互不等价、候选难度理由。发现问题先报告root/生成者，不改别人JSONL；修正后重审最终文本。
- 写data/variants/batches/b002/review_g{被复核年级}.json：顶层reviewer_agent,reviewer_model,method,records。每条{id,independently_derived_answer,independent_derivation,boundary_and_uniqueness_checks,status:'pass'或'issue',issues:[],content_sha256}。
- content_sha256采用最终四字段question/options/answer/solution：hashlib.sha256(json.dumps({k:q[k] for k in ['question','options','answer','solution']},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()。仅给已实际复核的最终版本填pass，问题未解决保持issue。
- 完成后报告总数和问题数，不将本批审查扩大声称为全1500题母库或未来300变式已批准。
