> 更新：网页题源v0.2已完成四站独立试采，正式新爬1137道、历史沿用363条、新变式300道草稿。当前入口为项目scripts/edumath_web.py及运行网页题库流程.ps1，详见data/benchmark_web_v0.2/使用说明.md。下文为早期28道纯文字验证记录；其中“不使用OCR”“仅牛题库验证”和旧参数knowledges[0]不适用于新版。新版普通OCR试采单列，当前实际参数为knowledges=11568。

# EduMathBench 纯程序自动采集

默认流程：读取筛选配置 → 请求列表及真实下一页链接 → 四站HTML规则解析 → 结构校验 → 自动分流 → 去重 → JSONL/CSV导出。运行阶段不使用大模型、OCR或人工转录台账，不自动补造答案与解析。

## 已完成的真实验证

2026-10-22，HTTP爬虫连续访问牛题库3页，共取得30道候选；自动导出28道文字题及原站文字答案，将2道含输入图片的题目保留到deferred.jsonl。按用户要求仅收集题干、选项和来源答案，解析不在采集范围。21项回归检查通过，离线复现同样得到28道及2道分流记录。

本次全自动联网实跑仅覆盖牛题库。其余三个网站已有适配器和浏览器驱动，但尚未完成独立驱动联网验收，不能把早前通过交互式浏览器保存的样本算入本次全自动成果。以前7道图片答案的目视转录不进入本次数据集。

## 直接运行

解压到任意目录，在解压后的项目根目录打开PowerShell：

```powershell
# 连续分页，最多检查30道候选；无需登录或人工补答案
& './scripts/site_crawler/运行爬虫.ps1' -Mode http -Site tiku -Pages 3 -Limit 30

# 离线复现交付的30道原始候选，自动输出28道文字题
& './scripts/site_crawler/运行爬虫.ps1' -Mode replay

# 四站浏览器模式：默认遇登录/验证就记录并跳过，不停下来要求人工补题
& './scripts/site_crawler/运行爬虫.ps1' -Mode browser -Site all -Limit 3

# 若需要先建立登录状态，由本人在程序的专用Edge窗口完成
& './scripts/site_crawler/运行爬虫.ps1' -Mode browser -Site all -Limit 3 -InteractiveLogin
```

普通电脑安装Python及requirements.txt所列依赖，浏览器模式另需Node、package.json所列依赖和Edge。当前机器已提供所需运行时。HTTP采集及离线复现只需Python和lxml。

```powershell
python -m pip install -r scripts/site_crawler/requirements.txt
# 只有浏览器模式需要：在scripts/site_crawler目录执行npm install
```

首次正常登录属于账户初始化，需要人的操作；建立登录状态后才可能自动复用。不能承诺验证码、登录失效或会员限制也能无人值守解决。程序不绕过这些限制，公开HTTP题源可以避免这一步。

## 自动接收与分流

- questions.jsonl / questions.csv：四选项完整、题干可转换、原站文字答案为A—D的文字题。
- candidates.jsonl：所有实际获取并解析的候选，便于审计被排除的数据。
- deferred.jsonl：图片输入、图片答案、无来源答案、公式待转换等不满足条件的记录，附规则原因。
- duplicates.jsonl：规范化题干与选项内容重复的处置记录。
- raw/：原列表HTML和每题HTML片段；manifest.json用于离线复现。
- events.jsonl：实际请求URL、状态、时间、字节数、SHA-256及异常。
- report.json：候选、接收、分流、去重、来源和解析缺失统计。

Limit是检查的候选题上限，不保证导出相同数量。解析字段为空并标为not_requested，不下载解析图片。原网页作为证据可能包含解析标记。运行入口统一启用--automatic-only；该选项禁止同时传入--transcriptions。Python保留了历史转录审计函数用于旧数据兼容，但默认入口不读取历史台账；即使给自动导出函数传入已转录数据，也会被分流。运行程序本身没有模型API调用。

## 技术实现

| 文件 | 用途 |
|---|---|
| edumath_crawler.py | urllib请求、lxml四站解析、公式转换、规则筛选、去重、导出 |
| browser_crawler.mjs | Playwright动态页面、普通登录状态、详情页和真实分页采集 |
| tasks.json | 知识点路径、题型、来源难度、来源类型和真实筛选URL |
| 运行爬虫.ps1 | 统一入口，默认使用全自动导出规则 |
| ../../tests/test_site_crawler.py | 21项编码、公式、答案、去重和全自动排除规则检查 |

来源参数来自真实筛选页面，每站分别配置：

| 站点 | 有理数加法 | 单选 | 普通/中档 | 期末来源 |
|---|---|---|---|---|
| 二一、出卷 | knowledges[0]=11568 | question_type_ids=1 | difficult_index=3 | question_source=5 |
| 菁优 | q=22119 | ct=1 | dg=13 | so=6 |
| 牛题库 | thirdknowid=701097 | typeid=600012 | diffid=1 | 页面不支持 |

新知识点需要在真实页面核对ID后配置，程序目前未实现知识点树自动遍历。网站来源难度仅作暂定标签。牛题库没有来源筛选且样本未报告原始试卷，不能虚构考试来源。

显式处理UTF-8和GB18030，保留注释尾部题干、上下标、常见MathML及MathJye分式；不支持的公式自动分流。去重比较规范化题干与选项内容，选项重排时核对答案所指的内容。请求有间隔、超时、页数及响应大小限制。

## 本次交付数据

全自动实采与离线复现依据位于data/site_crawl_runs/20261022_fully_automatic_tiku/。另外附带的两份历史HTML仅供回归测试，不计入本次全自动采集成果。

原1800题库未改动。结构检查不等于独立数学正确性复核；网页可变，后续运行数量可能变化。本次未验证样本的公开再分发许可。
