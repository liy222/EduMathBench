"""Chronological acquisition report with verified implementation details."""
import json
import hashlib
from pathlib import Path
from collections import Counter
from urllib.parse import urlsplit
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'汇报材料';OUT.mkdir(exist_ok=True)
NAME='EduMathBench_数据获取与处理过程汇报_技术过程版_2026-10-15'
rows=[json.loads(s) for s in (ROOT/'data/benchmark_draft/questions.jsonl').read_text(encoding='utf-8').splitlines()]
assert Counter(q['source_type'] for q in rows)=={'public':1500,'variant':300}
assert Counter(q['source_type'] for q in rows if q['split']=='dev')=={'public':150}
assert Counter(q['source_type'] for q in rows if q['split']=='test')=={'public':1350,'variant':300}
source_families=[('ecnu-icalk/cmm-math','CMM-Math'),('math-eval/tal-scq5k','TAL-SCQ5K'),('lizhongzhi2022/cmmath','CMMaTH'),('ceval/ceval-exam','C-Eval'),('smilewhc/cjeval','CJEval'),('open-compass/mathbench','MathBench')]
source_counts=Counter();web_hosts=Counter()
public=[q for q in rows if q['source_type']=='public']
for q in public:
    url=q['source']['url'].lower()
    matches=[label for token,label in source_families if token in url]
    assert len(matches)<=1,'ambiguous primary source'
    source_counts[matches[0] if matches else '公开网页与PDF资料']+=1
    if not matches:web_hosts[urlsplit(url).netloc]+=1
assert source_counts=={'CMM-Math':699,'TAL-SCQ5K':156,'CMMaTH':130,'C-Eval':73,'CJEval':43,'MathBench':36,'公开网页与PDF资料':363}
assert sum(source_counts.values())==1500 and web_hosts['zy.21cnjy.com']==304
order=[label for _,label in source_families]+['公开网页与PDF资料']
distribution={'scope':'1500 selected unique public questions, grouped by current primary acquisition source; additional_sources not counted twice; generated variants excluded',
    'public_count':1500,'generated_variants':300,'dataset_count':1137,'web_pdf_count':363,
    'groups':[{'source':label,'count':source_counts[label],'percentage':round(source_counts[label]/1500*100,1)} for label in order],
    'web_pdf_hosts':dict(web_hosts.most_common()),
    'dataset_sha256':hashlib.sha256((ROOT/'data/benchmark_draft/questions.jsonl').read_bytes()).hexdigest()}
