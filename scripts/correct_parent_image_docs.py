"""Correct current claims and preserve the prior finding as an explained error."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def replace(path,old,new):
    p=ROOT/path;t=p.read_text(encoding='utf-8');assert old in t,(path,old);p.write_text(t.replace(old,new),encoding='utf-8')
replace('README.md','剩余270道变式，300候选中的7道缺必要图示题先暂缓或同格替换。','剩余270道变式。此前7道缺图提示已更正：原图均通过image_assets单独关联且文件完整，筛选漏读字段造成误报；300候选实际带图21道。')
replace('docs/next_batches.md','当前剩270道变式，先处理300候选中7道缺必要图示题，再按批扩量','当前剩270道变式，按批扩量前逐题核条件与答案；此前7道缺图提示是漏读image_assets字段造成的误报，原图全部完整')
replace('docs/variant_stage_plan.md','300候选逐格配额已核对，含图母题7道；另17道文字中提到图示却无内嵌图，经初筛10道文字条件充分待数学复核、7道需补图暂缓。','300候选逐格配额已核对，实际含图母题21道、24个原图引用，文件完整。原17道未嵌图提示中13道通过image_assets单独关联原图，4道为文字充分的题；此前7道缺必要图示判断系漏读该字段，已更正并解除限制。')
p=ROOT/'data/reports/variant_stage_progress.md';t=p.read_text(encoding='utf-8')
t=t.replace('含图候选7道','含图候选21道、24个原图引用，文件和SHA-256完整')
t=t.replace('七年级试做母题EMB-P-CMMA-s_04446缺少必要矩形图/坐标，已换成同格同难度的公交相遇母题。缺图原题仍保留公开库来源记录，仅在候选处置中暂停使用。','首批七年级改用同格同难度的纯文字公交相遇题。更正：原矩形母题EMB-P-CMMA-s_04446已有image_assets原图，先前漏读字段导致误报，不是来源缺图；已解除该候选限制，试做题对仍保留。')
t=t.replace('300候选中17道提到图示但没有内嵌图：10道初判文字充分待数学复核，7道需图待补，先暂缓。','原17道题干未嵌图提示中13道已有独立关联原图，4道文字条件充分；之前7道需补图判断全部为误报，已更正。')
t=t.replace('先从同年级、模块、难度候补替换7道缺必要图示候选，或找回原图并补足条件。','原7道缺图提示已经解除，不需要为其重新找图或换题。')
p.write_text(t,encoding='utf-8')
p=ROOT/'scripts/build_variant_pilot_delivery.py';t=p.read_text(encoding='utf-8')
t=t.replace('均为纯文字。后续仍允许含图题。','变式均为纯文字；试做母题有1道附原图但文字条件完整。后续仍允许含图题。')
t=t.replace('查看题对、来源、修改说明和折叠的答案/推导','查看题对、来源、母题原图、修改说明和折叠的答案/推导')
t=t.replace('300候选中缺图提示另附处置清单；仅确认可用的题再扩展。','原7道缺图提示已更正：独立image_assets原图均完整，筛选漏读字段造成误报。300候选实际21道带图、24个图引用；包中原图保留相对路径。')
p.write_text(t,encoding='utf-8')
p=ROOT/'data/variants/parents/audit_selection.py';t=p.read_text(encoding='utf-8')
start=t.index("lines += ['', f'- 含题面图片占位的母题")
end=t.index("lines += ['- 明确排除",start)
new='''lines += ['', f'- 带图母题：{images}道，包括独立image_assets关联；试做母题带图{sum(q["has_image"] for q in pilots)}道，生成的30道变式均为纯文字。', f'- 提到图示而未关联图的候选：{figure_refs}道，均已初判文字条件充分，仍待数学复核。', '- 原报告称7道缺必要图示，经核对均已有image_assets原图，文件和SHA-256完整。漏读字段导致误报；300候选实际带图21道、24个图引用、缺图文件0。', '- 未重绘或修改原图；图文变式仍须同步核对。', '', '## 风险和筛选限制', '', f'- 风险标记次数：{json.dumps(dict(risk),ensure_ascii=False)}。']
lines += ['', '## 图示引用更正', '', '- 原17条提示中13题已有独立关联原图、4题文字条件充分。旧需图待补7题全部为误报，已解除限制；原图存在不等于数学答案已批准。逐题说明见figure_reference_triage.csv。', '- 纠正证据见data/reports/parent_image_metadata_correction.json；源记录、300候选ID和30变式保持不变。', '- 递增整数母题源解析问题另作记录，不将图片误报的解除当作数学审批。']
'''
t=t[:start]+new+t[end:];p.write_text(t,encoding='utf-8')
print('Current documentation and report generator corrected')
p=ROOT/'data/visualization/variant_pairs_template.html';t=p.read_text(encoding='utf-8')
t=t.replace('block(node,q.question);const list=',"block(node,q.question);for(const asset of q.image_data||[]){const img=document.createElement('img');img.src=asset.data_url;img.alt=asset.alt||'原题配图';img.style='max-width:100%;height:auto;display:block;margin:12px 0';node.append(img)}const list=")
p.write_text(t,encoding='utf-8')
p=ROOT/'data/variants/pilot/g7_generation_notes.md'
with p.open('a',encoding='utf-8') as f:f.write('\n\n更正：2026-10-14后续原图核对发现s_04446已有image_assets配图，先前仅看题干和has_image筛选值误认缺图。原图文件完整，已解除母题缺图限制；首批公交替代题仍保留。\n')
