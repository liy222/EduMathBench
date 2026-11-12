"""Finish the local release only after version-bound validation evidence passes."""
import json,shutil
from pathlib import Path
from build_reviewed_release import ROOT,OUT,sha,dump

def main():
    load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    m=load(OUT/'manifest.json');s=load(OUT/'statistics.json');v=load(OUT/'reports/release_validation.json');b=load(OUT/'reports/browser_render_check.json');math=load(OUT/'reports/current_variant_math.json');soft=load(OUT/'reports/software_validation.json')
    assert v['passed'] and b['passed'] and v['data_sha256']==b['data_sha256']==math['input_sha256']==sha(OUT/'questions.jsonl')==m['questions_sha256']
    assert soft['data_manifest_sha256']==sha(OUT/'manifest.json') and soft['external_model_requests']==0
    assert math['program_passed']==236 and not math['spec_answer_mismatches'] and not math['check_errors']
    additions=m['source_build']['added_from_existing_crawler_cache'];image_count=s['with_necessary_images']
    text=f'''EduMathBench v0.3 使用说明（更新2026-11-11）

当前1500原题＋300变式，七/八/九年级各600题。原题每年级500，知识模块及基础600/中等600/困难300配额满足；变式每年级100，模块配额满足，实际难度120/121/59，不强改标签凑数。
成员复核按用户确认的六份提交接收，不新增人工复核任务。保留{s['review_basis']['member_reviewed_user_confirmed']}条成员版本，从旧爬虫缓存补入{additions}题，另3道变式由助手针对知识范围/题族实际重写并程序验算。三类工作分别记录，不冒称新版本又经成员批准。缓存题完成程序源材料检查，不冒称成员逐题求解。替换原因与原记录见history/。

主要文件
questions.jsonl：完整通用题库。questions.csv：兼容CSV，每行record_json可完整还原。
inputs/debug_inputs.jsonl、dev_inputs.jsonl、test_inputs.jsonl、all_inputs.jsonl：无答案模型输入；元数据用于分组，实际请求只发送题干、四选项和必要图。
answers/：独立答案表。splits/：集合题号。
assets/input/：必要原图，按内容摘要命名；{image_count}题依赖原图，整题审核截图不进入评测输入。
完整题库浏览.html：双击本地打开，资源离线内嵌。
history/：移出、替换、修订和缓存来源。
reports/：来源/配额/分集/图像/离线复现/数学规格/浏览器/软件验证记录。

编号
id为稳定题号。已有review_no保留原全局复核编号，补入题从1801起分配新号，绝不复用移出题身份。display_no为本版连续1—1800展示编号；跨版本请用id、review_no和版本共同定位。

分集
开发150全原题、每年级50；测试1650=1350原题+300变式；debug100来自开发。300个不同母题及变式族均在测试侧，历史受保护开发31和调试20保留，已识别近重复不跨集合。

本地程序（项目根目录）
./运行评测流程.ps1 -Action self-test
./运行评测流程.ps1 -Action build
./运行评测流程.ps1 -Action verify
./运行评测流程.ps1 -Action viewer
./运行评测流程.ps1 -Action run -Config config/software_check_debug.json -Output runs/my_software_check
./运行评测流程.ps1 -Action score -Output runs/my_software_check
run加-Resume可续跑，配置与数据必须相同。self-test及software_check均为模拟，不生成模型能力结论。

真实API
首轮固定六家官方接口：DeepSeek-V4.1-Flash、Qwen3.8-Flash、GLM-5.3-Flash、Kimi K3、MiniMax M3.1 Flash、豆包Seed 2.1 Lite。名单见config/evaluation_domestic_six.json。项目根目录.env.local用于本机填写六家Key，统一入口启动时载入环境变量；不把密钥写入模型配置、日志或共享文件。batch-check进行零请求本地检查，batch-run顺序运行和评分，可加-Resume续跑。用户已授权本轮六家合计最多60次、每家10次（含失败重试）。GLM/Kimi/MiniMax强制思考，Kimi/MiniMax温度固定1，参数差异单独记录。详见项目根目录“国产六模型运行说明.txt”；其他候选不进入首轮。
max_requests计入重试与续跑；max_total_tokens仅按已知usage停后续请求，不是硬金额上限。缺图、解析失败、拒答、超时、接口错误、未运行分别统计。纯文字模型跳过图题时明确报告覆盖范围，不能静默漏算或当作答错。

本轮验收
84项相关测试通过；禁网双次重建核心产物一致。1800题在1280/390两种宽度共3600次渲染访问，公式/图片/溢出/筛选检查通过。300变式的236份可执行规格全部通过，64份程序不支持的规格保留成员复核状态，无新增人工待办。
debug100和dev150完成本地模拟验证，续跑零重复请求；模拟验证不发外部请求，也不作为模型成绩。真实API预检另见项目根目录runs/domestic_six_pilot_report.json及同名txt/csv。首轮已完成60次debug侧请求，发现小图尺寸、Kimi限流及MiniMax余额问题；程序修订完成离线检查，未API复测。正式测试集尚未运行。后续草稿上限为0，需新的预算授权。
旧v0.2及原反馈与附件保留。只交付普通文件夹，不生成新压缩包。

2026-11-11开发阶段更新：步骤1补验和步骤2六家dev150运行均已完成，协议已冻结。本轮记账922/1000次，六家各150题，共900份答题记录；6条无有效最终答案的回复按规则计错，正式测试集未运行。最新结果见项目根目录runs/campaign_1000/完成说明.txt、reports/development_report.json和reports/frozen_protocol.json。前述模拟验收记录与后续真实API账目分别保存。
'''
    (OUT/'使用说明.txt').write_text(text,encoding='utf-8-sig')
    entry=ROOT/'可视化/完整题库浏览.html';previous=ROOT/'可视化/完整题库浏览_更新前_20261110.html'
    if entry.exists() and not previous.exists():shutil.copyfile(entry,previous)
    shutil.copyfile(OUT/'完整题库浏览.html',entry)
    report={'version':m['version'],'questions_sha256':m['questions_sha256'],'manifest_sha256':sha(OUT/'manifest.json'),'count':1800,'public':1500,'variants':300,'added_cached':additions,'with_necessary_images':image_count,'data_validation_passed':True,'browser_render_passed':True,'browser_visits':b['render_visits'],'supported_variant_specs_passed':math['program_passed'],'unit_tests_passed':84,'software_validation_only':True,'external_api_requests':0,'formal_test_set_model_runs':0,'main_local_viewer':str(entry),'main_viewer_sha256':sha(entry),'previous_entry_preserved':str(previous),'source_and_feedback_not_overwritten':True}
    dump(OUT/'reports/stage_completion.json',report)
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
