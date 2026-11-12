"""Course report: chronological data acquisition decisions, without audit detail."""
from pathlib import Path
from collections import Counter
import json
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'汇报材料';OUT.mkdir(exist_ok=True)
NAME='EduMathBench_数据获取过程阶段汇报_2026-10-15'
qs=[json.loads(s) for s in (ROOT/'data/benchmark_draft/questions.jsonl').read_text(encoding='utf-8').splitlines()]
assert Counter(q['source_type'] for q in qs)=={'public':1500,'variant':300}
assert Counter(q['source_type'] for q in qs if q['split']=='dev')=={'public':150}
assert Counter(q['source_type'] for q in qs if q['split']=='test')=={'public':1350,'variant':300}

doc=Document();section=doc.sections[0]
section.page_width=Inches(8.5);section.page_height=Inches(11)
section.top_margin=section.bottom_margin=Inches(.65)
section.left_margin=section.right_margin=Inches(.75)
for name,size,line in [('Normal',11,17),('Title',21,28),('Subtitle',11,17),('Heading 1',14,21)]:
    s=doc.styles[name];s.font.name='Microsoft YaHei';s.font.size=Pt(size);s.font.color.rgb=RGBColor(0,0,0)
    fonts=s.element.get_or_add_rPr().get_or_add_rFonts();fonts.set(qn('w:eastAsia'),'Microsoft YaHei')
    for attr in ['asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme']:fonts.attrib.pop(qn('w:'+attr),None)
    for b in list(s.element.findall('.//'+qn('w:pBdr'))):b.getparent().remove(b)
    snap=OxmlElement('w:snapToGrid');snap.set(qn('w:val'),'0');s.element.get_or_add_pPr().append(snap)
    s.paragraph_format.line_spacing=Pt(line);s.paragraph_format.space_after=Pt(7)
    if name=='Heading 1':s.paragraph_format.space_before=Pt(11);s.paragraph_format.keep_with_next=True
doc.core_properties.title='EduMathBench 数据获取过程阶段汇报'
doc.core_properties.subject='按时间顺序说明数据如何获取以及方法调整原因'
doc.core_properties.author='EduMathBench 项目组'
md=[]
def p(text,style=None):
    para=doc.add_paragraph(text,style);md.append(text+'\n');return para
def h(text,new_page=False):
    para=doc.add_heading(text,1);para.paragraph_format.page_break_before=new_page;md.append('## '+text+'\n')

p('EduMathBench 数据获取过程阶段汇报','Title')
p('汇报日期  2026年10月15日','Subtitle')
p('本阶段围绕中文初中数学四选一题库展开。工作从少量试采开始，逐步调整为批量获取、按缺口补采，再完成变式构建和数据整理。截至目前，共形成1500道公开题和300道变式。下面按实际推进顺序说明数据如何取得，以及每次调整方法的原因。')

h('一 10月9日 先确定需要什么数据')
p('启动时先明确收集范围：七至九年级数学四选一题，公开题目标1500道，每个年级500道，并覆盖数与式、方程与不等式、函数、几何、统计与概率五个模块。题目必须有完整题干、四个选项和可追溯的参考答案，已有解析则保留。')
p('这样做是为了让题库服务于后续模型比较，而不是只追求数量。如果不先规定范围，容易收集到大量重复、超出初中范围或集中在少数知识点的题目，最后仍需要返工。')

h('二 10月9日 从公开资料进行少量试采')
p('最初从公开试卷、模拟题和同步练习资料中逐题提取题干、选项和答案，同时记录来源网址、资料名称和原题位置。先用少量题验证：题目能否完整取得，公式是否能保留，答案能否与题号对应。')
p('试采帮助确定了基本录入规则，也暴露出效率问题：不同网页格式不一致，有些题目预览省略公式，有些答案需要登录才能查看。逐题查找和整理的重复工作较多，因此这种方式适合验证题源和少量补缺，不适合作为1500道题的主要获取方式。')

h('三 10月9日起 转向公开数据包批量获取')
p('随后优先取得CMM-Math、TAL-SCQ5K等公开数学数据包，后续补充MathBench、C-Eval、CJEval等来源。先下载整份材料，再用程序提取题干、选项和答案，筛掉缺项、非法答案、明显残缺和不符合范围的记录，并进行重复检查。早期一次筛选与精确去重后，形成约2050条候选。')
p('批量获取减少了反复访问网页和手工录入，但候选数量不等于可用题量。不同数据集的学段、题型和分类标准并不一致，因此还要按主要知识重新判断年级与模块，依照配额选题；对脚本无法明确判断的记录，再由辅助智能体成批整理。来源版本、原题编号等信息一并保留，方便回查。')

h('四 10月13日至14日 针对困难题缺口补采',True)
p('批量筛选解决了数量问题，但没有自动解决覆盖问题。10月13日的一版题库虽然已有1500道题，暂定困难题只有63道，距离300道的目标仍有明显缺口。于是转向带答案的压轴选择题、培优专题和考试材料，按缺少的年级与模块定向补采。')
p('补采初期优先考虑纯文字题，以降低图片保存和核对的工作量；实际发现，一部分困难题尤其是几何题需要图形才能完整表达。为避免因输入形式限制漏掉合适题目，随后允许纳入图像题，完整保存题图并核对其与题干、选项的对应关系，纯文字困难题也继续收集。')
p('新题按同年级、同模块替换过量的基础或中等题，保持公开题总量1500道。最终公开题暂定分布为基础600道、中等600道、困难300道，包含202道图像题。难度依据来源专题信息和题面任务判断，未进行学生正确率或用时校准，也没有通过调高简单题标签来凑比例。')

