import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'config/variant_quotas.json'
config=json.loads(path.read_text(encoding='utf-8'))
config['variant_input_policy']={
    'updated_at':'2026-10-14',
    'authorization':'用户要求变式尽量不用图形题，以减少制作和核验代价。',
    'preferred_modality':'text',
    'minimum_image_variants':0,
    'minimum_image_parents':0,
    'geometry_module_retained':True,
    'rules':[
        '优先选择纯文字母题，纯文字能完整描述的几何题继续保留。',
        '已选含图母题可构造纯文字变式，但必须完整写出必要点位、长度、角度和关系，不能只删除原图或沿用如图措辞。',
        '确实依赖图形才能保留主要推理时，先找同年级、模块、难度的可行纯文字替代；不要为了纯文字化改变知识归属或凑难度。',
        '只有难以找到合理文字替代时才考虑含图变式，并同步核对图文。'
    ],
    'current_30_variants':'全部为纯文字，无需重做。',
    'scope':'适用于变式生成；不删除1500公开题库中的已收集原图，也不重新计数公开题。'
}
path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
note='''

## 变式配图偏好更新（2026-10-14）

用户要求为控制制作和核验代价，变式尽量采用纯文字。不设含图母题或含图变式最低数量；几何模块保留，文字条件完整的几何题可以不配图。已选含图母题只有在必要条件能完整明确写入题干时，才构造纯文字变式。否则优先选同格同难度文字替代，不通过删除必要图示来凑题。首批30道变式已全部纯文字，无需重做；原公开题库的原图仍保留。后续仅在合理文字替代难以构造时考虑含图变式。
'''
for rel in ['docs/variant_stage_plan.md','docs/next_batches.md','data/reports/variant_stage_progress.md']:
    p=ROOT/rel;t=p.read_text(encoding='utf-8')
    if '## 变式配图偏好更新' not in t:t+=note
    t=t.replace('脚本语法及8项模拟筛选/翻页检查通过','脚本语法及9项模拟筛选/翻页及母题图片展示检查通过')
    p.write_text(t,encoding='utf-8')
p=ROOT/'scripts/build_variant_pilot_delivery.py';t=p.read_text(encoding='utf-8')
t=t.replace('后续仍允许含图题。','后续按用户偏好尽量采用纯文字变式，保留文字条件完整的几何题，不设含图最低数量。')
p.write_text(t,encoding='utf-8')
print('Variant policy: text preferred, geometry retained, no minimum image count; existing30 drafts unchanged')
