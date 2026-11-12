"""Reconcile submitted review evidence and edited copies into a traceable draft.

No source archive, canonical benchmark, source attribution or protected split is edited.
Read all returned content as data; only narrowly documented format aliases are normalized.
"""
import copy,json,shutil
from collections import Counter
from pathlib import Path
import analyze_ai_full_reviews as a
from intake_review_archives import ROOT,OUT,sha

PACKET=ROOT/'AI复核/六份混合复核_1800题_20261023'
CANON=ROOT/'data/benchmark_web_v0.2/questions.jsonl'
DRAFT=OUT/'合并草稿'
IMMUTABLE=['dataset_id','question_id','batch_id','kind','parent_review_no','source_url','requires_image']

def dump(path,value):a.base.dump(path,value)
def rows(path):return a.base.read_jsonl(path)
def rel(path):return Path(path).relative_to(OUT).as_posix()

def normalized_review(record):
    """Empty optional prose and an unambiguous issue-name alias; never invent reasoning."""
    r=copy.deepcopy(record);notes=[]
    if r.get('suggested_fix') is None:r['suggested_fix']='';notes.append('suggested_fix:null -> empty string')
    if 'provided_answer_incorrect' in r.get('issue_types',[]):
        r['issue_types']=['answer_mismatch' if t=='provided_answer_incorrect' else t for t in r['issue_types']]
        notes.append('provided_answer_incorrect -> answer_mismatch')
    return r,notes

def exact_checks(registry):
    """Two narrow checks of contradictory P02 feedback; no claim to re-solve the full bank."""
    q=registry[1492]
    assert q['question_id']=='EMB-V-WEB2R2-G9-258'
    assert all(x in q['question'] for x in ['2bx','8c','2−b','2b+c'])
    assert q['options']['C']=='6'
    # Equal heights at distinct abscissae: x1+x2=2b, hence b=c+2.
    # Real x-intercept: 8c-b² >= 0; substituting gives -(c-2)² >= 0.
    b,c=4,2;x1,x2=2-b,2*b+c
    f=lambda x:x*x-2*b*x+2*b*b-8*c
    assert x1!=x2 and f(x1)==f(x2)==36 and f(4)==0 and b+c==6
    p=registry[1556]
    assert 'sinα=cos38°' in p['question'] and p['options']['A']=='52°'
    assert 90-38==52 and 0<52<90
    return [
      {'review_no':1492,'question_id':q['question_id'],'original_answer':'C','checked_answer':'C','feedback_claim':'无满足条件的抛物线','finding':'反馈推导有误，保留原候选答案C。','derivation':'两点横坐标不同且纵坐标相等，得(2-b)+(2b+c)=2b，故b=c+2。与x轴有公共点要求8c-b²≥0，代入得-(c-2)²≥0，故c=2、b=4，b+c=6。抛物线为(x-4)²，A(-2,36)、B(10,36)互异且均在其上。','method':'exact algebra plus integer substitution','scope':'targeted assistant check with executable arithmetic; not human approval'},
      {'review_no':1556,'question_id':p['question_id'],'original_answer':'A','checked_answer':'A','feedback_claim':'独立答案C(38°)，但reason写cos38°=sin52°且revised_question.answer=A。','finding':'反馈答案字段与自身推导矛盾；锐角条件下答案为A(52°)。','derivation':'cos38°=sin(90°-38°)=sin52°，锐角区间正弦严格递增，故α=52°。','method':'complementary-angle identity and exact integer subtraction','scope':'targeted assistant check; not human approval'}]

