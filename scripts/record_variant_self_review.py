"""Record the current assistant's explicit per-item re-derivations, not human approval."""
import csv,hashlib,json,shutil
from collections import Counter
import rebuild_web_benchmark as r

FOLDER=r.OUT/'review/assistant_self_check_v2'
REV=r.OUT/'variants/regeneration_v2'
BEFORE=FOLDER/'before'

PATCHES=[
 (15,'question','N在AB上','N在线段AB上','clarification','明确在线段内部范围取点'),
 (66,'question','⑤m≠0','⑤2m>1','clarification','避开不同教材对≠是否计入不等式的口径歧义，答案数量不变'),
 (85,'question','则|a−b|+|b−c|−|a−c|为','则|a−b|+|b−c|−|a−c|恒等于','clarification','强调对全部允许参数均成立，避免将特例相等当作恒等选项'),
 (92,'option_D','抽中的学生如实记录一周睡眠','各班按人数比例随机抽取','clarification','将不属于选样方法的表述改为明确的随机选样方法'),
 (107,'question','下列图形中，一定关于其两条对角线交点中心对称的是','下列图形中，一定是中心对称图形的是','clarification','不为三角形、五边形预设不存在或不唯一的两条对角线交点'),
 (181,'question','则A体积为（ ）','则A体积为（ ）立方厘米','clarification','补全体积答案单位'),
 (182,'question','一批木材总价2760元，每根运费5元。少买一根后，其余木材运费恰等于一根木材单价。原计划买（ ）根。','原计划购买一批单价相同的木材，货款共2760元，每根运费5元。若单价不变且少买一根，其余木材的总运费恰等于一根木材的单价。原计划买（ ）根。','clarification','明确同价、货款不含运费及减购后单价保持不变'),
 (215,'question','D、E分别在射线BA、CA上且位于A外侧','在△ABC中，D、E分别在射线BA、CA上且位于A外侧','clarification','明确母几何对象为三角形，排除隐含共线退化'),
 (245,'question','OABC是第一象限中的矩形','矩形OABC位于第一象限及其边界上','clarification','原点和轴上顶点属于象限边界，避免严格开放象限的措辞冲突'),
 (261,'question','某温室一天温度T=','某温室一天的温度T（℃）随时刻t（小时）的关系为T=','clarification','明确自变量和温度单位'),
 (264,'question','A在第二象限','A在第三象限','substantive_condition_error','k>0时xy=k>0，曲线不能进入第二象限；以第三象限满足其余全部条件'),
 (267,'question','小球高度h=40t−5t²，0≤t≤8','小球高度h（米）与时间t（秒）的关系为h=40t−5t²，0≤t≤8','clarification','补全高度与时间单位'),
 (296,'question','独立抛两次，以下面数字a、b组成点(a，b)','独立抛两次，将两次朝下面的数字依次记为a、b，组成点(a，b)','clarification','消除“以下面数字”病句，明确有序取数来自朝下面'),
 (298,'question','每轮抛5枚公平硬币','每轮将5枚公平硬币相互独立地抛出','clarification','明确同轮各硬币独立，支持32个等可能有序结果'),
 (299,'question','每轮独立掷两枚公平硬币','每轮将两枚公平硬币相互独立地掷出，各轮试验也相互独立','clarification','分别明确同轮两币及各轮之间的独立性'),
]

