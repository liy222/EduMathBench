"""Validate full-question AI proposals; keep canonical files untouched. Stdlib only."""
import argparse, copy, hashlib, json
from collections import defaultdict
from pathlib import Path
import analyze_ai_reviews as base

FULL_KEYS={'question','options','answer','grade','module','difficulty_provisional'}
REQUIRED=base.REQUIRED|{'revised_question','correction_status','image_consistency'}

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def original(q):
    return {k:copy.deepcopy(q[k]) for k in FULL_KEYS-{'answer'}}|{'answer':q['provided_answer']}

def blank(q):
    return {k:q[k] for k in ['dataset_id','batch_id','review_no','question_id','input_sha256']}|{
        'reviewer':'','verdict':'pending','independent_answer':None,
        'image_access':'not_viewed' if q['requires_image'] else 'not_needed',
        'issue_types':[],'reason':'','suggested_fix':'','confidence':'low',
        'correction_status':'pending','image_consistency':'not_checked' if q['requires_image'] else 'not_applicable',
        'revised_question':original(q)}

def validate(record,questions,dataset_id):
    error=base.validate(record,questions,dataset_id)
    if error:return error
    missing=REQUIRED-set(record)
    if missing:return 'Missing full-return fields: '+','.join(sorted(missing))
    q=questions[record['review_no']];v=record['verdict'];status=record['correction_status'];full=record['revised_question'];img=record['image_consistency']
    if not isinstance(status,str) or status not in {'pending','unchanged','proposed','unresolved'}:return 'Invalid correction_status'
    if not isinstance(img,str) or img not in {'not_applicable','unchanged_ok','needs_redraw','not_checked'}:return 'Invalid image_consistency'
    if not isinstance(full,dict) or set(full)!=FULL_KEYS:return 'revised_question must contain exactly the six full-question fields'
    if not isinstance(full['question'],str) or not full['question'].strip():return 'Full question text is required'
    opts=full['options']
    if not isinstance(opts,dict) or set(opts)!=set('ABCD') or any(not isinstance(s,str) or not s.strip() for s in opts.values()):return 'Exactly four nonempty A-D options required'
    if full['answer'] is not None and (not isinstance(full['answer'],str) or full['answer'] not in 'ABCD' or len(full['answer'])!=1):return 'Full answer must be A-D or null'
    if type(full['grade']) is not int or full['grade'] not in {7,8,9}:return 'Invalid revised grade'
    if full['module'] not in ['数与式','方程与不等式','函数','几何','统计与概率']:return 'Invalid revised module'
    if full['difficulty_provisional'] not in ['基础','中等','困难']:return 'Invalid revised difficulty'
    if not q['requires_image'] and img!='not_applicable':return 'Text question must use not_applicable'
    if q['requires_image'] and img=='not_applicable':return 'Image question cannot use not_applicable'
    if q['requires_image'] and record['image_access']!='viewed' and img!='not_checked':return 'Unseen image consistency cannot be asserted'
    if v=='pending':
        if status!='pending' or full!=original(q):return 'Pending template must retain original full question'
    elif v=='pass':
        if status!='unchanged' or full!=original(q):return 'pass must return the unchanged complete original question'
        if q['requires_image'] and img!='unchanged_ok':return 'Image pass needs unchanged_ok'
    elif v in {'uncertain','needs_image'}:
        if status!='unresolved' or full['answer'] is not None:return 'Unresolved review must use unresolved and null full answer'
        if {k:value for k,value in full.items() if k!='answer'}!={k:value for k,value in original(q).items() if k!='answer'}:return 'Unresolved review must preserve original question/options/labels'
    elif v=='issue':
        if status not in {'proposed','unresolved'}:return 'issue needs proposed or unresolved correction'
        if status=='proposed':
            if full['answer'] is None or full==original(q):return 'Proposed correction needs a complete changed question and answer'
            if q['requires_image'] and img=='not_checked':return 'Proposed image correction needs an explicit image consistency assessment'
        elif full['answer'] is not None or {k:value for k,value in full.items() if k!='answer'}!={k:value for k,value in original(q).items() if k!='answer'}:
            return 'Unresolved issue must preserve original content and use null answer'
    return None

def jsonl(path,rows):
    Path(path).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')

def aggregate(questions,records):
    grouped=defaultdict(list)
    for x in records:grouped[x['review_no']].append(x)
    full_set=[];proposals=[];conflicts=[];changes=[]
    for n,q in sorted(questions.items()):
        items=grouped[n];attempts=[x for x in items if x['verdict']!='pending']
        concrete=[x for x in attempts if x['correction_status'] in {'proposed','unchanged'}]
        signatures={digest(x['revised_question']) for x in concrete}
        answers={x['independent_answer'] for x in attempts if x['independent_answer'] is not None}
        verdicts={x['verdict'] for x in attempts}
        conflict=len(signatures)>1 or len(answers)>1 or {'pass','issue'}<=verdicts
        status='conflict' if conflict else ('missing' if not items else 'pending' if not attempts else 'unresolved')
        revised=original(q);reviewers=sorted({x['reviewer'] for x in attempts})
        if concrete and not conflict:
            revised=copy.deepcopy(concrete[0]['revised_question'])
            status='proposed' if any(x['correction_status']=='proposed' for x in concrete) else 'unchanged_by_ai'
            if any(x['image_consistency']=='needs_redraw' for x in concrete):status='needs_image_redraw'
        elif attempts:revised['answer']=None
        row={k:copy.deepcopy(q[k]) for k in ['dataset_id','batch_id','review_no','question_id','input_sha256','kind','parent_review_no','source_url','requires_image','image_file','image_sha256']}
        row.update({'review_status':status,'revised_question':revised,'reviewers':reviewers,'human_approved':False,'original_provided_answer':q['provided_answer']})
        full_set.append(row)
        if conflict:conflicts.append({'review_no':n,'question_id':q['question_id'],'versions':attempts})
        elif status in {'proposed','needs_image_redraw'}:
            proposals.append(row)
            for field in sorted(FULL_KEYS):
                if original(q)[field]!=revised[field]:changes.append({'review_no':n,'question_id':q['question_id'],'field':field,'before':original(q)[field],'after':revised[field]})
    return full_set,proposals,conflicts,changes

