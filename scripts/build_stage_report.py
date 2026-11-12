"""Build a stage-report document from the current audited data snapshot."""
import json, hashlib
from pathlib import Path
from collections import Counter
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'汇报材料';OUT.mkdir(exist_ok=True)
NAME='EduMathBench_阶段工作汇总_2026-10-15'
def read(p):return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
qs=read(ROOT/'data/benchmark_draft/questions.jsonl')
public=[q for q in qs if q['source_type']=='public'];variants=[q for q in qs if q['source_type']=='variant']
policy=json.loads((ROOT/'data/benchmark_draft/split_policy.json').read_text(encoding='utf-8'))
audit=json.loads((ROOT/'data/reports/luna_split_audit/final_audit.json').read_text(encoding='utf-8'))
presentation=json.loads((ROOT/'data/reports/benchmark_draft_presentation_check.json').read_text(encoding='utf-8'))
assert len(qs)==1800 and len(public)==1500 and len(variants)==300 and audit['passed']
assert policy['version']=='split-policy-v0.2'
dev=[q for q in qs if q['split']=='dev'];test=[q for q in qs if q['split']=='test'];debug=[q for q in qs if q['debug_subset']]
assert len(dev)==150 and all(q['source_type']=='public' for q in dev)
assert len(test)==1650 and sum(q['source_type']=='variant' for q in test)==300
assert len(debug)==100 and all(q['source_type']=='public' for q in debug)
assert presentation['formulas_checked']==19252 and not presentation['formula_errors']
assert presentation['synthetic_control_checks']==9338
solution_counts={typ:sum(bool(q.get('solution','').strip()) for q in rows) for typ,rows in [('public',public),('variant',variants),('all',qs)]}
assert solution_counts=={'public':989,'variant':300,'all':1289}

doc=Document();sec=doc.sections[0]
sec.page_width=Inches(8.5);sec.page_height=Inches(11)
sec.top_margin=Inches(.65);sec.bottom_margin=Inches(.65);sec.left_margin=Inches(.72);sec.right_margin=Inches(.72)
sec.header_distance=Inches(.25);sec.footer_distance=Inches(.25)
for name in ['Normal','Title','Subtitle','Heading 1','Heading 2']:
    st=doc.styles[name];st.font.name='Microsoft YaHei';st.font.color.rgb=RGBColor(0,0,0)
    st.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'Microsoft YaHei')
    for border in list(st.element.findall('.//'+qn('w:pBdr'))):border.getparent().remove(border)
    fonts=st.element.get_or_add_rPr().get_or_add_rFonts()
    for key in ['asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme']:fonts.attrib.pop(qn('w:'+key),None)
    snap=OxmlElement('w:snapToGrid');snap.set(qn('w:val'),'0');st.element.get_or_add_pPr().append(snap)
normal=doc.styles['Normal'];normal.font.size=Pt(11)
normal.paragraph_format.line_spacing=Pt(17);normal.paragraph_format.space_after=Pt(6)
for name,size in [('Title',22),('Subtitle',11),('Heading 1',16),('Heading 2',12)]:
    st=doc.styles[name];st.font.size=Pt(size);st.paragraph_format.line_spacing=Pt(size+6);st.paragraph_format.space_before=Pt(9 if name.startswith('Heading') else 0);st.paragraph_format.space_after=Pt(6)
    if name.startswith('Heading'):st.paragraph_format.keep_with_next=True
doc.core_properties.title='EduMathBench 项目阶段工作汇总'
doc.core_properties.subject='数据准备 变式构建 质量检查与评测准备'
doc.core_properties.author='EduMathBench 项目组'
doc.core_properties.keywords='初中数学 评测题库 阶段汇报 数据准备'
md=[]
def p(s,bold_lead=None,style=None):
    para=doc.add_paragraph(style=style)
    if bold_lead and s.startswith(bold_lead):para.add_run(bold_lead).bold=True;para.add_run(s[len(bold_lead):])
    else:para.add_run(s)
    md.append(s+'\n');return para