def main():
    manifest=json.loads((PACKET/'manifest.json').read_text(encoding='utf-8'))
    original_sha=sha(CANON);assert original_sha==manifest['source_questions_sha256'] and sha(PACKET/'questions.jsonl')==manifest['questions_sha256']
    registry={q['review_no']:q for q in rows(PACKET/'questions.jsonl')}
    canonical={q['id']:q for q in rows(CANON)}
    intake=json.loads((OUT/'intake_manifest.json').read_text(encoding='utf-8'))
    for arc in intake['archives']:
        assert sha(arc['archive'])==arc['archive_sha256']
        for file in arc['files']:assert sha(Path(arc['extracted_directory'])/file['path'])==file['sha256']
    DRAFT.mkdir(parents=True,exist_ok=True);(DRAFT/'images').mkdir(exist_ok=True)
    raw=[];compatible=[];normalizations=[];parts=[];merged=[];field_changes=[];reconciliation=[];problems=[];image_records=[];provenance_errors=[]
    checks=exact_checks(registry);check_by={x['review_no']:x for x in checks}
    visual_path=OUT/'替换图片助手查看记录.json'
    visual_checks={x['review_no']:x for x in json.loads(visual_path.read_text(encoding='utf-8'))} if visual_path.exists() else {}
    all_review_numbers=[];all_submitted_numbers=[]
    for part in sorted((OUT/'原始反馈').iterdir()):
        batch=part.name;root_questions=[p for p in part.rglob('questions.jsonl') if '移出题目' not in p.parts]
        assert len(root_questions)==1
        qp=root_questions[0];submitted=rows(qp);edited={q['review_no']:q for q in submitted};assert len(edited)==len(submitted)
        excluded=[]
        for p in part.rglob('questions.jsonl'):
            if '移出题目' in p.parts:excluded.extend(rows(p))
        removed_by={q['review_no']:q for q in excluded};removed=set(removed_by);assert not removed&set(edited)
        review_files=[]
        for p in part.rglob('*.jsonl'):
            rr=rows(p)
            if rr and 'verdict' in rr[0] and rr[0]['verdict']!='pending':review_files.append((p,rr))
        assert len(review_files)==1
        rp,reviews=review_files[0];review_by={x['review_no']:x for x in reviews}
        expected={n for n,q in registry.items() if q['batch_id']==batch}
        assert len(reviews)==len(review_by)==300 and set(review_by)==expected
        assert set(edited)|removed==expected
        all_review_numbers.extend(review_by);all_submitted_numbers.extend(edited);all_submitted_numbers.extend(removed)
        part_error=Counter();part_flags=Counter();part_diffs=0;part_answer=0;part_images=0
        for n in sorted(expected):
            base=registry[n];record=review_by[n]
            assert all(record[k]==base[k] for k in ['dataset_id','batch_id','question_id','input_sha256'])
            raw.append(copy.deepcopy(record)|{'_feedback_file':rel(rp)})
            adjusted,notes=normalized_review(record);compatible.append(adjusted)
            if notes:normalizations.append({'review_no':n,'changes':notes,'original_record_preserved':True})
            error=a.validate(adjusted,registry,manifest['dataset_id'])
            if error:part_error[error]+=1
            origin=a.original(base);flags=[];artifact=edited.get(n);full=copy.deepcopy(origin);chosen='original_input'
            # Edited copies are the latest user submissions; retain divergences explicitly.
            if artifact is not None:
                for key in IMMUTABLE:
                    if artifact.get(key)!=base.get(key):provenance_errors.append({'review_no':n,'field':key,'original':base.get(key),'submitted':artifact.get(key)})
                assert artifact['input_sha256']==base['input_sha256'] or artifact.get('previous_input_sha256')==base['input_sha256']
                afull=a.original(artifact)
                if afull!=origin:full=copy.deepcopy(afull);chosen='submitted_edited_questions'
            if chosen=='original_input' and not error and record['correction_status']=='proposed':
                full=copy.deepcopy(record['revised_question']);chosen='complete_review_proposal'
            if n in removed:
                flags.append('removed_by_submitter');full=copy.deepcopy(origin);full['answer']=None;chosen='excluded_original_preserved'
            else:
                if error:flags.append('review_protocol_inconsistent')
                if not record.get('reason','').strip():flags.append('missing_review_reason')
                if not record.get('reviewer','').strip():flags.append('reviewer_unspecified')
                if base['requires_image'] and record['image_access']!='viewed':flags.append('necessary_image_not_reviewed')
                if record['verdict']=='pass' and record['independent_answer']!=base['provided_answer']:
                    flags.append('independent_answer_conflicts_with_pass');full['answer']=None
                if record['correction_status']=='unresolved' or record['verdict'] in {'uncertain','needs_image'}:
                    if chosen=='submitted_edited_questions':flags.append('later_edit_after_unresolved_review')
                    else:flags.append('unresolved_review');full['answer']=None
                if record.get('image_consistency') in {'needs_redraw','inconsistent'}:flags.append('review_requests_image_correction')
            # Later submitted prose conversions and manual repairs are kept, not silently undone.
            if artifact is not None and chosen=='submitted_edited_questions' and a.original(artifact)!=record['revised_question']:
                flags.append('submitted_edit_differs_from_review_snapshot')
                reconciliation.append({'review_no':n,'question_id':base['question_id'],'batch_id':batch,'selected':'latest_submitted_copy','submitted_full_question':a.original(artifact),'review_snapshot_full_question':record['revised_question'],'changed_fields':[k for k in a.FULL_KEYS if a.original(artifact)[k]!=record['revised_question'].get(k)],'state':'additional_edit_pending_confirmation'})
            image_file=None;image_hash=None;image_changed=False
            if base['requires_image']:
                # References are resolved only inside the received part directory.
                image_source=artifact or removed_by.get(n) or base
                local_path=image_source['image_file']
                local=(qp.parent/local_path).resolve()
                if not local.is_relative_to(part.resolve()):raise ValueError('Image path outside submitted part')
                image_origin='submitted_archive'
                if not local.is_file() and n in removed:
                    # The deleted biology question may have no picture in the active archive.
                    local=(PACKET/base['image_file']).resolve();image_source=base
                    image_origin='original_packet_for_quarantined_question'
                assert local.is_file(),str(local)
                image_hash=sha(local);assert image_hash==image_source['image_sha256']
                target=DRAFT/'images'/f'q{n:04d}.png';shutil.copyfile(local,target);assert sha(target)==image_hash
                image_file=target.relative_to(DRAFT).as_posix();image_changed=image_hash!=base['image_sha256'];part_images+=image_changed
                text_changed=full['question']!=origin['question'] or full['options']!=origin['options']
                if text_changed and not image_changed:flags.append('text_changed_image_consistency_to_check')
                visual=visual_checks.get(n)
                if visual:assert visual['image_sha256']==image_hash
                if image_changed:flags.append('submitted_replacement_image_visual_checked' if visual else 'submitted_replacement_image_pending_check')
                image_records.append({'review_no':n,'image_file':image_file,'sha256':image_hash,'original_sha256':base['image_sha256'],'changed':image_changed,'evidence_source':image_origin,'source_path':str(local),'visually_checked_in_this_import':bool(visual),'visual_check':visual})
            if n in check_by:
                full=copy.deepcopy(origin);full['answer']=check_by[n]['checked_answer'];chosen='original_confirmed_by_targeted_check'
                flags=[f for f in flags if f not in {'unresolved_review','independent_answer_conflicts_with_pass'}]
                flags.append('feedback_error_identified_by_targeted_check')
            changed=[k for k in a.FULL_KEYS if full[k]!=origin[k]]
            if changed:part_diffs+=1
            if full['answer'] is not None and full['answer']!=origin['answer']:part_answer+=1
            for key in sorted(changed):field_changes.append({'review_no':n,'question_id':base['question_id'],'batch_id':batch,'field':key,'before':origin[key],'after':full[key],'selected_from':chosen})
            q=copy.deepcopy(base)
            q.update({k:copy.deepcopy(full[k]) for k in ['question','options','grade','module','difficulty_provisional']})
            q['answer']=full['answer'];q['provided_answer']=full['answer'];q['original_provided_answer']=base['provided_answer']
            q['image_file']=image_file;q['image_sha256']=image_hash
            q['original_review_input_sha256']=base['input_sha256'];q['original_canonical_id']=base['question_id']
            q['original_classification']={k:base[k] for k in ['grade','module','difficulty_provisional']}
            q['original_split']=canonical[base['question_id']]['split']
            q['feedback']={'file':rel(rp),'submitted_questions_file':rel(qp),'reviewer_as_submitted':record['reviewer'],'raw_verdict':record['verdict'],'raw_correction_status':record['correction_status'],'image_access_as_submitted':record['image_access'],'reason':record['reason'],'suggested_fix':record['suggested_fix'],'complete_review_proposal':record['revised_question'],'protocol_error_after_compatible_aliases':error,'compatibility_notes':notes,'selected_content_from':chosen,'flags':flags,'content_changed':bool(changed),'changed_fields':sorted(changed),'image_changed':image_changed}
            q['review_state']='quarantined' if n in removed else 'unresolved' if full['answer'] is None else 'feedback_received_pending_confirmation'
            q['human_approved']=False
            # Give this merged content its own version; never reuse a stale input digest.
            merged.append(q)
            if flags or full['answer'] is None:
                problems.append({'review_no':n,'question_id':base['question_id'],'batch_id':batch,'review_state':q['review_state'],'flags':flags,'answer':full['answer'],'protocol_error':error,'reason':record['reason']})
            part_flags.update(flags)
        parts.append({'batch_id':batch,'received_reviews':300,'submitted_active_questions':len(submitted),'submitted_removed_questions':len(removed),'removed_review_numbers':sorted(removed),'compatible_protocol_valid':300-sum(part_error.values()),'protocol_errors':dict(part_error),'selected_content_changes':part_diffs,'non_null_answer_changes':part_answer,'replacement_images':part_images,'flags':dict(part_flags)})
    assert sorted(all_review_numbers)==sorted(all_submitted_numbers)==list(range(1,1801))
    assert not provenance_errors,provenance_errors
    merged.sort(key=lambda q:q['review_no'])
    dataset='EMB-FEEDBACK1-'+a.digest({'original_dataset':manifest['dataset_id'],'archive_sha256s':[x['archive_sha256'] for x in intake['archives']],'policy':'latest-submitted-edits-or-valid-review-proposals-v1'})[:16]
    for q in merged:
        q['original_dataset_id']=q['dataset_id'];q['dataset_id']=dataset
        payload={k:q[k] for k in ['dataset_id','review_no','question_id','question','options','provided_answer','grade','module','difficulty_provisional','requires_image','image_sha256']}
        q['input_sha256']=a.digest(payload)
    for name,data in [('原始复核记录.jsonl',raw),('兼容字段后的复核记录.jsonl',compatible)]:a.jsonl(OUT/name,data)
    active=[q for q in merged if q['review_state']!='quarantined'];removed_q=[q for q in merged if q['review_state']=='quarantined'];changed_q=[q for q in merged if q['feedback']['content_changed']]
    for name,data in [('questions.jsonl',merged),('未隔离题目_1797题.jsonl',active),('已隔离题目_3题.jsonl',removed_q),('有内容变动的题目.jsonl',changed_q)]:a.jsonl(DRAFT/name,data)
    # A compact full-question format specifically for handing back to other reviewers.
    a.jsonl(DRAFT/'完整题目与复核状态.jsonl',[{k:q[k] for k in ['dataset_id','review_no','question_id','batch_id','kind','question','options','answer','grade','module','difficulty_provisional','parent_review_no','requires_image','image_file','image_sha256','source_url','original_split','review_state','feedback','human_approved']} for q in merged])
    for name,data in [('字段修改明细.json',field_changes),('后续编辑与原复核差异.json',reconciliation),('协议兼容记录.json',normalizations),('图片核对记录.json',image_records),('待处理清单.json',problems),('定点复算记录.json',checks)]:dump(OUT/name,data)
    field_count=dict(Counter(x['field'] for x in field_changes));flags_count=dict(Counter(f for q in merged for f in q['feedback']['flags']))
    report={'dataset_id':dataset,'original_dataset_id':manifest['dataset_id'],'source_questions_sha256':original_sha,'received_reviews':1800,'unique_review_numbers':1800,'missing_review_numbers':[],'strict_protocol_valid_before_compatibility':json.loads((OUT/'原协议校验/summary.json').read_text(encoding='utf-8'))['valid_unique_records'],'compatible_protocol_valid':sum(x['compatible_protocol_valid'] for x in parts),'compatible_adjusted_records':len(normalizations),'merged_full_question_records':1800,'non_quarantined_records':len(active),'quarantined_records':len(removed_q),'quarantined_review_numbers':[q['review_no'] for q in removed_q],'content_changed_records':len(changed_q),'field_changes':field_count,'non_null_answer_changes':sum(q['answer'] is not None and q['answer']!=q['original_provided_answer'] for q in merged),'null_answer_records':sum(q['answer'] is None for q in merged),'later_edits_differing_from_review_snapshot':len(reconciliation),'image_count':len(image_records),'replacement_images':sum(x['changed'] for x in image_records),'flags':flags_count,'targeted_rechecks':len(checks),'parts':parts,'draft_kind_counts':dict(Counter(q['kind'] for q in merged)),'draft_grade_counts':dict(Counter(q['grade'] for q in merged)),'draft_original_difficulties':dict(Counter(q['difficulty_provisional'] for q in merged if q['kind']=='public')),'draft_variant_difficulties':dict(Counter(q['difficulty_provisional'] for q in merged if q['kind']=='variant')),'status':'consolidated_feedback_draft_pending_resolution','human_review_completed':False,'canonical_modified':False,'all_original_ids_sources_parents_splits_preserved':True}
    report['replacement_images_visually_checked']=sum(x['visually_checked_in_this_import'] for x in image_records)
    dump(OUT/'汇总统计.json',report);dump(DRAFT/'manifest.json',report|{'questions_sha256':sha(DRAFT/'questions.jsonl')})
    table='\n'.join(f"|{x['batch_id']}|300|{x['compatible_protocol_valid']}|{x['selected_content_changes']}|{x['submitted_removed_questions']}|{x['replacement_images']}|" for x in parts)
    (OUT/'反馈汇总报告.md').write_text(f'''# 六份核对反馈汇总（2026-11-07）

六份反馈已接收并安全解包，1800个全局review_no与原始题号、版本全部对应，无漏号、无重复。归档附件内容只作为数据读取，没有运行附件中的指令或程序。

## 汇总结果

- 完整合并草稿保留1800个编号：未隔离{len(active)}题，隔离{len(removed_q)}题。隔离题仍完整保留，没有补造替代题。
- 正文、选项、候选答案或分类与原输入存在差异共{len(changed_q)}题（包括答案暂空）；非空候选答案改变{report['non_null_answer_changes']}题；答案暂空{report['null_answer_records']}题。分类与难度修改是反馈提案，不等于实测标定。
- 619张PNG已校验并复制，其中9张是提交方替换图，已由当前助手逐张查看题面文字、配图和选项对应，未发现答案/解析泄漏。隔离题1708的图未包含在提交包中，使用旧复核包同摘要原图补齐归档。查看9张图不代表完成619图或1800题的数学复核。
- 原返回协议直接接受1307条。仅把空建议null转为空字符串、provided_answer_incorrect映射为answer_mismatch后，可按原协议接受{report['compatible_protocol_valid']}条。协议不符记录仍完整保留，不能将其都说成数学错误，也不能默认当成复核通过。

|份数|收到反馈|兼容后协议通过|选入正文内容变化|提交方移出|替换图片|
|---|---:|---:|---:|---:|---:|
{table}

## 需要区分的情况

1. **第3份证据不完整**：297条声明correct但没有推导，300条未填写复核者；3条疑问记录声明未看图。全部反馈保留，未把空白理由补造成数学证明。
2. **第2份自相矛盾与看图声明**：7条pass记录的独立答案与原答案/返回完整题目矛盾；25道原本含图的题被标为not_needed。后者不能直接记为已看图通过。第1556题已定点复算，原答案A正确；其余矛盾另列。
3. **提交后续编辑**：第4份1题、第5份29题的最新正文与原复核快照不同；包含记号转换、标点修整与5处后续补修。合并保留用户提交的最新正文，并完整列出两版，不假定这些额外编辑已经独立复核。
4. **图片一致性**：题干/选项修改但PNG没更新的236条记录，仅标为需要核对图文一致性。它可能只是等价记号变化，也可能涉及条件变化，不能据此直接判为错图。已替换的9张图片也保留新旧摘要、来源和助手逐张查看记录。
5. **定点发现反馈错误**：第1492题原变式答案C(6)成立，反馈错误地认为无解；第1556题α=52°，答案A。推导及可执行算术检查保存在定点复算记录.json。这两项检查不代表重做全库数学复核。

## 隔离的三题

- 253：题干枚举表达式缺失，无法按现有材料完整恢复。
- 1174：依赖的统计表缺失。
- 1708：混入生物学题，内容不属于数学题库。

三题保留原ID、来源和原答案候选。合并草稿的answer置空并明确quarantined。不能把1797题称作已完成原计划的1500原题+300变式正式验收。

## 文件与使用

- 合并草稿/questions.jsonl：1800题、四选项、候选答案、图片、来源、原划分、完整反馈与状态。provided_answer与answer一致；原答案另存original_provided_answer。未解决题的空答案不参与正式评测。
- 合并草稿/完整题目与复核状态.jsonl：便于继续交给其他AI的完整题目集合。
- 合并草稿/未隔离题目_1797题.jsonl：仅去除三道提交方移出题；其中仍可能有未解决反馈，文件名不表示1797题均已通过。
- 合并草稿/已隔离题目_3题.jsonl：三道隔离题全文。
- 字段修改明细.json、后续编辑与原复核差异.json：新旧全文差异与编辑选择依据。
- 待处理清单.json、图片核对记录.json：继续处理的入口。
- 原始反馈/、原始复核记录.jsonl、原协议校验/：完整原始附件及严格格式校验结果。

所有题号、真实来源、母题关系与原开发/测试划分保留；新草稿单独计算版本摘要。新的分类分布尚未重新满足历史配额，不强改标签凑数。原题库未覆盖，当前状态是“反馈已汇总，修订草稿待确认”。AI名称及“人工补修”等身份均仅记录附件自述，不作为独立身份验证或人工批准依据。只交付普通文件夹，不生成压缩包。
''',encoding='utf-8')
    assert sha(CANON)==original_sha and len({q['question_id'] for q in merged})==1800
    print(json.dumps({k:report[k] for k in ['received_reviews','compatible_protocol_valid','merged_full_question_records','non_quarantined_records','quarantined_review_numbers','content_changed_records','non_null_answer_changes','null_answer_records','later_edits_differing_from_review_snapshot','image_count','replacement_images','flags']},ensure_ascii=False))

if __name__=='__main__':main()