h('五 10月14日 在预览中发现问题后统一整理')
p('公开题收集过程中持续检查空字段、重复、缺选项和来源定位；形成初版后，再通过本地预览检查实际显示效果。预览暴露出部分公式记号不兼容、表格排版不一致等问题，因此增加统一的格式处理，让不同来源的题目能以一致方式展示和使用。')
p('整理时保留来源原文和原答案，将显示格式修复与数学内容修改分开。对缺少必要条件的题目暂缓使用，对截断或异常的源解析作标记，不猜测补写。这样既能提高数据可用性，也能保留回查依据，避免在清洗过程中无意改变题意。')

h('六 10月14日 从公开母题构建300道变式')
p('公开题初版完成后，选出300道母题，每个年级100道，通过改变数值、系数或条件构造对应变式，并重新计算答案和干扰项。之所以增加变式，是为了在后续评测中比较同一知识点、相近题目条件下模型表现是否稳定。')
p('为控制制作与核验工作量，变式尽量不引入新图片，最终300道均采用纯文字表达；几何题仍保留，但用文字把必要关系说完整。每道变式与母题关联，记录改动与推导，并经过计算检查和独立题面初核。变式与公开原题分开标记，不能把生成变式当成来自公开试卷的题目，也不能据此保证消除训练数据污染。')

h('七 10月14日至15日 汇总题库并划分用途',True)
p('公开题和变式完成后，将题干、选项、答案、年级、模块和来源整理为统一字段，并提供本地浏览页面，便于抽查与回溯。当前共1800道题，七、八、九年级各600道，其中各有500道公开题和100道变式。')
p('按最新要求，开发集只使用公开题。为了避免调试时接触母题而影响后续对变式的评价，300道变式及其母题和关联题族全部放入测试集；开发集从其他公开题中选择。当前划分如下。')
t=doc.add_table(rows=1,cols=3);t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
widths=[2.3,2.35,2.35];values=[['用途','公开题','变式'],['开发集',150,0],['测试集',1350,300],['调试子集',100,0]]
for index,values_row in enumerate(values):
    row=t.rows[0] if index==0 else t.add_row()
    for i,(cell,value) in enumerate(zip(row.cells,values_row)):
        cell.width=Inches(widths[i]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cp=cell.paragraphs[0];cp.paragraph_format.line_spacing=Pt(16);cp.paragraph_format.space_after=Pt(0)
        cp.alignment=WD_ALIGN_PARAGRAPH.LEFT if i==0 else WD_ALIGN_PARAGRAPH.CENTER
        rr=cp.add_run(str(value));rr.font.size=Pt(10);rr.bold=index==0
        pr=cell._tc.get_or_add_tcPr();margin=OxmlElement('w:tcMar')
        for side in ['top','bottom','left','right']:
            n=OxmlElement('w:'+side);n.set(qn('w:w'),'90');n.set(qn('w:type'),'dxa');margin.append(n)
        pr.append(margin)
        if index==0:
            shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E8EEF5');pr.append(shade)
borders=OxmlElement('w:tblBorders')
for side in ['top','bottom','left','right','insideH','insideV']:
    b=OxmlElement('w:'+side);b.set(qn('w:val'),'single');b.set(qn('w:sz'),'5');b.set(qn('w:color'),'D9D9D9');borders.append(b)
t._tbl.tblPr.append(borders)
p('调试100题属于开发集，不额外计数。它们用于先检查程序能否正确读取题目、提取模型答案和记录结果；测试集在评测方法确定后使用。')

h('本阶段的收获与仍需注意的问题')
p('本阶段逐步形成了“先定范围、少量试采、批量获取、按缺口补采、统一清洗、再构建变式”的数据获取流程。方法上的主要调整都来自实际问题：逐题获取慢，就转向整包提取；困难题不足，就定向补采；纯文字限制影响覆盖，就保留必要图片；来源格式不一致，就统一整理并保留原文。')
p('目前完成的是题库初版，不等于全部题目已经通过数学复核。年级内部的困难题分布仍不均衡，部分公开题只有答案而无完整解析；现有来源和自动去重也不能保证排除所有近重复或模型已接触的题目。上述限制会影响后续结果解释，需要继续核查并如实报告。')

h('下一步工作')
p('下一步先开发评测程序，用开发集进行小规模调试，同时优先核查已知高风险题目。待题库和评测配置确定后，再开展测试集上的模型比较。当前尚未运行正式模型实验，因此本次汇报重点是数据获取过程、方法调整及形成的数据基础，不报告模型准确率或排名。')
note=p('过程依据为项目实施计划、批量采集记录、10月13日难度整理记录、10月14日公开题和变式完成记录，以及当前数据划分。')
note.paragraph_format.space_before=Pt(5)
for rr in note.runs:rr.font.size=Pt(9);rr.font.color.rgb=RGBColor.from_string('525C6A')

footer=section.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
rr=footer.add_run('EduMathBench 数据获取过程汇报  ');rr.font.size=Pt(8)
field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
output=OUT/(NAME+'.docx');doc.save(output)
(OUT/(NAME+'.md')).write_text('# EduMathBench 数据获取过程阶段汇报\n\n'+'\n'.join(md),encoding='utf-8')
print(output)