def h(s,level=1):doc.add_heading(s,level);md.append('#'*(level+1)+' '+s+'\n')
def page(s):
    paragraph=doc.add_heading(s,1);paragraph.paragraph_format.page_break_before=True;md.append('## '+s+'\n')
def table(headers,rows,widths):
    t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
    for i,w in enumerate(widths):t.columns[i].width=Inches(w)
    pr=t._tbl.tblPr;borders=OxmlElement('w:tblBorders')
    for edge in ['top','left','bottom','right','insideH','insideV']:
        x=OxmlElement('w:'+edge);x.set(qn('w:val'),'single');x.set(qn('w:sz'),'5');x.set(qn('w:color'),'D9D9D9');borders.append(x)
    pr.append(borders)
    for idx,values in enumerate([headers]+rows):
        cells=t.rows[0].cells if idx==0 else t.add_row().cells
        for j,(cell,value) in enumerate(zip(cells,values)):
            cell.width=Inches(widths[j]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcp=cell._tc.get_or_add_tcPr();margin=OxmlElement('w:tcMar')
            for edge,n in [('top',50),('bottom',50),('left',90),('right',90)]:
                item=OxmlElement('w:'+edge);item.set(qn('w:w'),str(n));item.set(qn('w:type'),'dxa');margin.append(item)
            tcp.append(margin)
            shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E8EEF5' if idx==0 else ('F7F9FB' if idx%2==0 else 'FFFFFF'));tcp.append(shade)
            cp=cell.paragraphs[0];cp.paragraph_format.space_after=Pt(0);cp.paragraph_format.line_spacing=Pt(14)
            cp.alignment=WD_ALIGN_PARAGRAPH.LEFT if j==0 or len(str(value))>15 else WD_ALIGN_PARAGRAPH.CENTER
            r=cp.add_run(str(value));r.font.size=Pt(9.5);r.bold=idx==0
            trpr=cell._tc.getparent().get_or_add_trPr()
            if trpr.find(qn('w:cantSplit')) is None:trpr.append(OxmlElement('w:cantSplit'))
        if idx==0:
            repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
    gap=doc.add_paragraph();gap.paragraph_format.line_spacing=Pt(4);gap.paragraph_format.space_after=Pt(3);gap.add_run().font.size=Pt(1)
    md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(map(str,row))+' |' for row in rows)+'\n')
    return t
def small(s):
    para=p(s)
    para.paragraph_format.line_spacing=Pt(14)
    for r in para.runs:r.font.size=Pt(9);r.font.color.rgb=RGBColor.from_string('4D5968')
    return para

doc.add_paragraph('EduMathBench 项目阶段工作汇总','Title');md.append('# EduMathBench 项目阶段工作汇总\n')
doc.add_paragraph('数据准备与变式构建阶段汇报','Subtitle')
small('汇报日期  2026年10月15日     工作范围  2026年10月9日至10月15日')
h('一 阶段结论与项目范围')
p('截至汇报日，项目已完成1500道公开题收集、300道变式构建及1800题初版整理，建立了来源追溯、格式规范化、题族分组、开发测试划分和本地离线浏览功能。当前已具备评测程序开发所需的数据基础；尚未开展正式模型评测，题库也未最终冻结。','截至汇报日')
p('项目面向中文初中七至九年级数学四选一任务，研究模型总体表现、知识模块差异、难度影响以及母题与变式的表现差异。研究目标是评测现有模型，不包含模型微调。原实施计划作为基线，图像题范围、变式制作方式和开发集组成按后续要求调整。[S1]')
table(['成果项目','当前结果'],[
 ['公开题与变式','1500道公开题＋300道变式，共1800道'],
 ['年级覆盖','七、八、九年级各600道，均为500公开＋100变式'],
 ['图文形式','1598道纯文字、202道含图；300道变式全部纯文字'],
 ['题族与关联','300个母题—变式对；自动分组1492个题族'],
 ['数据划分','开发集150公开；测试集1350公开＋300变式'],
 ['阶段状态','数据初版及暂定划分完成；评测程序和正式实验待开展']
],[1.55,5.45])
h('全库年级与模块覆盖',2)
table(['年级','数与式','方程与不等式','函数','几何','统计与概率','合计'],[
 ['七年级',240,180,0,120,60,600],['八年级',120,180,120,120,60,600],['九年级',0,60,240,180,120,600],['合计',360,420,360,420,240,1800]
],[.8,.82,1.28,.7,.7,1.1,.6])
small('本表含公开题及变式。零配额表示本版不以该年级模块组合为采集目标，不表示该年级完全不涉及该知识。[S2]')

