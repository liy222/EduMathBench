"""公开预览的题图与题面对应首批，图片不包含来源答案。"""
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/hard_collection/images_round1'
ASSETS=BASE/'assets'
ASSETS.mkdir(parents=True,exist_ok=True)
now=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
source=next(json.loads(s) for s in (ROOT/'data/hard_collection/g9/candidates.jsonl').read_text(encoding='utf-8').splitlines() if 'SUIHUA' in json.loads(s)['id'])
q={k:v for k,v in source.items() if k.startswith('source_')}
q.update({
    'id':'HC-IMG-G9-QINGDAO-2025',
    'question':r'（2025·山东青岛·模拟预测）如图，二次函数 $y=ax^2+bx+c$ 的图象与正比例函数 $y=kx$ 的图象相交于 $A,B$ 两点，已知点 $A$ 的横坐标为 $-3$，点 $B$ 的横坐标为 $2$，二次函数图象的对称轴是直线 $x=-1$。下列结论：① $abc<0$；② $3b+2c>0$；③关于 $x$ 的方程 $ax^2+bx+c=kx$ 的两根为 $x_1=-3,x_2=2$；④ $k=\frac12a$。其中正确的有（ ）',
    'option_a':'1个','option_b':'2个','option_c':'3个','option_d':'4个','answer':'B',
    'grade':9,'source_exam_grade':9,'module':'函数',
    'knowledge_point':'图象系数符号、交点与根系数关系综合',
    'difficulty':'困难','source_type':'public','solution':'',
    'source_ref':'公开原卷预览第2页，题型一变式训练第2题（2025山东青岛模拟预测）',
    'source_answer_location':'公开文字解析题型一变式训练第2题【答案】B，末尾注明正确结论①③共2个',
    'source_image_files':['data/hard_collection/g9/raw/25572206-page2.svg','data/hard_collection/g9/raw/25572206-page2.png'],
    'source_accessed_at':now,'input_modality':'text_image','status':'collected',
    'batch_id':'hard_image_web_001','risk_flags':['secondary_source','provisional_difficulty','source_reuse_unknown','math_not_reviewed'],
    'image_assets':[{
        'id':'HC-IMG-G9-QINGDAO-2025-STEM','path':'data/hard_collection/images_round1/assets/qingdao-2025-stem.png',
        'role':'stem','alt':'原题中的抛物线与正比例函数图象，标注A、B和对称轴。',
        'source_url':'https://preview.21cnjy.com/f2/2026/04/f1/f18770b2d902b7e73c0a64385c636294.svg?v=1777216810',
        'source_ref':'公开原卷预览第2页变式训练2的原图',
        'source_page_path':'data/hard_collection/g9/raw/25572206-page2.png',
        'crop_box':{'left':96,'top':800,'width':242,'height':238},
        'contains_answer_or_solution':False,
    }],
    'difficulty_evidence':{'kind':'capstone_topic','source_label':'选择压轴题','source_value':None,
                           'url':'https://zy.21cnjy.com/25572206','reference':'题型一变式训练2','empirical':False},
    'difficulty_annotation':{
        'difficulty':'困难','reason':'读取原图的开口和截距符号，再将对称轴、直线交点与方程根系数关系联立，判断系数线性组合和参数k关系；包含多个相互联系的命题。',
        'model':'primary_agent','annotated_at':now,'rule_version':'source-hard-image-v0.1',
        'review_method':'public_preview_image_and_text_correspondence','confidence':'medium'},
})
asset=ROOT/q['image_assets'][0]['path']
assert asset.is_file(),'先裁切原题图，不能以整页答案图替代'
q['image_assets'][0]['sha256']=hashlib.sha256(asset.read_bytes()).hexdigest()
(BASE/'function_candidates.jsonl').write_text(json.dumps(q,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps({'collected':1,'image_asset':str(asset)}))