def analyze(packet,inputs,out):
    packet=Path(packet).resolve();out=Path(out).resolve()
    if out==packet or packet in out.parents and out.name in {'parts','returned'}:raise ValueError('Choose a separate analysis output directory')
    manifest=json.loads((packet/'manifest.json').read_text(encoding='utf-8'))
    if manifest['format_version']!='ai-review-full-v2' or manifest['status']!='ready_for_ai_review' or base.sha(packet/'questions.jsonl')!=manifest['questions_sha256']:raise ValueError('Wrong or modified review packet')
    questions={q['review_no']:q for q in base.read_jsonl(packet/'questions.jsonl')}
    if set(questions)!=set(range(1,1801)):raise ValueError('Expected complete 1800-question registry')
    files=set()
    for value in inputs:
        p=Path(value).resolve()
        if p.is_dir():files.update(x for x in p.rglob('*') if x.is_file() and x.suffix.lower() in {'.jsonl','.json'} and out not in x.parents)
        elif p.is_file():files.add(p)
        else:raise FileNotFoundError(p)
    # Guard against an accidental output path that would overwrite any review evidence.
    if any(p==out or out in p.parents for p in files):raise ValueError('Output contains input evidence')
    out.mkdir(parents=True,exist_ok=True)
    accepted=[];invalid=[];duplicates=[];seen={};received=0
    for path in sorted(files):
        rows,errors=base.parse_text(path.read_text(encoding='utf-8-sig'))
        invalid.extend({'source_file':str(path),**e} for e in errors)
        for line,record in rows:
            received+=1;error=validate(record,questions,manifest['dataset_id'])
            if error:invalid.append({'source_file':str(path),'line':line,'error':error,'record':record});continue
            clean={key:record[key] for key in sorted(REQUIRED)};key=digest(clean);origin={'file':str(path),'line':line}
            if key in seen:seen[key]['_sources'].append(origin);duplicates.append(origin|{'review_no':record['review_no']});continue
            clean['_sources']=[origin];seen[key]=clean;accepted.append(clean)
    stats,coverage,issues,_,unresolved=base.summarize(questions,accepted)
    full,proposals,conflicts,changes=aggregate(questions,accepted)
    conflict_n={x['review_no'] for x in conflicts}
    for row in coverage:row['存在分歧']='是' if row['复核编号'] in conflict_n else '否'
    unresolved_n={x['review_no'] for x in full if x['review_status'] in {'missing','pending','unresolved','conflict','needs_image_redraw'}}
    report={'dataset_id':manifest['dataset_id'],'source_questions_sha256':manifest['source_questions_sha256'],'input_files':len(files),'received_records':received,'valid_unique_records':len(accepted),'invalid_records_or_lines':len(invalid),'exact_duplicate_records':len(duplicates),**stats,
        'conflict_questions':len(conflicts),'complete_question_records':len(full),'proposed_corrected_questions':len(proposals),'questions_still_needing_resolution':len(unresolved_n),'human_review_completed':False,'canonical_answers_modified':False}
    for name,value in [('summary.json',report),('invalid_records.json',invalid),('duplicates.json',duplicates),('conflicts.json',conflicts),('field_changes.json',changes)]:base.dump(out/name,value)
    for name,rows in [('accepted_reviews.jsonl',accepted),('reviewed_questions.jsonl',full),('proposed_corrections.jsonl',proposals)]:jsonl(out/name,rows)
    for name,rows in [('全部复核覆盖.csv',coverage),('问题清单.csv',issues),('复核分歧.csv',[x for x in coverage if x['复核编号'] in conflict_n]),('缺失或待补复核.csv',[x for x in coverage if x['复核编号'] in unresolved_n])]:base.csv_out(out/name,rows)
    (out/'使用说明.txt').write_text('reviewed_questions.jsonl包含完整1800题及复核状态；missing/pending尚未复核，其答案仅为原候选值。unresolved/conflict答案为空。proposed_corrections.jsonl仅含无分歧的完整修改提案；needs_image_redraw仍需修图。conflicts.json保留各复核者全文版本，field_changes.json逐字段比较。所有AI结果都是复核证据或提案，未自动写回主库，也不等于人工批准。',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('inputs',nargs='+');p.add_argument('--packet',default=str(Path(__file__).resolve().parent));p.add_argument('--out',default='analysis');a=p.parse_args();analyze(a.packet,a.inputs,a.out)