page('二 公开题采集与来源整理')
h('采集方式与覆盖补齐',2)
p('公开题按先定配额、后采集的方式推进。早期逐网页提取较慢，随后转为公开数据包和整份资料批量提取，统一筛选题型、答案、主要知识归属和配额，再针对分式方程、几何、概率及困难题缺口定向补采。下载记录、异常候选和候补题不计入1500道正式初版数量。')
p('公开题最终达到每年级500道及全部年级模块配额。困难题收集范围同时保留纯文字题和图像题；202道含图题计入公开题初版，困难题中另有98道纯文字题。图像题的纳入是补充覆盖的选择，并未将困难题限定为图形题。[S3]')
h('来源追溯与对应检查',2)
p('每题保留来源名称、网址、原题定位、答案位置、获取时间和原材料路径；公开数据集同时保留版本、原记录编号或行号。重复题合并时保留附加来源。来源试卷年级与按主要知识暂定的题库年级分开记录。')
table(['已逐字段对应的来源','核对题数'],[
 ['CMM Math',699],['CMMaTH',130],['TAL SCQ5K',156],['C Eval',73],['CJ Eval',43],['MathBench',36],['合计',1137]
],[5.5,1.5])
p('1137道数据集题已对照归档原记录核对题干、四选项和来源答案，未发现未解决的对应差异。其余363道题不计入这一逐记录核对数量，采用各批提取记录及网页、PDF原页抽查。该检查证明转换对应关系，不证明来源答案在数学上正确。[S4]')
h('原件与修订记录',2)
p('来源原件、原始主库和规范化输入分别保存。对明显重复、图片字段错放、分类争议及源解析笔误保留处置记录；不通过修改来源答案来掩盖问题。已修正过一处母题候选将文具单价题误归九年级圆几何的选择问题，替换候选保留快照和账本，未改写公开题原记录。')
small('部分题源为二手公开数据集，尚未逐题核实原始试卷；公开可访问不等于复用许可已确认。相关风险继续保留。[S3 S4]')

