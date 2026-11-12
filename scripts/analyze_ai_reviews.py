"""Validate and summarize returned AI reviews with Python stdlib; never edit questions."""
import argparse,csv,hashlib,json
from collections import Counter,defaultdict
from pathlib import Path

REQUIRED={'dataset_id','batch_id','review_no','question_id','input_sha256','reviewer','verdict','independent_answer','image_access','issue_types','reason','suggested_fix','confidence'}
VERDICTS={'pending','pass','issue','uncertain','needs_image'}
ISSUES={'condition_incomplete','condition_inconsistent','multiple_correct','no_correct_option','answer_mismatch','formula_or_encoding','option_problem','image_unreadable','grade_module_mismatch','difficulty_questionable','other'}

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_jsonl(path):return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def dump(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def parse_text(text):
    text=text.lstrip('\ufeff').strip();errors=[]
    if text.startswith('```') and text.endswith('```'):
        text='\n'.join(text.splitlines()[1:-1]).strip()
    if not text:return [],[]
    try:
        value=json.loads(text)
        if isinstance(value,dict) and isinstance(value.get('results'),list):value=value['results']
        if isinstance(value,dict):value=[value]
        if not isinstance(value,list):return [],[{'line':1,'error':'Expected JSON object/list or JSONL'}]
        return [(i+1,x) for i,x in enumerate(value)],[]
    except json.JSONDecodeError:pass
    rows=[]
    for i,line in enumerate(text.splitlines(),1):
        if not line.strip():continue
        try:rows.append((i,json.loads(line)))
        except json.JSONDecodeError as e:errors.append({'line':i,'error':str(e)})
    return rows,errors

def validate(record,questions,dataset_id):
    if not isinstance(record,dict):return 'Record is not a JSON object'
    if REQUIRED-set(record):return 'Missing fields: '+','.join(sorted(REQUIRED-set(record)))
    n=record['review_no']
    if type(n) is not int or n not in questions:return 'Unknown or non-integer review_no'
    q=questions[n]
    for key,expected in [('dataset_id',dataset_id),('batch_id',q['batch_id']),('question_id',q['question_id']),('input_sha256',q['input_sha256'])]:
        if record[key]!=expected:return key+' mismatch; wrong question or version'
    v=record['verdict'];answer=record['independent_answer'];access=record['image_access']
    if not isinstance(v,str) or v not in VERDICTS:return 'Invalid verdict'
    if answer is not None and (not isinstance(answer,str) or answer not in ['A','B','C','D']):return 'independent_answer must be one A-D letter or null'
    if not isinstance(access,str) or access not in {'not_needed','viewed','not_viewed'}:return 'Invalid image_access'
    issue_types=record['issue_types']
    if not isinstance(issue_types,list) or any(not isinstance(x,str) or x not in ISSUES for x in issue_types):return 'Invalid issue_types'
    if not isinstance(record['confidence'],str) or record['confidence'] not in {'high','medium','low'}:return 'Invalid confidence'
    for field in ['reviewer','reason','suggested_fix']:
        if not isinstance(record[field],str):return field+' must be a string'
    if v!='pending' and (not record['reviewer'].strip() or not record['reason'].strip()):return 'Completed/attempted reviews need reviewer and actual reasoning'
    if q['requires_image']:
        if access!='viewed' and v not in {'pending','needs_image'}:return 'Necessary image not viewed; cannot claim a mathematical review'
        if access=='not_needed':return 'Image-required question cannot use not_needed'
    elif access!='not_needed' or v=='needs_image':return 'Text question has inconsistent image status'
    if v=='pass' and (answer!=q['provided_answer'] or issue_types):return 'pass contradicts independent answer or issue list'
    if v=='issue' and not issue_types:return 'issue requires at least one concrete issue type'
    if v=='needs_image' and access!='not_viewed':return 'needs_image requires not_viewed'
    return None

def summarize(questions,records):
    grouped=defaultdict(list)
    for x in records:grouped[x['review_no']].append(x)
    issues=[];conflicts=[];unresolved=[];coverage=[]
    for n,q in sorted(questions.items()):
        items=grouped.get(n,[]);answers=sorted({x['independent_answer'] for x in items if x['verdict']!='pending' and x['independent_answer'] is not None})
        verdicts={x['verdict'] for x in items};decided=bool(verdicts & {'pass','issue'})
        conflict=len(answers)>1 or {'pass','issue'}<=verdicts
        row={'复核编号':n,'原始题号':q['question_id'],'批次':q['batch_id'],'题类':q['kind'],'年级':q['grade'],'模块':q['module'],'候选答案':q['provided_answer'],
          '有效返回数':len(items),'复核者':'；'.join(sorted({x['reviewer'] for x in items if x['reviewer']})),'返回判定':'；'.join(sorted(verdicts)),
          '独立答案':'；'.join(answers),'问题类型':'；'.join(sorted({t for x in items for t in x['issue_types']})),
          '理由':'\n'.join(x['reviewer']+'：'+x['reason'] for x in items if x['reason']),
          '修改建议':'\n'.join(x['reviewer']+'：'+x['suggested_fix'] for x in items if x['suggested_fix']),
          '待补原因':'' if decided else ('未收到记录' if not items else '；'.join(sorted(verdicts))),'存在分歧':'是' if conflict else '否'}
        coverage.append(row)
        if 'issue' in verdicts:issues.append(row)
        if conflict:conflicts.append(row)
        if not decided:unresolved.append(row)
    return {'covered_questions':sum(any(x['verdict']!='pending' for x in items) for items in grouped.values()),'questions_with_any_return_including_pending':len(grouped),'decided_questions':len(questions)-len(unresolved),'issue_questions':len(issues),'conflict_questions':len(conflicts),'unresolved_questions':len(unresolved),'verdict_records':dict(Counter(x['verdict'] for x in records))},coverage,issues,conflicts,unresolved

def csv_out(path,rows):
    fields=['复核编号','原始题号','批次','题类','年级','模块','候选答案','有效返回数','复核者','返回判定','独立答案','问题类型','理由','修改建议','待补原因','存在分歧']
    def safe(v):
        # Notes from external AI output are data, not spreadsheet formulas.
        return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:safe(v) for k,v in row.items()} for row in rows)

