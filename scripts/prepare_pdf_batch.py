"""Publish visually checked question-only PDF crops as portable image questions."""
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from check_collection import write_jsonl,source_metadata
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/hard_collection/public_pdf/additional'
BATCH='hard_public_pdf_001'
# Each of these nine crops has been viewed after rendering, including all four options.
REVIEW={
 'pdfcand-0001':(9,'圆的切线与三角形面积最值','将动点连线的截距极值转为过定点到圆的切线，用直角三角形关系计算最大截距，再求三角形面积。'),
 'pdfcand-0002':(9,'中点轨迹与点到圆最远距离','证明AP中点Q的轨迹为半径减半的圆，再用中心连线与半径确定CQ最大值；需先完成轨迹圆心和中心距构造。'),
 'pdfcand-0003':(8,'全等矩形重叠面积的约束最值','从两全等矩形重叠四边形的平行边和等宽约束建立面积表达式，结合重叠区域必须为四边形的边界条件判断最大面积。'),
 'pdfcand-0004':(8,'面积约束下的菱形动点最短路径','由三角形与菱形面积比确定P的轨迹直线，再利用反射最短路径和135度角的长度关系求PC+PD的最小值。'),
 'pdfcand-0005':(8,'等腰三角形中的双动点最短路径','利用等腰三角形对称性把折线路径BE+EF转成到直线的距离，再构造直角三角形计算长度，需要协调两个动点。'),
 'pdfcand-0006':(8,'直角三角形中的双动点最短路径','先利用对称转化动点D处的折线路径，再选择到BC的垂线实现最短距离，用直角三角形边长约束计算极值。'),
 'pdfcand-0047':(9,'胡不归模型与带权路径最值','把PD的一半用30度角对应的垂直距离表示，将带权距离和转化为直线距离，再判断最短路径达到的位置。'),
 'pdfcand-0059':(9,'外作正方形与锐角三角函数综合','由三个外作正方形的边角关系构造相似或旋转对应，再把给定sinBCD转化为所求tanCDB，不能直接套同一三角形公式。'),
 'pdfcand-0060':(9,'风车图形、斜边中点与面积','利用四个全等直角三角形和斜边延长线经过另一斜边中点的条件建立相似比例，将IJ长度转化为原三角形边长后求整体面积。'),
}
rows=[json.loads(s) for s in (BASE/'mcq_image_candidates.jsonl').read_text(encoding='utf-8').splitlines()]
now=datetime.now(timezone(timedelta(hours=8))).isoformat()
sources={};questions=[]
for r in rows:
 if r['candidate_id'] not in REVIEW:continue
 grade,kp,reason=REVIEW[r['candidate_id']]
 sid='SRC-HARD-PDF-'+Path(r['sourcefile']).stem.upper().replace('_','-')
 if sid not in sources:
  sources[sid]={'source_id':sid,'title':r['source_title'],'url':r['source_url'],'year':'unknown','region':'mixed',
    'raw_path':r['source_raw_path'],'answer_location':'原解析PDF每题后的【答案】字段，逐题答案页详见source_ref',
    'accessed_at':now,'access_status':'downloaded_public_pdf','reuse_status':'unknown',
    'notes':'公开教学资料二手来源，保留完整PDF与校验值。原题公式在PDF文字提取时丢失，使用核对过的原题裁图，图片包含题干与原四选项且止于印刷答案之前。'}
 qid='EMB-P-PDF-'+Path(r['sourcefile']).stem.upper().replace('_','-')+'-P'+str(r['question_start_page'])+'-Q'+r['qnumber']
 q={'id':qid,'question':'请根据以下原题图片作答。<ImageHere>',
    **{'option_'+c.lower():'原题图片中标记为 '+c+' 的选项' for c in 'ABCD'},
    'answer':r['source_answer'],'grade':grade,'module':'几何','knowledge_point':kp,'difficulty':'困难',
    'source_exam_grade':9,'source_id':sid,
    'source_ref':f"原PDF第{r['question_start_page']}页第{r['qnumber']}题；第{r['answer_page']}页【答案】={r['source_answer']}",
    'source_type':'public','status':'collected','batch_id':BATCH,'input_modality':'text_image','solution':'',
    'risk_flags':['secondary_source','math_not_reviewed','reuse_unknown','provisional_difficulty'],
    'image_assets':[{'path':r['image_path'],'role':'stem','sha256':r['sha256'],'source_url':r['source_url'],
      'source_ref':f"PDF第{r['question_start_page']}页，第{r['qnumber']}题至【答案】之前的裁图",
      'alt':'原题完整题干、数学表达式、配图及A至D四个选项','contains_answer_or_solution':False,
      'content_scope':'question_and_four_options','crop_boxes':r['crop_boxes']}],
    'provenance':{'format':'pdf_question_crop','original_question_number':r['qnumber'],
      'question_start_page':r['question_start_page'],'answer_page':r['answer_page'],'crop_boxes':r['crop_boxes'],
      'source_text_extraction':r['question_text_extracted'],'source_text_extraction_status':'incomplete_math_symbols_not_model_input'},
    'difficulty_annotation':{'difficulty':'困难','reason':reason,'model':'primary_agent','confidence':'medium',
      'annotated_at':now,'rule_version':'source-hard-image-v0.1','review_method':'rendered_original_question_and_source_answer_boundary_check','empirical':False},
    'difficulty_evidence':{'kind':'capstone_topic','source_value':None,'source_context':r['source_title'],
                           'item_evidence':r['difficulty_evidence'],'empirical':False},
    'image_review':{'visual_checked':True,'reviewer':'primary_agent','contains_printed_answer':False}}
 q.update(source_metadata(sources[sid]));questions.append(q)
write_jsonl(ROOT/'data/batches'/BATCH/'questions.jsonl',questions)
write_jsonl(ROOT/'data/batches'/BATCH/'sources.jsonl',list(sources.values()))
print(json.dumps({'image_questions':len(questions),'source_pdfs':len(sources)}))