page('三 变式构建与暂定难度')
h('300道变式的构建与初核',2)
p('从1500道公开题中确定300道母题，一题对应一道变式，七、八、九年级各100道。先完成30道试做，扩展到90道后再补齐210道，最终达到300道。变式通过调整数值、系数、条件或对象关系构造，并重新计算正确选项和干扰项。')
p('为控制制图和核验工作量，300道变式均采用纯文字；几何题保留，使用完整文字说明点线角、运动或位置关系。每题记录母题号、题族、来源、修改说明、四个选项、候选答案、推导、难度依据、生成岗位及时间。[S5]')
p('全部300道变式通过结构检查、显式算术或约束检查及生成者以外的独立题面初核。交叉初核处理了集合结果遗漏、等价干扰项、定理退化条件及位置表述等问题；复核记录与最终题面内容摘要绑定。算术约束和代表点检查不充当一般定理证明，独立初核仍未升级为正式数学批准。')
h('难度分布与标注口径',2)
table(['题类','基础','中等','困难','合计'],[
 ['公开题',600,600,300,1500],['变式',123,122,55,300],['全库',723,722,355,1800]
],[2.6,1.1,1.1,1.1,1.1])
p('难度结合来源专题证据和题面任务判断暂定，保留逐题依据；未采集目标年级学生正确率、用时等实证校准数据。变式原覆盖目标为120基础、120中等、60困难，实际按内容标为123、122、55，不为凑比例抬高难度。')
table(['公开题年级','基础','中等','困难','合计'],[
 ['七年级',209,265,26,500],['八年级',220,189,91,500],['九年级',171,146,183,500]
],[2.6,1.1,1.1,1.1,1.1])
small('公开题全库40%／40%／20%的目标已满足，但年级内部难度明显不均衡。后续分层分析必须同时报告各层样本量，不能将暂定标签表述为经学生实测的难度。[S6]')
h('辅助智能体分工',2)
p('重复提取、来源登记、覆盖统计、格式与结构复核优先使用Luna；复杂推导、变式生成、交叉初核和争议处理由主智能体及专岗承担。部分生成记录仅写明继承主模型，汇报不反推未记录的具体版本。已保存角色和复核记录，尚无可据以量化金额或速度节省的完整成本统计。[S5 S7]')

page('四 格式修复与质量检查范围')
h('格式规范化与图片完整性',2)
p('针对浏览器中公式命令残留、乱码样显示及表格排版问题，建立独立规范化层，处理公式分隔符、部分来源专用命令、HTML转义及表格结构。保留原始题面于来源输入记录，不改变题目条件、选项顺序或来源答案。规范化公开题版本为question-format-v1.1。[S8]')
p('公开题202道含图题共有219次图片引用、218个独立文件；已核对文件存在性、SHA256及题干或选项角色。答案图、解析图不作为模型输入。此前7道母题“缺图”提示源于漏读image_assets字段，复查确认原图完整，筛选逻辑和历史说明已更正。')
table(['检查对象','已完成证据','适用范围'],[
 ['1500道公开题页面','用户提供真实浏览器报告；1500题、7703个公式节点、219次图引用、9表152格；报告问题0','Edge记录视口1409px；不等于逐题人工视觉审阅'],
 ['当前1800题完整页面','19252段显示公式解析错误0；9338项模拟控制检查通过；219次图引用核对','公式引擎及模拟交互检查；尚无新页真实浏览器报告']
],[1.4,3.4,2.2])
h('解析文本的实际覆盖',2)
table(['题类','有解析文本','无解析文本','其中异常片段'],[
 ['公开题',989,511,41],['变式',300,0,0],['合计',1289,511,41]
],[2.5,1.5,1.5,1.5])
p('完整解析在原计划中为可选字段。511道公开题未保存解析文本，但保留参考答案。41道源解析仍有截断或格式异常，属于有解析文本的子集；页面明确提示并原样展示，不猜测补齐推导。有文本不代表内容完整，也不代表来源答案正确。')
p('旧公开题页面曾只展示答案而未展示已保存的解析。当前完整页面已补充解析展示及有解析、无解析、异常片段筛选，每题有可见状态，数量随其他筛选条件更新。[S9]')
small('全库结构与来源检查、格式引擎检查、真实浏览器DOM检查、独立数学初核分别记录，不互相替代。当前不能汇报为“全部题目数学正确、全部页面人工检查通过”。')