def signature(q):
    return hashlib.sha256(json.dumps({k:q[k] for k in ['id','parent_id','question','options','answer']},ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def main():
    files=sorted((REV/'authored').glob('*.jsonl'));batches={p:r.read(p) for p in files};by={int(q['id'][-3:]):q for qs in batches.values() for q in qs}
    notes={}
    for p in sorted(FOLDER.glob('g*_notes.txt')):
        for line in p.read_text(encoding='utf-8').splitlines():
            i,a,n=line.split('|',2);i=int(i);assert i not in notes and a in 'ABCD' and len(a)==1;notes[i]=(a,n)
    assert set(notes)==set(by)==set(range(1,301))
    if not BEFORE.exists():
        names=['questions.jsonl','variants/questions.jsonl','完整题库浏览.html','人工复核对照.html','reports/final_validation.json','reports/variant_checks.json']+[p.relative_to(r.OUT).as_posix() for p in files]
        manifest=[]
        for name in names:
            source=r.OUT/name;target=BEFORE/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            assert r.sha(source)==r.sha(target);manifest.append({'path':name,'sha256':r.sha(target)})
        r.dump(BEFORE/'snapshot.json',{'created_at':r.site.stamp(),'purpose':'before assistant self-check corrections','files':manifest})
    original={int(q['id'][-3:]):q for q in r.read(BEFORE/'variants/questions.jsonl')}
    changes=[]
    for i,field,old,new,severity,reason in PATCHES:
        q=by[i];value=q['options'][field[-1]] if field.startswith('option_') else q[field]
        assert old in value or new in value,(i,field,'missing expected text')
        changed=value.replace(old,new) if old in value else value
        if field.startswith('option_'):q['options'][field[-1]]=changed
        else:q[field]=changed
        oldvalue=original[i]['options'][field[-1]] if field.startswith('option_') else original[i][field]
        changes.append({'id':q['id'],'field':field,'before':oldvalue,'after':changed,'category':severity,'reason':reason,'answer_before':original[i]['answer'],'answer_after':q['answer']})
        # Keep the literal authoring source consistent for optional offline replay.
        source=r.ROOT/'scripts'/('author_regeneration_g'+str(7 if i<=100 else 8 if i<=200 else 9)+'.py')
        text=source.read_text(encoding='utf-8')
        if old in text:
            assert text.count(old)==1,(i,'source text ambiguous');source.write_text(text.replace(old,new),encoding='utf-8')
    q=by[264]
    spec={'kind':'line_inverse_pair_constraints','slope':'1/2','quadrants':['III','I'],'horizontal_gap':'3','AC_BC_ratio':'2','option_exprs':dict(zip('ABCD',['(1,1/2)','(1/2,1)','(2,1/2)','(1,1)']))}
    q['verification_spec']=spec
    source=r.ROOT/'scripts/author_regeneration_g9.py';text=source.read_text(encoding='utf-8')
    marker="Q(265,"
    inserted="s.rows[-1]['verification_spec']="+repr(spec)+'\n'
    if inserted not in text:source.write_text(text.replace(marker,inserted+marker,1),encoding='utf-8')
    for p,qs in batches.items():r.jsonl(p,qs)
    reviewed_at=r.site.stamp();records=[]
    for i,q in sorted(by.items()):
        answer,note=notes[i];assert answer==q['answer'],(q['id'],'self-rederived answer mismatch',answer,q['answer'])
        records.append({'id':q['id'],'parent_id':q['parent_id'],'reviewer':'current_assistant_same_as_generator','review_type':'assistant_self_check_not_independent_review',
          'reviewed_at':reviewed_at,'status':'self_checked_pending_user_review','rederived_answer':answer,'reasoning':note,
          'reviewed_input_sha256':signature(q),'before_input_sha256':signature(original[i]),'changed_in_self_check':i in {x[0] for x in PATCHES},
          'program_math_kind':q['verification_spec']['kind'],'independent_math_review_completed':False,'human_review_completed':False,
          'scope':['question_conditions_and_feasibility','new_derivation_from_problem_and_options','all_option_meanings_and_unique_choice','domain_and_boundary_cases_if_applicable']})
    r.jsonl(FOLDER/'records.jsonl',records);r.dump(FOLDER/'changes.json',changes)
    with (FOLDER/'逐题自查记录.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['题号','母题','自查答案','本轮改动','自查推导','自查状态','用户复核']);w.writerows([[x['id'],x['parent_id'],x['rederived_answer'],'是' if x['changed_in_self_check'] else '否',x['reasoning'],'助手已自查，非独立复核','待复核'] for x in records])
    report={'reviewed_at':reviewed_at,'count':len(records),'changes':len(changes),'substantive_condition_errors_corrected':sum(x['category']=='substantive_condition_error' for x in changes),
      'clarifications':sum(x['category']=='clarification' for x in changes),'answer_letter_changes':sum(x['answer_before']!=x['answer_after'] for x in changes),
      'previously_unsupported_64_also_self_reviewed':sum(x['program_math_kind']=='manual_review_required' for x in records),
      'reviewer':'current_assistant_same_as_generator','independent_math_review_completed':False,'human_review_completed':False,
      'review_records_sha256':r.sha(FOLDER/'records.jsonl'),'status':'self_check_complete_pending_user_review','authored_files':{p.name:r.sha(p) for p in files}}
    r.dump(FOLDER/'summary.json',report)
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