def analyze(packet,inputs,out):
    packet=Path(packet).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((packet/'manifest.json').read_text(encoding='utf-8'))
    if manifest['status']!='ready_for_ai_review' or sha(packet/'questions.jsonl')!=manifest['questions_sha256']:raise ValueError('Packet input changed or is not ready')
    questions={q['review_no']:q for q in read_jsonl(packet/'questions.jsonl')};dataset_id=manifest['dataset_id']
    if len(questions)!=1800 or set(questions)!=set(range(1,1801)):raise ValueError('Expected the complete versioned 1800-question registry')
    files=set()
    for value in inputs:
        p=Path(value).resolve()
        if p.is_dir():files.update(x for x in p.rglob('*') if x.is_file() and x.suffix.lower() in {'.jsonl','.json'} and out not in x.parents)
        elif p.is_file():files.add(p)
        else:raise FileNotFoundError(p)
    accepted=[];invalid=[];duplicates=[];seen={};received=0
    for path in sorted(files):
        records,errors=parse_text(path.read_text(encoding='utf-8-sig'))
        invalid.extend({'source_file':str(path),**e} for e in errors)
        for line,record in records:
            received+=1;error=validate(record,questions,dataset_id)
            if error:invalid.append({'source_file':str(path),'line':line,'error':error,'record':record});continue
            clean={key:record[key] for key in sorted(REQUIRED)}
            key=hashlib.sha256(json.dumps(clean,ensure_ascii=False,sort_keys=True).encode()).hexdigest();origin={'file':str(path),'line':line}
            if key in seen:
                seen[key]['_sources'].append(origin);duplicates.append(origin|{'review_no':record['review_no']});continue
            clean['_sources']=[origin];seen[key]=clean;accepted.append(clean)
    stats,coverage,issues,conflicts,unresolved=summarize(questions,accepted)
    report={'dataset_id':dataset_id,'source_questions_sha256':manifest['source_questions_sha256'],'input_files':len(files),'received_records':received,'valid_unique_records':len(accepted),'invalid_records_or_lines':len(invalid),'exact_duplicate_records':len(duplicates),**stats,'human_review_completed':False,'canonical_answers_modified':False,'status':'ai_review_evidence_only_pending_independent_resolution'}
    dump(out/'summary.json',report);dump(out/'invalid_records.json',invalid);dump(out/'duplicates.json',duplicates)
    (out/'accepted_reviews.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in accepted),encoding='utf-8')
    for name,rows in [('全部复核覆盖.csv',coverage),('问题清单.csv',issues),('复核分歧.csv',conflicts),('缺失或待补复核.csv',unresolved)]:csv_out(out/name,rows)
    (out/'复核汇总.md').write_text(f'''# AI返回结果汇总

收到{len(files)}个文件、{received}条记录；有效去重后{len(accepted)}条。覆盖{stats['covered_questions']}道，给出pass/issue判定{stats['decided_questions']}道。问题{stats['issue_questions']}道、分歧{stats['conflict_questions']}道、仍缺失或未能判定{stats['unresolved_questions']}道。非法记录/行{len(invalid)}，完全重复{len(duplicates)}条。

请查看问题清单、分歧清单和待补清单；错误版本或缺图却宣称通过等记录在invalid_records.json中。pending空模板不会计为已完成；不同AI的判定不会投票自动改答案。当前仅汇总AI返回证据，人工复核仍未完成，原题库没有修改。
''',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Validate returned JSONL/JSON reviews; no model calls and no canonical edits')
    p.add_argument('inputs',nargs='+');p.add_argument('--packet',default=str(Path(__file__).resolve().parent));p.add_argument('--out',default='analysis');a=p.parse_args();analyze(a.packet,a.inputs,a.out)
