"""Add source-checked text hard questions with full equations and four choices."""
import hashlib,json,re
from datetime import datetime,timezone,timedelta
from pathlib import Path
from check_collection import write_jsonl,source_metadata
from prepare_completion import read
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'data/hard_collection/text_completion'
raw=ROOT/'data/hard_collection/public_pdf/grade78/124522481.pdf'
now=datetime.now(timezone(timedelta(hours=8))).isoformat()
source={'source_id':'SRC-HARD-INEQ-124522481','title':'专题12 解题技巧专题：不等式(组)中含参数问题压轴题五种模型全攻略',
 'url':'https://www.gcyls.cn/file/upload/202405/29/124522481.pdf','year':'unknown','region':'mixed',
 'answer_location':'原PDF每题后的红字来源答案与解析，具体题页及答案页见source_ref',
 'raw_path':raw.relative_to(ROOT).as_posix(),'accessed_at':now,'access_status':'downloaded_public_pdf_and_rendered',
 'reuse_status':'unknown','sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),
 'notes':'公开教学资料二手来源；本批5题由原PDF渲染图转录完整公式与四选项，源答案不改写。均为纯文本题，未将含答案整页图片作为模型输入。'}
rows=[]
for r in read(BASE/'candidates.jsonl'):
 q={'id':'EMB-P-HARD-INEQ-124522481-P'+str(r['source_page']).zfill(2),
    'question':r['question'],**{'option_'+c.lower():r['options'][c] for c in 'ABCD'},'answer':r['answer'],
    'grade':r['grade'],'module':'方程与不等式','knowledge_point':r['knowledge_point'],'difficulty':r['difficulty'],
    'source_exam_grade':8 if '八年级' in r['question'] else (7 if '七年级' in r['question'] else 9),
    'source_id':source['source_id'],'source_ref':f"原PDF第{r['source_page']}页，{r['question_number']}；第{r['answer_page']}页来源答案={r['answer']}",
    'source_type':'public','batch_id':'hard_text_completion_001','status':'collected','input_modality':'text','solution':'',
    'risk_flags':['secondary_source','math_not_reviewed','source_reuse_unknown','provisional_difficulty'],
    'source_question_kind':'public_exam_capstone_text',
    'provenance':{'format':'rendered_pdf_transcription','question_page':r['source_page'],'answer_page':r['answer_page'],
                  'question_number':r['question_number'],'source_pdf_sha256':source['sha256']},
    'difficulty_annotation':{'difficulty':r['difficulty'],'reason':r['reason'],'model':'gpt-6-luna','confidence':'medium',
       'annotated_at':now,'rule_version':'source-hard-v0.1','review_method':'original_pdf_question_options_answer_correspondence','empirical':False},
    'difficulty_evidence':{'kind':'capstone_topic','source_context':source['title'],'source_value':None,'empirical':False}}
 q.update(source_metadata(source));rows.append(q)
write_jsonl(ROOT/'data/batches/hard_text_completion_001/questions.jsonl',rows)
write_jsonl(ROOT/'data/batches/hard_text_completion_001/sources.jsonl',[source])
print(json.dumps({'source_checked_text_hard_questions':len(rows)}))