(ROOT/'data/reports/report_source_distribution_20261015.json').write_text(json.dumps(distribution,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
early=json.loads((ROOT/'data/bulk_probe/summary.json').read_text(encoding='utf-8'))
assert early['combined_preliminary_candidates']==2138 and early['conservative_exact_unique_candidates']==2050
doc=Document();sec=doc.sections[0]
sec.page_width=Inches(8.5);sec.page_height=Inches(11)
sec.top_margin=sec.bottom_margin=Inches(.62);sec.left_margin=sec.right_margin=Inches(.72)
sec.footer_distance=Inches(.25)
for name,size,line in [('Normal',11,17),('Title',21,28),('Subtitle',11,17),('Heading 1',15,22),('Heading 2',11.5,18)]:
    s=doc.styles[name];s.font.name='Microsoft YaHei';s.font.size=Pt(size);s.font.color.rgb=RGBColor(0,0,0)
    fonts=s.element.get_or_add_rPr().get_or_add_rFonts();fonts.set(qn('w:eastAsia'),'Microsoft YaHei')
    for attr in ['asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme']:fonts.attrib.pop(qn('w:'+attr),None)
    for border in list(s.element.findall('.//'+qn('w:pBdr'))):border.getparent().remove(border)
    snap=OxmlElement('w:snapToGrid');snap.set(qn('w:val'),'0');s.element.get_or_add_pPr().append(snap)
    s.paragraph_format.line_spacing=Pt(line);s.paragraph_format.space_after=Pt(6)
    if name.startswith('Heading'):
        s.paragraph_format.space_before=Pt(10);s.paragraph_format.keep_with_next=True
doc.core_properties.title='EduMathBench 数据获取与处理过程汇报'
doc.core_properties.author='EduMathBench 项目组'
doc.core_properties.subject='按工作推进阶段说明数据来源 获取技术 筛选清洗及方法调整'
md=[]
def p(text,style=None):
    q=doc.add_paragraph(text,style);md.append(text+'\n');return q
def h(text,level=1,newpage=False):
    q=doc.add_heading(text,level);q.paragraph_format.page_break_before=newpage;md.append('#'*(level+1)+' '+text+'\n')
def table(headers,body,widths):
    t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
    for i,w in enumerate(widths):t.columns[i].width=Inches(w)
    border=OxmlElement('w:tblBorders')
    for side in ['top','left','bottom','right','insideH','insideV']:
        b=OxmlElement('w:'+side);b.set(qn('w:val'),'single');b.set(qn('w:sz'),'5');b.set(qn('w:color'),'D9D9D9');border.append(b)
    t._tbl.tblPr.append(border)
    for k,values in enumerate([headers]+body):
        row=t.rows[0] if k==0 else t.add_row()
        for i,(cell,value) in enumerate(zip(row.cells,values)):
            cell.width=Inches(widths[i]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            c=cell.paragraphs[0];c.paragraph_format.line_spacing=Pt(14);c.paragraph_format.space_after=Pt(0)
            c.alignment=WD_ALIGN_PARAGRAPH.LEFT if i==0 or len(str(value))>15 else WD_ALIGN_PARAGRAPH.CENTER
            r=c.add_run(str(value));r.font.size=Pt(9.5);r.bold=k==0
            props=cell._tc.get_or_add_tcPr();margins=OxmlElement('w:tcMar')
            for side in ['top','bottom','left','right']:
                margin=OxmlElement('w:'+side);margin.set(qn('w:w'),'65' if side in ['top','bottom'] else '85');margin.set(qn('w:type'),'dxa');margins.append(margin)
            props.append(margins)
            shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E8EEF5' if k==0 else ('F7F9FB' if k%2==0 else 'FFFFFF'));props.append(shade)
        trpr=row._tr.get_or_add_trPr();trpr.append(OxmlElement('w:cantSplit'))
        if k==0:trpr.append(OxmlElement('w:tblHeader'))
    gap=doc.add_paragraph();gap.paragraph_format.line_spacing=Pt(4);gap.paragraph_format.space_after=Pt(3)
    md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(map(str,r))+' |' for r in body)+'\n')
def note(text):
    q=p(text);q.paragraph_format.line_spacing=Pt(14)
    for r in q.runs:r.font.size=Pt(9);r.font.color.rgb=RGBColor.from_string('4F5966')

p('EduMathBench 数据获取与处理过程汇报','Title')
p('按工作推进阶段说明获取方法与技术实现','Subtitle')
note('汇报日期  2026年10月15日')
p('本阶段的任务是形成用于初中数学模型评测的数据基础。实际工作先从公开资料试采开始，随后转向数据包批量获取，再根据覆盖缺口补充困难题和必要图像，最后完成清洗、变式构建与统一导出。当前形成1500道公开题和300道变式；下文按这一推进顺序说明采用的技术及其原因。')
h('一 启动阶段 先明确数据标准')
p('首先限定学科、学段与题型：中文七至九年级数学四选一题，公开题每年级500道，并按数与式、方程与不等式、函数、几何、统计与概率设置配额。题干、四个选项和来源参考答案必须能够对应；完整解析是可选字段。来源试卷年级另行保存，题库年级按解题所需主要知识暂定。')
p('这一步把“收集足够多的题”转成了可检查的任务：每个年级和模块还缺多少题、某道题为什么入选，都能通过记录核对。否则容易被题源自身的分布带偏，例如大量收进数式题，却缺少分式方程、函数或概率题。')
h('二 试采阶段 验证网页和PDF能否完整提取')
p('最初从公开试卷、模拟题和同步练习中少量提取，先打开题目正文及参考答案，再按原题号配对，保存网页HTML、取得内容的文本摘录或原PDF。网页标题写“含答案”并不足以入选，必须实际取得该题对应的答案；只取得公开预览时，记录其为预览或摘录，不写成完整原卷。')
p('PDF以pypdf提取文本，利用pdfplumber读取页面文字与位置，必要时渲染原页核对根号、分式、指数及选项。这样做是因为文字抽取顺序可能与视觉排版不同。早期曾遇到扫描PDF抽取文本为空，且原文件只有试题、没有答案，此类资料未直接录入，也没有自行计算一个答案来补足来源字段。')
p('试采确认了基本字段和来源配对方法，也暴露出逐网页采集的瓶颈：排版差异大、公式易丢、答案访问不稳定、重复登记较多。因此后续把网页与PDF保留为定向补缺渠道，主要题量转向格式较统一的公开数据包。')

h('三 批量获取阶段 下载可追溯的原始数据',newpage=True)
p('首轮主要使用Hugging Face上的CMM-Math与TAL-SCQ5K，之后按覆盖需要补充MathBench、C-Eval、CJEval和CMMaTH。采用“整份获取、本地筛选”的方式，减少逐题访问与复制。不同来源各有适用范围：竞赛数据不自动等于适合初中，CJEval中的改写题也不描述为未经改写的原始试卷题。')
h('当前入选公开题的主要来源分布',2)
p('按当前1500道公开题的主来源统计，公开数据集共提供1137道，约占75.8%；公开网页与PDF资料提供363道，约占24.2%。下表统计的是最终入选题，不是各题源下载量或早期候选数量。')
table(['主要来源','入选题数','占公开题比例'],[
    *[[label,source_counts[label],f'{source_counts[label]/1500*100:.1f}%'] for label in order],
    ['合计',1500,'100.0%']
],[3.9,1.25,1.85])
note('统计口径：每道公开题只计一次主来源，合并保留的附加来源不重复计数；比例保留一位小数，分项相加可能因四舍五入略有差异。这里表示实际获取渠道，不等于已逐题确认原始命题单位。')
p('网页与PDF部分以二一教育资料页面为主，其中304道的主来源记录指向zy.21cnjy.com，其余来自公开专题PDF、试卷和教辅资料网站。这与实际采集策略一致：数据包承担主要题量，网页和PDF用于补充具体章节与困难题缺口。')
p('此外，300道变式由项目在公开母题基础上生成，不列入上述公开题来源表。若按1800题全库统计，公开题占83.3%，生成变式占16.7%；变式仍保留母题来源关联。')
h('批量下载与字段适配的技术实现',newpage=True)
h('固定版本并保留下载清单',2)
p('实际批量探查使用Python的urllib.request发出HTTP请求。先读取数据集元信息中的提交版本revision，再通过带版本号的resolve链接下载文件；少量并发任务由ThreadPoolExecutor执行。取得文件后，先按UTF-8解析逐行JSON，避免把服务器错误页面当成题库文件保存。')
p('下载清单记录数据集名称、revision、文件URL、本地路径、字节数及SHA256。SHA256用于核对文件内容是否变化，revision用于定位当时取得的发布版本。这两项让后续复查能够回到同一份原始材料，而不依赖可能更新的在线“最新版”。')
h('为不同来源建立字段适配',2)
p('程序没有假设所有数据集格式相同。JSONL按行读取；即使文件扩展名为.json，也先检查其实际内容。CJEval的数学文件实际为JSONL，因此采用逐行解析。不同来源先映射为统一工作记录，再转成通用导出格式。')
table(['统一内容','CMM-Math来源字段','TAL-SCQ5K来源字段'],[
 ['题干','question','problem'],
 ['四个选项','options字符串，按A至D标记拆分','answer_option_list中的aoVal与content'],
 ['参考答案','answer','answer_value'],
 ['来源解析','analysis','answer_analysis'],
 ['原题定位','id及原文件行号','queId及原文件行号']
],[1.05,2.65,3.3])
p('选项拆分使用正则表达式识别字母及其后的句点、顿号或冒号等分隔符。对CJEval按字母标签建立选项映射，不把出现顺序直接当A、B、C、D；因此遇到B先于A的文本，仍可保留原标签与答案含义。缺失或重复标签的记录进入待处理池。')
note('首轮原始条目为33069条，经初筛形成2138条候选，保守精确去重后剩2050条、重复88条。2050是当时的候选规模，并非最终1500题的完成数；后续仍进行了范围审核和其他来源补采。')

h('四 筛选阶段 把可解析记录变成可用候选',newpage=True)
h('先检查结构 再判断课程范围',2)
p('结构检查由本地Python脚本执行：题干与四选项非空，答案必须为A、B、C、D之一，题号不重复，来源登记和原件路径存在，并检查异常控制字符、替换字符及明显缺式提示。首轮纯文字筛选还结合image字段、图片占位符和“如图”等提示识别图依赖；加入图像题后改为检查必要图片是否完整，而非一律排除。')
p('结构通过只表示记录满足输入要求，不能证明题设充分或答案唯一。对于缺图、缺选项、源答案冲突和明显超范围题目，保留原因并暂缓或退回；对超过当前配额、但结构合格的题目保留候补，不计入初版完成数。')
p('年级与模块分类以题干、选项和主要知识为依据，来源学段与大类标签只作为提示。规则脚本先识别概率、统计量、函数表达式及几何主题等特征，再把模糊项交给辅助智能体复看。例如数轴上的“平移”不直接等于图形变换，题干出现“圆珠笔”也不能归为圆几何。只按关键词归类会造成课程定位错误，因此需保留分类依据和修订记录。')
h('用内容指纹检查重复与答案冲突',2)
p('初步精确去重对题干和四选项做保守Unicode规范化及空白处理，保留负号、数字、指数和括号，再用SHA256计算内容指纹。相同指纹只保留一个主记录，其余来源并入附加来源字段。后续含图记录的查重指纹还纳入对应图片摘要，防止题面文字相同、但题图不同的题目误合并。')
p('随后增加选项重排检查：将规范化选项内容排序后分组，并比较答案所指向的选项内容。不能只比较答案字母，因为同一道题更换选项顺序后，正确字母可能变化；反之，字母相同也可能指向不同内容。答案含义冲突的组不直接合并为可用题。')
p('对于改了数值、表达方式或条件的近重复，采取分组而非自动删除。后续题族整理再结合母题关系、已知重复记录及数字模板进行保守关联。这能减少相关题跨开发测试集的情况，但并不构成穷尽的语义去重。')
h('脚本与辅助智能体各自承担什么',2)
p('脚本承担格式、字段、指纹、配额和路径等可重复检查；Luna优先处理成批提取、暂定标签及结构复核；复杂推导、可疑条件和分类冲突由主智能体或专岗处理。标签和问题处置以附表保留，不通过覆盖来源原文来掩盖争议，也不把辅助检查写成全库数学批准。')

h('五 补采阶段 按困难覆盖缺口扩大来源',newpage=True)
p('早期题库达到1500道后，暂定困难题只有63道，说明数量达标并不等于覆盖达标。后续检索带答案的压轴选择题、培优专题和考试材料，并补充CMMaTH等图文来源。新入选题按同年级、同模块替换过量基础或中等题，保持1500道公开题的年级模块配额。')
p('困难判断区分三类信息：来源明确的难度标签、压轴或培优专题中的定位、项目根据题面作出的暂定判断。竞赛出处或专题标题都不能直接证明每一道题困难；当前标签也没有学生正确率和用时校准。最后公开题暂定为600基础、600中等、300困难，未通过抬高简单题标签来凑比例。')
h('从纯文字扩展到必要图像',2)
p('纯文字处理成本较低，但会遗漏一部分几何、函数图象等题目，因此在困难题补采受限时纳入图像。对于数据集中的题图，按原记录的图片引用定位到同一版本的图像压缩包；下载后保留原图，不自行重绘推测条件。')
p('为取得大型压缩包中的所需成员，部分下载脚本读取ZIP目录与成员偏移，通过HTTP Range请求获取对应字节段，核查206响应及Content-Range，再解压并验证CRC、长度和SHA256。也保留完整包下载方式；不会把“采用按需提取”表述为所有图片都只经过这种方式取得。')
p('图片并非只要下载成功就能入库。程序将图片标记为题干图或某个选项图，并记录所在字段、占位符位置、源文件名和校验值；解析图与答案图不作为输入。对占位符数量与图片引用数量不一致的记录暂缓，避免错配或漏图。')
h('PDF公式丢失时保留原题裁图',2)
p('部分公开PDF能抽取文字，但复杂数学符号丢失。对此用pdfplumber定位原题号与【答案】所在位置，用pdftoppm渲染页面，再使用Pillow裁取题干、原四选项和必要配图；跨页题目按顺序拼接，裁切止于印刷答案之前。裁图保存原页码和裁切坐标，并核对不含答案与解析。')
p('这类题保留text_image形式，不把残缺提取文本误当完整纯文字题。最终公开题含202道图像题，对应219次图片引用和218个独立文件；困难题中仍保留98道纯文字题。图片只扩大可用候选范围，并未把困难题限定为图形题。')

h('六 整理阶段 统一公式表示并保留可回查链条',newpage=True)
h('把来源保存层与使用层分开',2)
p('本地预览暴露出部分公式命令不兼容、HTML转义残留和表格排版不一致的问题。为避免只修网页显示而实际输入仍有问题，项目建立独立规范化层：来源原文保存为原始记录，规范化题面统一供浏览页面和通用导出使用。公开题处理规则记录在format_normalization中，来源输入保留在source_input中。')
p('具体处理包括HTML实体解码、特定来源命令映射、公式分隔符规范化、数字上标和表格结构处理。例如把来源自定义的全等、弧线等记号转换为公式库可识别的形式；对正文和数学区域分别处理，避免把普通文字误当公式。处理不删除负号、改变指数或重排选项，不以排版修复名义改题意和答案。')
p('公式通过KaTeX解析检查，表格转为真实单元格；页面与数据文件逐题比较，图片核对路径及摘要。1500题旧版取得了用户提供的实际浏览器报告，当前1800题新版另有公式和模拟交互检查，尚无新版真实浏览器报告。公式可解析、页面能显示和数学答案正确是不同层面的结论。')
h('保留题目来源与清洗记录',2)
p('每题可由稳定题号回到来源名称、URL、版本、文件、原始题号或行号；PDF补充页码和题号，图片补充原包成员或裁切位置。相同题目多处出现时保留附加来源。下载清单、原件、分类附表、重复组和修订说明分开保存，使后续发现问题时能够定位到具体转换环节。')
p('例如一条CMM记录的追溯链为：项目题号→来源数据集及固定版本→all_data.jsonl中的原行与原ID→该行answer字段；图像题再通过image_assets连接原图片。对能映射的1137道数据集题已逐字段比较题干、四选项和来源答案，未发现未解决的对应差异。该核对证明提取对应关系，不证明源答案数学正确。')
h('对不完整解析标记而不补猜',2)
p('已有解析按来源保留，未提供解析的题目不通过生成文字伪装成源解析。当前全库1289题有解析文本、511题未保存解析，41道异常源解析片段属于有解析的子集。异常片段在页面中明确标记并原样展示；是否有解析只按文本是否非空判断，不能作为已完成验算的依据。')
note('原题保留、规范化输入统一、来源定位可回查，是本阶段清洗工作的主要约束。数据复用条件和二手题源的原试卷信息仍需后续确认。')

h('七 扩展阶段 在公开母题基础上构建变式',newpage=True)
p('公开题初版完成后，从各年级与模块中选择300道母题，改变数值、系数或题目条件，重新计算正确结果并重造干扰项。先完成小批试做，再按批次扩展至300道。其目的在于观察同一知识或相近结构在条件变化后的模型表现，而不是把生成题充当新增公开原题。')
p('每道变式标记source_type为variant，通过parent_id连接母题，记录改动说明、推导、暂定难度及生成信息。为降低制图与核验成本，300道变式均采用纯文字；保留几何题，但要求文字足以完整定义点线角和位置关系。')
p('验证分成两层：一层是结构与显式算术或约束检查，使用Python的ast解析受限表达式，通过Fraction尽量保留有理数精度，并针对适用题型进行代入或有限枚举；另一层由生成者以外的岗位检查题面推导、答案唯一性与退化条件。300题已完成独立初核，但有限计算不代替一般证明，也未升级为最终数学批准。')
h('八 交付阶段 汇总1800题并隔离评测用途')
p('最终将题干、选项、答案、标签、来源和图片关联导出为JSONL与CSV。JSONL每行一道题，便于程序逐条读取；CSV保留独立选项列，便于人工筛选。模型输入另行导出题干、选项与必要图片，答案和解析分开保存，防止后续调用时泄漏标准答案。必要图片一并打包，本地HTML页面内嵌题目、公式库与字体，便于离线抽查。')
p('按最新要求，开发集只包含公开题。程序以母题关联、既有同族信息、已知重复与数字模板构建连通题族，再按整个题族划分；同一母题和变式不拆开。划分使用固定种子与题号清单，所有300道变式及其母题族均在测试集，降低开发时接触相关题目造成的评价偏差。')
table(['集合','公开题','变式','用途'],[
 ['开发集',150,0,'选择提示词与调试评测流程'],
 ['测试集',1350,300,'配置确定后进行正式比较'],
 ['调试子集',100,0,'开发集的子集，不额外计数']
],[1.2,.9,.8,4.1])
p('至此形成1500道公开题与300道变式，每年级600道。仍需继续处理数学正确性、课程标签、语义近重复及已知高风险题；暂定难度的年级分布也不均衡。下一步开发评测程序并用开发集试运行，之后复核、冻结并正式测试，当前没有模型准确率或排名结论。')
note('过程依据：项目采集规范与批量探查记录；probe_bulk_sources、prepare_bulk_work、select_bulk_collection、check_collection、PDF与图片处理、question_format及变式验证脚本；当前题库与划分记录。本文按实际方法演进组织，不把可选技术或候选数量写成已经完成的结果。')

footer=sec.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
r=footer.add_run('EduMathBench 数据获取与处理过程汇报  ');r.font.size=Pt(8)
field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
doc.save(OUT/(NAME+'.docx'))
(OUT/(NAME+'.md')).write_text('# EduMathBench 数据获取与处理过程汇报\n\n'+'\n'.join(md),encoding='utf-8')
print(OUT/(NAME+'.docx'))