page('五 数据划分与本地交付')
h('开发集仅使用公开题',2)
p('按最新要求，开发集不包含变式，采用split-policy-v0.2覆盖原计划中的混合开发集。所有300道变式及其公开母题和整个关联题族均放入测试集；开发集从其他公开题族中选取。数据总量保持1800题。[S2 S10]')
table(['集合','公开题','变式','总数','年级分布'],[
 ['开发集',150,0,150,'50／50／50'],['测试集',1350,300,1650,'550／550／550'],['调试子集',100,0,100,'34／33／33']
],[1.45,1.05,.85,.95,2.7])
p('调试100题属于开发集，不额外计数。它用于先检查题面与图片输入、答案提取、错误日志和统计流程；开发集整体用于确定提示词、解析规则与评测配置。测试集在配置确定后用于最终比较，不用测试结果反复调参。当前尚未实际运行模型测试。')
p('划分保留旧开发集中符合新规则的90道公开题及旧调试子集中的60道公开题，并分别补齐至150和100题。旧划分及审计快照归档，当前题号清单、种子、配置和输入摘要固定，可重复生成。全部已识别题族无跨开发测试集情况。')
h('题族分组的依据与边界',2)
p('自动分组共1492个题族，覆盖母题与变式、既有同族标签、已知重复与别名、忽略选项顺序的相同文字及保守数字模板候选。题族用于隔离，未因分组删题。未记录的文字改写或语义近重复仍可能漏检；现有公开题和变式也不能保证未被模型训练数据接触。')
h('通用格式与离线浏览',2)
p('提供统一JSONL、带BOM的UTF-8 CSV、开发测试与调试题号清单、无答案模型输入、单独答案表、图片、字段说明和文件摘要。模型输入仅保留题干、选项及所需图片字段；答案、解析、来源、难度、题族和审核信息不进入解题提示。')
p('本地完整页面通过HTML、JavaScript和公式库实现，题目、图片和字体全部内嵌，双击即可离线打开，不需部署服务。支持集合、题类、年级、模块、难度、解析状态筛选，题号搜索、来源查看及同族题跳转。访问外部来源链接时才需要联网。')
small('已完成Luna独立结构复核及JSONL／CSV／HTML一致性核对；最新ZIP通过完整性、manifest和摘要核验。数据状态仍为草稿，不视为正式冻结。[S9 S10]')

page('六 遗留问题与下一阶段安排')
h('仍需完成的质量工作',2)
p('数学正确性方面，1500道公开题尚未逐题独立求解；300道变式虽已完成独立初核，仍待最终复核与冻结。优先处理41道异常源解析及已有高风险记录，通过重新验算确认参考答案，必要时修订或剔除并保留版本。511道无解析题不因缺少解析自动判为无效，应结合答案可靠性和评测用途决定是否补充。')
p('覆盖与标签方面，年级内部难度不均衡，教材版本尚未最终指定，知识归属与困难标签仍属暂定。后续应核查明显分类争议，按样本量解读年级与难度分层结果，不以改标签凑配额。')
p('数据与展示方面，自动分组不构成穷尽语义去重；二手数据集的原试卷与复用条件尚需确认；当前1800题页面尚缺真实浏览器运行报告。上述问题应在冻结记录中逐项明确处置结果。')
h('评测程序开发与试运行',2)
p('第一步，开发本地数据加载、图片校验和纯文字／含图任务分流，限定模型输入白名单。纯文字模型不能静默纳入无法读取的图像题；正式比较前应确定可比题集和报告口径。')
p('第二步，实现答案提取、无效回复、拒答、超时和逐题日志，保存原始响应、模型配置、提示词版本、运行编号和数据摘要。先用独立构造的模拟响应及模拟题对验证功能；模拟结果不能当作模型能力数据。')
p('第三步，用开发集中的100道公开题调试，稳定后利用其余50道公开题检查配置。开发集没有变式，不计算真实题对指标；题对计算功能使用模拟数据调试。实际模型版本、图像能力、接口和运行预算确定后，再启动有成本的模型调用。')
p('第四步，开展集中质量复核并冻结数据与配置，然后使用测试集正式评估。报告总体及年级、模块、暂定难度分层准确率，并对300个完整母题—变式对计算两题同时正确率及一致性，报告样本量和未运行或不适用题。[S11]')
h('阶段汇报可直接采用的结论',2)
p('本阶段完成了1800题初版的数据准备，包括1500道可追溯公开题、300道有母题关联和独立初核记录的纯文字变式，以及统一格式、离线浏览、题族隔离和公开题开发集。已建立可核验的数据处理与检查记录；当前成果是评测数据和工具准备，尚未形成模型准确率、模型排名或变式鲁棒性结论。下一阶段将推进评测程序、开发集试运行和正式评测前的质量复核。')

