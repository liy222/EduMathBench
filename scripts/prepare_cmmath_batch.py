"""Add reviewed CMMaTH candidates with original question figures and pinned provenance."""
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from check_collection import write_jsonl,source_metadata
from prepare_completion import read
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'data/hard_collection/cmmath_new'
BATCH='hard_cmmath_001';SID='SRC-CMMATH-FULL-001'

def main():
    archive=json.loads((BASE/'image_archive_manifest.json').read_text(encoding='utf-8'))
    data_manifest=json.loads((BASE/'full_metadata_manifest.json').read_text(encoding='utf-8'))
    now=datetime.now(timezone(timedelta(hours=8))).isoformat()
    source={'source_id':SID,'title':'CMMaTH 完整公开数据包 / CMMaTH/cmmath.json',
        'url':archive['archive_url'],'year':'unknown','region':'mixed','source_exam_grade':'mixed',
        'answer_location':'原JSON对应problem_id条目的answer字段，analysis保留于逐题solution',
        'raw_path':data_manifest['path'],'accessed_at':now,'access_status':'downloaded_public_archive_member_crc_verified',
        'reuse_status':'unknown','sha256':data_manifest['sha256'],'revision':archive['revision'],
        'notes':'作者公开中文多模态数学题库的完整23854条记录；本批仅筛初中四选一。题干和源选项不改写，原题图来自同一公开包，解析图不加入输入。来源标签grade_id另存为source_exam_grade；主知识年级和困难标签由项目暂定，不是学生正确率校准。'}
    pool={q['candidate_id']:q for q in read(BASE/'priority_candidates.jsonl')}
    labels={a['candidate_id']:a for p in sorted(BASE.glob('labels_part*.jsonl')) for a in read(p)}
    assets={a['reference']:a for a in read(BASE/'downloaded_images.jsonl')}
    rows=[];held=[]
    for cid,a in labels.items():
        if a.get('difficulty')!='困难':continue
        if a.get('decision')!='eligible' or a.get('visual_checked') is not True:
            held.append({'candidate_id':cid,'reason':a.get('hold_reason','visual check pending')});continue
        c=pool[cid]
        canonical_module={'图形与几何':'几何','统计和概率':'统计与概率','统计与概率综合':'统计与概率'}.get(a['module'],a['module'])
        images=[]
        for index,ref in enumerate(c['image']):
            image=assets[ref]
            images.append({'path':image['path'],'sha256':image['sha256'],'role':'stem',
                'source_url':archive['archive_url'],'source_ref':image['member'],
                'upstream_image_url':c['image_url'][index] if index<len(c['image_url']) else '',
                'alt':'原题配图','contains_answer_or_solution':False})
        row={'id':'EMB-P-CMMA-'+c['problem_id'],'question':c['question'],
             **{'option_'+letter.lower():c['options'][letter] for letter in 'ABCD'},'answer':c['answer'],
             **{key:a[key] for key in ['grade','module','knowledge_point','difficulty']},
             'source_exam_grade':c['source_grade'],'source_id':SID,
             'source_ref':f"CMMaTH/cmmath.json；数组第{c['source_index']+1}条；problem_id={c['problem_id']}；answer字段",
             'source_type':'public','batch_id':BATCH,'status':'collected','input_modality':'text_image',
             'image_assets':images,'solution':c.get('analysis',''),
             'risk_flags':['secondary_source','math_not_reviewed','curriculum_version_unconfirmed','reuse_unknown','provisional_difficulty'],
             'source_question_kind':'dataset_exam_with_original_figures',
             'provenance':{'dataset':'lizhongzhi2022/cmmath','revision':archive['revision'],'archive_member':'CMMaTH/cmmath.json',
                'array_index':c['source_index'],'original_id':c['problem_id'],'local_path':data_manifest['path'],
                'original_question_id':c.get('metadata',{}).get('init_question_id'),
                'upstream_source':c.get('metadata',{}).get('source'),'source_knowledge_point':c['knowledge_point']},
             'difficulty_annotation':{**{k:a[k] for k in ['candidate_id','grade','module','knowledge_point','difficulty','reason','confidence'] if k in a},'source_difficulty':'not_provided','annotated_at':a.get('annotated_at',now),
                'model':a.get('model','gpt-6-luna'),'rule_version':'difficulty-v0.2','empirical':False,
                'review_method':'source_question_four_options_analysis_and_original_figure'},
             'image_review':{'visual_checked':True,'reviewer':a.get('model','gpt-6-luna')}}
        row['module']=canonical_module
        if canonical_module!=a['module']:
            row['label_resolution']={'decision':'normalize_module_name','original_module':a['module'],
                                     'canonical_module':canonical_module,'reason':'对应项目统一的五个知识模块，未改变题意或难度。'}
        row.update(source_metadata(source));rows.append(row)
    write_jsonl(ROOT/'data/batches'/BATCH/'questions.jsonl',rows)
    write_jsonl(ROOT/'data/batches'/BATCH/'sources.jsonl',[source])
    write_jsonl(BASE/'hard_held.jsonl',held)
    print(json.dumps({'reviewed_candidates':len(labels),'hard_ready':len(rows),'hard_held':len(held)}))

if __name__=='__main__':main()
