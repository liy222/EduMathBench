"""Package ordinary files and truthful workload evidence; no archives created."""
import csv,hashlib,importlib.metadata,json,shutil,sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
import rebuild_web_benchmark as r

def main():
    validation=json.loads((r.OUT/'reports/final_validation.json').read_text(encoding='utf-8'));assert validation['passed']
    qs=r.read(r.OUT/'questions.jsonl');stat=json.loads((r.OUT/'statistics.json').read_text(encoding='utf-8'));progress=r.status()
    regeneration=json.loads((r.OUT/'variants/regeneration_v2/checks.json').read_text(encoding='utf-8'))
    parent_selection=json.loads((r.OUT/'variants/regeneration_v2/selection.json').read_text(encoding='utf-8'))
    active=json.loads((r.OUT/'variants/active_generation.json').read_text(encoding='utf-8'))
    self_review=json.loads((r.OUT/'review/assistant_self_check_v2/summary.json').read_text(encoding='utf-8'))
    assert self_review['count']==300 and validation['variant_assistant_self_check_completed']==300
    assert active['revision']=='v2_regeneration' and regeneration['passed'] and validation['variant_difficulty_goal_met']
    math_passed=validation['variant_math_specs_passed'];math_pending=300-math_passed
    selection=json.loads((r.OUT/'reports/selection.json').read_text(encoding='utf-8'))
    qualification=json.loads((r.OUT/'reports/site_qualification.json').read_text(encoding='utf-8'))
    events={name:r.read(r.OUT/'reports'/name) for name in ['crawl_events.jsonl','asset_events.jsonl','probe_events.jsonl']}
    http_counts={name:sum('requested_at' in e for e in entries) for name,entries in events.items()}
    browser=json.loads((r.OUT/'browser_capture/manifest.json').read_text(encoding='utf-8'))
    retained=[q for q in qs if q['acquisition_origin']=='retained_legacy_web'];domains=Counter(urlparse(q['source']['url']).netloc for q in retained)
    code=['rebuild_web_benchmark.py','answer_ocr.py','web_benchmark_delivery.py','web_benchmark_viewer.py','verify_web_variant_math.py','verify_web_delivery.py','web_review_materials.py','edumath_web.py','finalize_web_rebuild.py','variant_authoring.py',
          'select_variant_parents_v2.py','check_variant_regeneration.py','record_variant_self_review.py','author_regeneration_common.py','author_regeneration_g7.py','author_regeneration_g8.py','author_regeneration_g9.py',
          'site_crawler/edumath_crawler.py','site_crawler/capture_logged_in.mjs','site_crawler/configure_second_module.mjs','site_crawler/discover_visible_tree.mjs','site_crawler/audit_web_render.mjs','site_crawler/audit_web_review.mjs','site_crawler/audit_rebuild_formulas.mjs']
    archive=r.OUT/'reproducibility/source';archive.mkdir(parents=True,exist_ok=True)
    code_sizes={}
    for name in code+['question_format.py','verify_pilot_variants.py','author_web_pilot.py','author_web_g7_remaining.py','author_web_g8_remaining.py','author_web_g9_remaining.py']:
        source=r.ROOT/'scripts'/name;target=archive/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        code_sizes[name]={'sha256':r.sha(source),'physical_lines':len(source.read_text(encoding='utf-8').splitlines())}
    conf=r.OUT/'reproducibility/config';conf.mkdir(exist_ok=True)
    for source in [r.ROOT/'config/quotas.json',r.ROOT/'config/variant_quotas.json',r.ROOT/'scripts/site_crawler/tasks.json',r.ROOT/'scripts/site_crawler/second_module_tasks.json',r.ROOT/'scripts/site_crawler/package.json']:
        if source.is_file():shutil.copyfile(source,conf/source.name)
    # Copy the original retained evidence, preserving original paths in an index.
    material_index=[]
    for original in sorted({q['source']['raw_path'] for q in retained}):
        source=r.ROOT/original;digest=r.sha(source);target=r.OUT/'baseline/retained_materials'/(digest[:24]+source.suffix)
        target.parent.mkdir(exist_ok=True)
        if not target.exists():shutil.copyfile(source,target)
        material_index.append({'original_path':original,'local_copy':target.relative_to(r.OUT).as_posix(),'sha256':digest})
    r.dump(r.OUT/'baseline/retained_material_index.json',material_index)
    sys.path.insert(0,str(r.ROOT/'.runtime_deps'))
    versions={name:importlib.metadata.version(name) for name in ['lxml','rapidocr-onnxruntime','sympy','numpy','onnxruntime','opencv-python','Pillow','Shapely']}
    (r.OUT/'reproducibility/requirements.lock.txt').write_text('\n'.join(k+'=='+v for k,v in versions.items())+'\n',encoding='utf-8')
    work={'generated_at':r.site.stamp(),'candidate_unique':progress['new_candidate_count'],'candidate_ready_before_dedup':progress['new_eligible_before_dedup'],'candidate_deferred_or_assets_pending':progress['new_deferred_or_assets_pending'],
          'http_request_log_entries':http_counts,'logged_http_total':sum(http_counts.values()),'browser_saved_manifest_entries':len(browser['items']),
          'browser_unique_candidates':sum(q['candidate_unique'] for q in qualification if q['site']!='tiku'),'dedup_events':selection['duplicate_records'],
          'selected_new':1137,'retained':363,'assistant_variants':300,'active_variant_revision':active['revision'],'variant_regeneration_count':300,'variant_program_math_checks_passed':math_passed,'variant_manual_math_pending':math_pending,'assistant_self_reviewed_variants':300,'self_review_substantive_fixes':self_review['substantive_condition_errors_corrected'],'self_review_clarifications':self_review['clarifications'],'source_distribution':stat['new_web_by_site'],'retained_domains':dict(domains),
          'final_ocr_answers':stat['new_web_ocr_answers'],'trial_accepted_ocr':sum(bool(q.get('answer_ocr',{}).get('accepted')) for q in r.read(r.OUT/'candidates/questions.jsonl')),
          'scripts':code_sizes,'runtime_versions':versions,'notes':['请求计数仅统计保存的请求日志，不包括浏览器的每个资源请求；早期一次图片下载被中断，部分已验证缓存未留下该轮完整请求日志，不能将此数宣称为绝对网络请求总数。','原网页归档可能包含解析区，但未抽取解析字段、未单独下载解析图片，最终solution为空。','知识点ID来自实际网页控件，不通过大模型逐题分类；跨知识点综合题的年级适配仍有风险。','主覆盖采集按知识点叶节点和难度取首页；跨页逻辑另有真实三页验收，未将本轮所有请求描述为连续翻页。']}
    r.dump(r.OUT/'reports/workload_evidence.json',work)
    source_lines='\n'.join('| '+domain+' | '+str(n)+' |' for domain,n in domains.items())
    site_lines='\n'.join('| '+{'tiku':'牛题库','jyeoo':'菁优网','21cnjy':'二一组卷网','chujuan':'出卷网'}[q['site']]+' | '+str(q['candidate_unique'])+' | '+str(q['auto_checked_unique'])+' | '+('进入正式采集' if q['qualified'] else '每日答案查看上限，暂停')+' |' for q in qualification)
    report=f'''# EduMathBench 网页题源替换与重建阶段记录

本次完成的是可复现的1800条题库草稿：1137道本次程序爬取、363条历史网页题沿用、300道当前助手逐题生成的变式。原题采集和处理程序不调用大模型。尚未完成人工来源抽查、变式独立数学复核和正式模型评测，不能把程序验收等同于数学正确性验收。

## 1. 固定旧版与替换范围

程序按旧题号前缀分离公开数据集记录，固定363条保留与1137条替换清单，保存旧300道变式停用清单和旧库SHA-256。旧题库文件摘要保持不变，新版单独写入`data/benchmark_web_v0.2/`。保留题号、来源和历史分类依据，解析统一清空并标记未采集；这些363条不计作新爬成果。

采用这一安排是为了在维持原来规模及配额的同时，能清楚区分历史采集、当轮爬虫和助手生成三种工作。旧开发侧31条、调试侧20条进入保护清单，避免重分集造成泄漏。

## 2. 四站试采与访问条件验收

使用Python的HTTP客户端和lxml解析公开列表、详情；动态或登录网站使用Playwright启动安装的Edge，指定独立用户目录。用户完成正常登录后，程序复用该会话进行列表、详情及分页访问。登录目录位于项目的本机私有目录，未复制进本交付，也没有读取用户密码。会员限制、验证码及失效会话需要正常处理，不由程序绕过。

四站实际结果如下。结构可用数量不表示数学复核通过。

| 站点 | 独立题号候选 | 当前结构与资源可用 | 处置 |
|---|---:|---:|---|
{site_lines}

二一与出卷网在已登录会话中出现“今日查看试题解析数量已达上限”等提示，答案与受限区相连，故暂停，不纳入正式1137道。菁优网完成两个知识模块试采，牛题库覆盖五个模块。牛题库没有在当前筛选页提供独立来源类型筛选，配置明确记为不支持，没有伪造期末、地区或年份筛选。其余站点记录实际展示的知识点、题型、难度和来源参数。

本轮各站都测试了必要图片保存。图片答案使用RapidOCR普通OCR（本地PP-OCR识别权重），而非大模型：裁边、白底、放大和两套二值/灰度预处理，两个结果须一致为单个A—D并满足0.90置信度门槛；失败自动分流。试采共有{work['trial_accepted_ocr']}条接受结果。最终新爬题全部有文字答案，OCR答案实际入库0条，OCR试验成果与正式题库分别统计。

## 3. 知识点覆盖采集与原材料归档

程序从网页知识点控件读取实际ID，牛题库建立422个叶节点的年级模块映射，33个节点不能可靠归档或不在范围内而跳过。新题年级与模块按这份固定配置归档，网站难度标签按固定表映射；不让模型逐题猜测缺失标签。它是暂定课程映射，综合题仍可能涉及更高年级知识。

覆盖采集按尚缺的年级模块及难度创建任务，主采样优先访问不同叶节点首页，避免大量同类题挤占配额。牛题库独立分页验收另保存了真实三页30题记录；登录站点程序测试了真实下一页链接或页面控件。首轮候选预算约2000，后按剩余缺口追加，最终保留{work['candidate_unique']}个唯一题号候选。达到配额后停止扩量。

请求地址、时间、状态、网页及图片SHA-256写入文件与SQLite，任务有完成、失败状态，便于续跑。累计保存HTTP请求日志{work['logged_http_total']}条，浏览器快照清单{work['browser_saved_manifest_entries']}条（有重复查询，去重后100题）。这些是可审计日志数量，**不是全部底层网络请求总数**：不包含浏览器每个资源请求，且早期一次图片下载中断后，部分已验证缓存未留下那轮完整请求日志。各原始材料及后续摘要校验仍保留。

## 4. 程序清洗、图片处理、去重与配额选取

流水线为“原始HTML/图片→站点规则解析→统一字段→资源检查→去重→配额选择”。中文实体、Unicode负号、上下标、MathML及已支持的MathJye结构由规则转换。图片URL中显式携带MathML时直接解析该表达式；普通公式图片不以大模型抄写，原样保留在题干或选项位置。答案和解析图片不进入模型输入资产。

无完整四选项、无来源答案、未知难度、公式异常或缺必要图的候选进入异常池；部分候选只因超额后没有继续下载资源而暂挂，不能全部称为内容错误。当前结构及资源可用{work['candidate_ready_before_dedup']}条，暂挂{work['candidate_deferred_or_assets_pending']}条，原因可多标签重叠。

去重同时比较网站题号、规范题干、忽略排列的选项内容及已下载图片SHA，而非只比较图片URL。选项重排时比较答案所指内容，冲突隔离。此次配额选取记录{work['dedup_events']}条重复处置。历史363条中有两组完全重复，按既定保留范围沿用，合并题族且同侧分集；因此1500为记录数，**不宣称1500条均为相互独立题面**。没有新爬题的精确重复留在最终结果。

采用网络流同时满足年级模块缺口与难度总额，防止逐类贪心选题耗尽另一个类别。最终1137道新爬题：牛题库1105道、菁优网32道；基础416、中等449、困难272。加上沿用题后，1500道原题每年级500道，基础600、中等600、困难300，所有年级模块计数满足原定配额。

保留363条的原始域名分布如下，域名是材料保存来源，不代表同域下每题的最终命题机构。

| 原来源域名 | 保留条数 |
|---|---:|
{source_lines}

## 5. 助手逐题生成300道新变式

首轮变式困难题不足，随后按用户要求完成第二轮全部300道重生成。先从既有1500道原题中选定300道不同母题，来源标签严格为基础120、中等120、困难60；不足会停止，不再用其他难度补位。每个年级100道，模块总额不变。八年级部分模块没有来源困难题，比例在全体300道层面控制，不宣称各年级都4∶4∶2。母题来源标签没有改动。

先完成30道试做，再逐年级撰写，第二轮全部改用新题号`EMB-V-WEB2R2-*`。题干、选项、候选答案、母题、具体改动、生成者推导与时间保存在`variants/regeneration_v2/authored/`，活动版本配置为`variants/active_generation.json`。没有自动调用大模型的程序生成器，重新导入只读取已写好的内容。上一轮300道及当时的完整题库、分集、页面和检查记录按摘要备份在`variants/archive_before_regeneration_v2/`，不计入当前1800道。

本轮变式全部为纯文字，{parent_selection['image_parents']}道带图母题先查看保存原图，再把必要关系完整写进新题。暂定难度基础120、中等120、困难60；困难任务保留或重构参数范围、分类讨论、综合几何、整数根、有限概率等推理。这个分布是基于来源母题及作者任务判断的暂定覆盖，**没有用学生正确率或用时验证**，不能仅凭母题标签保证变式实际难度相同。

程序对可支持的{math_passed}道题执行分数运算、有限枚举或SymPy符号检查，包括完整实数解集、分母与定义域、参数范围、二次项退化、有限资源分配及概率停止规则；{math_pending}道概念或复杂几何题标记暂不支持数学自动验算。300道结构、母题绑定和题干重复检查通过，与上轮300道及1500道原题无规范化相同题干。程序不以候选答案字母产生计算结果，但题面到表达式的对应关系仍需独立复核，特别是几何题中的生成者推导。所有300道维持草稿待复核。

随后按用户要求，由当前助手重新逐题阅读300道题干与四选项，重新推导候选答案，检查条件、定义域、边界与选项含义，保存300条单独自查记录。包括上述64道不能自动数学验算的题。发现并修正1道实质条件矛盾：反比例函数k>0却把交点设在第二象限，现改为第三象限；另外14道完善表述。修正后答案字母均未变。该题原自动规格只核对已整理的数值，没有覆盖象限可行性，本次增加直接求交点并核查象限、横距和长度比的程序回归。**这次是同一生成者自查，不是独立复核或用户批准。** 具体见`变式自查报告.md`和`review/assistant_self_check_v2/逐题自查记录.csv`。

## 6. 划分、渲染、复现与后续复核

开发集150道原题，每年级50道；测试集1350道原题与300道变式。变式及母题和已识别近重复题族均在测试侧，调试100道从开发集抽取，历史保护题继续留在对应侧。模型输入只含题号、题干、选项和必要图片，答案表单独输出。CSV增加完整记录列，已逐条验证与JSONL往返一致。

1800题在真实Edge中按1280、390两种宽度各逐题渲染，共3600次；公式解析、缺图、占位符、页面溢出和筛选数量检查通过，另抽看保存截图。首轮发现共享公式图缓存覆盖位置标记、源网页上标将后续中文误包入公式，已修复规则并全量重跑。这些检查保证的是渲染与文件完整性，不保证原站题意、答案或难度正确。

从2142份候选记录关联的保存网页离线重跑解析，重新计算1137道配额选题与分集，结果一致；OCR证据在核对原图摘要后复用，不把离线复用说成再次独立确认OCR准确率。本轮28项采集处理及数学验算回归检查通过，包含空实根集、二次项退化、分式禁值、整数变换汇总、概率停止规则与反比例函数象限可行性等；未运行正式模型评测。

本地提供50道原题来源核对、30道本轮变式验算任务，以及单列的20道OCR试采核对任务。全部结果为空、待实际复核，未编造通过记录。已知源题变量混用、多选项可能同时成立、跨年级综合知识等疑点列入`review/known_source_suspects.json`，优先核查。本轮改编还发现一条源题概率答案与枚举结果疑似冲突，已加入清单，保留来源答案并等待核对；未将源答案直接照抄给其变式。尚未解决这些语义疑点、人工抽查和独立变式验算前，本版只能标为“程序检查完成、待人工复核”的草稿。

## 交付入口

- `完整题库浏览.html`：双击离线打开。
- `人工复核对照.html`：对照统一题面、保存的来源材料及待填结果表。
- `questions.jsonl`、`questions.csv`：1800条通用格式；`public/`和`variants/`分别保留原题与新变式。
- `*_inputs.jsonl`与`*_answer_key.jsonl`：各分集输入和独立答案表。
- `raw/`、`browser_capture/`、`assets/`、`state.sqlite`：真实原材料、资源与断点状态；85个历史原材料文件另复制到`baseline/retained_materials/`并建立索引。
- `reproducibility/`、`reports/`：配置、代码快照、依赖版本、运行记录和检查报告。代码快照用于审计，实际统一运行入口位于项目`scripts/edumath_web.py`。

仅交付普通目录和文件，不新建压缩包。后续先完成来源疑点与人工复核，再决定正式评测。
'''
    (r.OUT/'阶段实施报告.md').write_text(report,encoding='utf-8')
    readme='''# 网页题源重建版 v0.2（草稿）

双击“完整题库浏览.html”离线浏览1800条；双击“人工复核对照.html”打开待复核任务。查看答案无需联网，来源链接需要联网。

原题1500条=363条历史沿用+1137道新爬；新变式300道，均待复核。解析没有采集。开发集150条原题，测试集1650条，调试100条属于开发集。来源、母题、题族、变式改动均在JSONL中，CSV的record_json列可无损还原嵌套字段。

**当前变式**：第二轮重生成300道，新题号EMB-V-WEB2R2-*，暂定难度120/120/60；母题来源难度也按120/120/60选择，每年级100道。活动稿在variants/regeneration_v2/authored/，上轮题库已备份到variants/archive_before_regeneration_v2/。本轮不是重新爬取1500道原题，原题题面、来源、答案及难度保持不变。

**助手自查**：300道已全部逐题重新推导，修正1道条件矛盾、完善另14道表述，包括原先64道不支持自动验算的题。浏览页每道变式新增“本轮助手逐题自查”折叠区；逐题记录和改动清单见“变式自查报告.md”。仍待用户独立复核。

**限制**：源题仍有已知语义疑点；历史保留题有2组精确重复并同族隔离。变式难度未实测校准，全部待独立复核。原题年级按知识点暂定归档，不保证综合题无超纲。请先读“阶段实施报告.md”和“变式重生成记录.md”。程序验收不等于数学复核，不建议直接宣称最终正式评测集已冻结。

## 运行与复现

在项目D:\\EduMathBench中运行普通PowerShell文件“运行网页题库流程.ps1”。默认执行离线verify，不会联网。可用模式：

```powershell
.\\运行网页题库流程.ps1 -Mode replay   # 从已保存网页离线重解析并核对选题
.\\运行网页题库流程.ps1 -Mode verify   # 配额、文件、分集、往返与当前渲染报告校验
.\\运行网页题库流程.ps1 -Mode build    # 重新导入草稿、分集、构建网页并执行渲染和复现检查
.\\运行网页题库流程.ps1 -Mode status   # 候选与暂挂原因
.\\运行网页题库流程.ps1 -Mode collect -Budget 500  # 未达配额时追加；已满足则停止
.\\运行网页题库流程.ps1 -Mode trial    # 四站探测及已有试采材料验收
.\\运行网页题库流程.ps1 -Mode login-capture  # 正常登录专用Edge后程序取样
```

新机器需Python3.12+及reproducibility/requirements.lock.txt中的依赖，Node.js、Playwright1.62.1和安装的Edge。首次建立正常登录会话需要本人操作；验证码、权限与登录失效会暂停对应站点。二一与出卷此次因每日查看上限暂停。不要把专用浏览器的登录目录复制到交付、代码仓库或其他电脑。

统一入口：scripts/edumath_web.py；程序不会调用大模型。variants模式导入已有助手草稿，不自动生成题目。build需要本项目中保留的旧版材料及离线公式资源；reproducibility/source为审计快照，不是独立可执行项目根目录。

最终题库OCR答案0条，20条OCR待核对来自试采池，不混入最终题数。review/人工复核结果表.csv为待填模板。代码、候选、历史停用记录中可能出现答案及旧题；评测只能读取指定的*_inputs.jsonl，使用完整questions.jsonl会带入答案。

不新建压缩包。旧版题库保留不变，历史浏览入口备份在baseline/旧版完整题库浏览.html。
'''
    (r.OUT/'使用说明.md').write_text(readme,encoding='utf-8')
    variants=[q for q in qs if q['source_type']=='variant']
    grade_lines='\n'.join('| '+str(g)+'年级 | '+' | '.join(str(sum(q['grade']==g and q['difficulty']==level for q in variants)) for level in ['基础','中等','困难'])+' | 100 |' for g in (7,8,9))
    module_lines='\n'.join('| '+module+' | '+' | '.join(str(sum(q['grade']==g and q['module']==module for q in variants)) for g in (7,8,9))+' | '+str(sum(q['module']==module for q in variants))+' |' for module in ['数与式','方程与不等式','函数','几何','统计与概率'])
    regeneration_report=f'''# 300道变式第二轮重生成记录

本轮已完成300道不同母题对应的300道新变式，题号前缀为`EMB-V-WEB2R2-`，现已替换本地浏览页中的上一轮变式。1500道原题的题号、题面、选项、答案、难度、来源及必要图片摘要不变；为保证新母题族全在测试侧，开发集与测试集重新计算，历史保护题仍留在开发侧。未重新采集原题，没有运行正式模型评测。

## 先选母题，再逐题改编

按全体300道严格选出基础120、中等120、困难60道母题，每题只计一次，且不占用受保护开发题族。母题不足会报错停止，不再跨难度补位。随后由当前助手逐题改写，先完成30道试做，再完成其余270道。可以重放已写稿件的导入与检查；这些记录程序不是内容自动生成器。

本轮变式暂定难度也为120/120/60，具体分布如下。这些是对来源标签及改编任务的判断，没有学生正确率或用时数据，不能据此宣称难度已实测校准。八年级部分模块没有来源困难题，因此没有要求每个年级各40/40/20。

| 年级 | 基础 | 中等 | 困难 | 合计 |
|---|---:|---:|---:|---:|
{grade_lines}
| 合计 | 120 | 120 | 60 | 300 |

| 模块 | 七年级 | 八年级 | 九年级 | 合计 |
|---|---:|---:|---:|---:|
{module_lines}
| 合计 | 100 | 100 | 100 | 300 |

22道母题有图，查看保存的原图后，将新题所需关系完整写入文字。当前300道变式均不依赖图片。困难任务涵盖参数与定义域、整数解与增根、同高点与判别式、内外心角度分类、双曲线面积关系、概率资源分配及先得分停止规则等。具体改动、生成者推导与数学规格分别保存，不把生成者推导当作独立复核。

## 实际检查结果与边界

- 300道题号、四选项、候选答案、不同母题及题族绑定检查通过；与上一轮300道、1500道原题均无规范化相同题干。近似语义重复仍需复核。
- {math_passed}道可执行数学规格通过，{math_pending}道概念或复杂几何题标记暂不支持自动数学验算。通过规格检查不保证题面到表达式的转换无误。
- 本轮28项相关回归检查通过；包括无实根、退化常数函数、分母禁值、整数变换求和、有限样本枚举、概率停止规则与反比例函数象限可行性等。
- 开发集150道原题，每年级50；测试集1350道原题＋300道变式；调试100道属于开发集。母题、变式及已识别近重复族没有跨侧，历史保护题保留。
- 全库1800题在1280和390像素两种宽度下共渲染3600次，公式解析、图片、占位符、溢出和既有筛选功能通过；另检查复核对照页100项任务。
- 原始网页离线重处理2142条候选、重选1137道新爬题及分集确定性检查通过；CSV与JSONL完整记录往返一致。
- 复读题面后，补全了一道角度题的“O在线段内部”条件及一道数轴题的点与坐标对应。发现的源题概率答案疑点另记入`review/known_source_suspects.json`，没有直接把源答案用于对应变式。

300道随后均已由当前助手逐题重新阅读并推导，包括64道不能程序自动验算的题；修正1道条件矛盾、完善另外14道表述，修正后候选答案字母不变。详见`变式自查报告.md`与逐题CSV。

**300道全部仍为草稿、待独立数学复核。** 助手自查不能替代用户的独立核对，也不能保证实际难度已校准。30道本轮变式的后续复核任务已放入本地对照页及结果表，当前没有任何已完成的人工通过记录。

## 文件及复现

- `variants/questions.jsonl`：当前300道通用格式变式。
- `variants/regeneration_v2/authored/`：当前助手明确撰写的原始草稿，保留逐题推导与检查规格。
- `variants/active_generation.json`：当前活动版本；`variants/parents.jsonl`：300道母题快照。
- `variants/regeneration_v2/checks.json`：逐题程序检查；`reports/final_validation.json`、`reports/browser_render_check.json`：完整题库验收与渲染报告。
- `variants/archive_before_regeneration_v2/`：上一轮完整题库及300道变式、母题、分集和页面备份；`snapshot.json`逐文件记录SHA-256，不计入当前题数。
- `完整题库浏览.html`：双击离线浏览；`人工复核对照.html`：来源及母题对照；`review/人工复核结果表.csv`：待实际填写。

在项目根目录运行`运行网页题库流程.ps1 -Mode build`可重新导入当前稿件、分集并检查页面；`-Mode verify`核对当前文件与验收绑定；`-Mode replay`离线重跑原题处理。不会在这些命令中调用大模型。母题快照SHA-256为`{active['parent_sha256']}`。

本次交付普通目录和文件，没有新建压缩包。
'''
    (r.OUT/'变式重生成记录.md').write_text(regeneration_report,encoding='utf-8')
    changes=json.loads((r.OUT/'review/assistant_self_check_v2/changes.json').read_text(encoding='utf-8'))
    change_lines='\n'.join('| '+c['id']+' | '+('条件错误修正' if c['category']=='substantive_condition_error' else '表述完善')+' | '+c['reason']+' |' for c in changes)
    self_report=f'''# 300道变式助手逐题自查报告

本轮根据用户要求，自查当前全部300道变式，包括原先64道不支持自动数学验算的题；没有将这64道跳过，也没有只重跑原有程序。由同一名生成助手读取题干与四个选项、重新推导答案，并逐题写下新的核对记录。核对范围为条件可行性、数学推导、定义域和边界、选项含义与唯一结论。原题1500道不在本次逐题自查范围内，保持不变。

自查完成300道，修正1道实质条件矛盾，另外14道完善表述。修正后300道自查答案与当前候选答案字母一致，未改答案字母。全部仍保持草稿及待用户独立复核状态；没有填写任何人工通过结果。

## 实质问题与原因

`EMB-V-WEB2R2-G9-264`原写反比例函数y=k/x、k>0，却要求一个交点位于第二象限。因为xy=k>0，曲线只能在第一、第三象限，原条件无解。现把该点改为第三象限，并按其余条件重新核算：横坐标−2和1，k=1、b=1/2，线段长比2∶1，答案A成立。

该题上一轮的程序规格只是计算已整理出的(k,b)数值，没有检查原文字中的象限，因此未能发现矛盾。本次增加直接求交点、检查两个象限、横坐标差与线段长度比的计算规格；回归检查确认旧的“第二象限”条件没有任何正确选项，修正后的条件唯一命中A。这也说明程序表达式计算通过不能直接等同于全题正确。

## 所有15道修改

| 题号 | 类型 | 原因 |
|---|---|---|
{change_lines}

14道表述完善主要涉及数轴/线段对象、恒等结论、几何对象定义、同价与货款条件、物理单位、硬币独立性等。其中第66题将“≠”改成明确的“>”条件以避开教材口径差异，第107题去除给三角形、五边形预设“两条对角线交点”的不当问法。这些调整没有改变计数配额、难度暂定标签和答案字母。

## 记录与检查

- `review/assistant_self_check_v2/逐题自查记录.csv`：300道各自的重新推导，可用表格软件查看。
- `review/assistant_self_check_v2/records.jsonl`：同样的逐题记录，附题面摘要、自查时间和自查者标记；摘要绑定修正后的题干、选项、母题与答案，防止记录与版本错配。
- `review/assistant_self_check_v2/changes.json`：15道修改前后的全文对照。
- `review/assistant_self_check_v2/before/`：自查修正前的题库、页面、原稿与摘要备份。
- `完整题库浏览.html`：每道变式新增“本轮助手逐题自查”折叠区，可直接查看本题推导。
- `人工复核对照.html`和`review/人工复核结果表.csv`：后续用户独立复核，结果仍为pending。

修正后，236道可执行数学规格检查通过；64道仍属于未实现可靠自动验算，但已完成助手逐题阅读和推导。28项相关程序回归通过。全库1800题重新渲染与分集检查、复核页100项任务、离线原题复现及CSV往返检查通过。题库规模和120/120/60的变式暂定难度分布保持不变。

**本轮结论是“300道助手自查已完成，待用户独立复核”，不是“全库数学正确性已经独立确认”。** 自查来自生成者本人，可能仍有遗漏；难度也没有学生正确率或用时校准。自查推导作为内部记录保留，原题解析字段仍为未采集，模型输入文件不含这些推导或答案。
'''
    (r.OUT/'变式自查报告.md').write_text(self_report,encoding='utf-8')
    visualization=r.ROOT/'可视化/完整题库浏览.html';backup=r.OUT/'baseline/旧版完整题库浏览.html'
    if visualization.exists() and not backup.exists():shutil.copyfile(visualization,backup)
    shutil.copyfile(r.OUT/'完整题库浏览.html',visualization)
    latest='''# 当前版本：网页题源重建 v0.2 草稿

2026-10-22：1137道网站爬取题与363条历史网页题保持不变，已完成第二轮300道变式重生成及全部300道助手逐题自查，修正1道条件矛盾并完善另外14道表述。母题来源标签及变式暂定难度均为120/120/60，各年级100道，全部待用户独立复核。请打开[当前1800题浏览页](可视化/完整题库浏览.html)、[变式自查报告](data/benchmark_web_v0.2/变式自查报告.md)、[阶段实施报告](data/benchmark_web_v0.2/阶段实施报告.md)和[人工复核对照](data/benchmark_web_v0.2/人工复核对照.html)。统一程序入口为运行网页题库流程.ps1；只交付普通文件。尚有来源语义疑点和人工复核，不能视为正式冻结题库。本次没有运行模型评测。

以下为旧版历史记录，旧ZIP引用和旧分布不代表本轮交付。

---

'''
    project_readme=r.ROOT/'README.md';content=project_readme.read_text(encoding='utf-8')
    if content.startswith('# 当前版本：网页题源重建 v0.2'):
        content=content.split('\n---\n',1)[1].lstrip() if '\n---\n' in content else content
    project_readme.write_text(latest+content,encoding='utf-8')
    legacy_readme=r.ROOT/'scripts/site_crawler/README.md';content=legacy_readme.read_text(encoding='utf-8')
    banner='''> 更新：网页题源v0.2已完成四站独立试采，正式新爬1137道、历史沿用363条、新变式300道草稿。当前入口为项目scripts/edumath_web.py及运行网页题库流程.ps1，详见data/benchmark_web_v0.2/使用说明.md。下文为早期28道纯文字验证记录；其中“不使用OCR”“仅牛题库验证”和旧参数knowledges[0]不适用于新版。新版普通OCR试采单列，当前实际参数为knowledges=11568。\n\n'''
    if not content.startswith('> 更新：网页题源v0.2'):legacy_readme.write_text(banner+content,encoding='utf-8')
    manifest=[]
    for path in sorted(r.OUT.rglob('*')):
        if path.is_file() and path.name not in ('文件摘要.csv',):manifest.append({'path':path.relative_to(r.OUT).as_posix(),'bytes':path.stat().st_size,'sha256':r.sha(path)})
    with (r.OUT/'文件摘要.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['path','bytes','sha256']);writer.writeheader();writer.writerows(manifest)
    print(json.dumps({'files':len(manifest),'draft_records':1800,'normal_folder':str(r.OUT),'zip_created':False,'formal_math_review_completed':False},ensure_ascii=False))

if __name__=='__main__':main()