page('附录 成果文件与证据索引')
p('项目根目录为D:\\EduMathBench。以下路径相对项目根目录；当前使用完整1800题页面和split-policy-v0.2，旧页面与旧划分仅作历史记录。')
table(['主要成果','文件位置'],[
 ['本地完整题库','可视化/完整题库浏览.html'],
 ['1800题通用数据','data/benchmark_draft/questions.jsonl\ndata/benchmark_draft/questions.csv'],
 ['开发测试及调试题号','data/benchmark_draft/splits/'],
 ['模型输入与答案表','data/benchmark_draft/*_inputs.jsonl\ndata/benchmark_draft/*_answer_key.jsonl'],
 ['题族与划分','data/benchmark_draft/families.jsonl\ndata/benchmark_draft/split_policy.json'],
 ['完整交付包','data/exports/EduMathBench_1800_draft_v0.1.zip'],
 ['300题对与变式独立包','data/variants/collection/pairs.json\ndata/exports/EduMathBench_variants_300_draft.zip']
],[1.65,5.35])
h('检查证据',2)
refs=[
 ('S1','原实施计划','C:/Users/liyh/Downloads/EduMathBench_实施计划.md'),
 ('S2','当前数量及划分','data/benchmark_draft/statistics.json；split_policy.json'),
 ('S3','公开题收集完成记录','data/reports/completion_report.md'),
 ('S4','来源对应审计','data/reports/provenance_audit.md'),
 ('S5','变式完成与初核','data/variants/batches/b003/completion_report.md；data/reports/variant_collection_check.json'),
 ('S6','暂定难度依据','data/reports/difficulty_review.md'),
 ('S7','辅助智能体安排与生成记录','docs/agent_assignments.md；data/variants/collection/questions.jsonl'),
 ('S8','规范化与公开题浏览器报告','data/reports/format_check.md；data/reports/luna_render_audit/browser_report_current_result.md'),
 ('S9','当前页面与数据一致性','data/reports/benchmark_draft_presentation_check.json；benchmark_draft_verify.json'),
 ('S10','最新独立结构审计与划分修订','data/reports/luna_split_audit/final_audit.json；data/reports/split_revision_v0.2.json'),
 ('S11','后续评测程序计划','docs/evaluation_stage_plan.md')]
for label,title,path in refs:
    para=p(f'[{label}] {title}  {path}')
    para.paragraph_format.line_spacing=Pt(13)
    for r in para.runs:r.font.size=Pt(8.8)
small('完整包SHA256  '+sha(ROOT/'data/exports/EduMathBench_1800_draft_v0.1.zip'))

footer=sec.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
rr=footer.add_run('EduMathBench 阶段汇报  ');rr.font.size=Pt(8)
field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
path=OUT/(NAME+'.docx');doc.save(path)
(OUT/(NAME+'.md')).write_text('\n'.join(md),encoding='utf-8')
snapshot={'report_date':'2026-10-15','public':1500,'variants':300,'total':1800,'dev':{'public':150,'variant':0},'test':{'public':1350,'variant':300},'debug100':{'public':100,'variant':0},'solution_counts':solution_counts,'fragment_solutions':41,'policy':policy['version'],'dataset_sha256':sha(ROOT/'data/benchmark_draft/questions.jsonl'),'zip_sha256':sha(ROOT/'data/exports/EduMathBench_1800_draft_v0.1.zip'),'report_sha256':sha(path)}
(ROOT/'data/reports/stage_report_facts_20261015.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'docx':str(path),'paragraphs':len(doc.paragraphs),'tables':len(doc.tables),'bytes':path.stat().st_size},ensure_ascii=False))
