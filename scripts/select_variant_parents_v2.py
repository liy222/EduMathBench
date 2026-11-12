"""Exact parent quotas for regeneration; no cross-difficulty fallback."""
import json,copy,hashlib
from collections import Counter
import rebuild_web_benchmark as r

REV=r.OUT/'variants/regeneration_v2'
# Generation-stage suitability choices by the assistant, without changing any
# original difficulty label or pretending this is an independent math review.
HARD_POOL_INDICES=[58,79,80,88,89,90,91,92,93,94,95,96,
 101,103,114,118,119,120,
 121,122,123,124,125,134,135,136,137,138,139,142,156,158,160,162,163,171,175,177,199,203,210,213,214,216,
 217,218,221,226,227,228,229,231,233,
 245,257,258,259,264,286,289]
# Global difficulty is 120/120/60. Per-cell hard targets from the old template
# were infeasible (e.g. no hard originals in grade-eight functions/algebra).
CELLS=[(7,'几何',8,12,0),(7,'数与式',20,19,1),(7,'方程与不等式',15,13,2),(7,'统计与概率',7,3,0),
 (8,'几何',8,10,2),(8,'函数',11,9,0),(8,'数与式',8,12,0),(8,'方程与不等式',12,11,7),(8,'统计与概率',5,5,0),
 (9,'几何',12,12,6),(9,'函数',7,7,26),(9,'方程与不等式',1,0,9),(9,'统计与概率',6,7,7)]

def main():
    rows=r.read(r.OUT/'public/questions.jsonl');cfg=json.loads((r.OUT/'rebuild_config.json').read_text(encoding='utf-8'))
    protected={q['family_id'] for q in rows if q['id'] in cfg['protected_dev_ids']}
    unsuitable={'EMB-P-WEB2-TIKU-2003992','EMB-P-WEB2-TIKU-1855917','EMB-P-WEB2-TIKU-1754084'}
    hard_pool={q['hard_pool_index']:q for q in r.read(r.OUT/'variants/hard_parent_pool.jsonl')}
    byid={q['id']:q for q in rows};selected=[];used=set()
    for index in HARD_POOL_INDICES:
        q=copy.deepcopy(byid[hard_pool[index]['id']]);assert q['difficulty']=='困难'
        assert q['family_id'] not in protected|used and q['id'] not in unsuitable,(index,q['id'])
        q['parent_suitability']={'stage':'variant_generation','selected_by':'current_assistant','basis':'保留来源困难标签；按题干可改编的条件、分类讨论或综合推理选择，生成时再核对推理层次。','formal_review_completed':False}
        selected.append(q);used.add(q['family_id'])
    for grade,module,easy,medium,hard in CELLS:
        assert sum((q['grade'],q['module'])==(grade,module) for q in selected)==hard,(grade,module,hard)
        for difficulty,target in [('基础',easy),('中等',medium)]:
            pool=sorted((q for q in rows if (q['grade'],q['module'],q['difficulty'])==(grade,module,difficulty) and q['id'] not in unsuitable and q['family_id'] not in protected),key=lambda q:(bool(q['image_assets']),len(q['image_assets']),r.rank(q['id'])))
            chosen=[]
            for q in pool:
                if len(chosen)==target:break
                if q['family_id'] in used:continue
                chosen.append(copy.deepcopy(q));used.add(q['family_id'])
            assert len(chosen)==target,('母题不足，停止而不换难度补位',grade,module,difficulty,target,len(chosen))
            selected+=chosen
    selected.sort(key=lambda q:(q['grade'],q['module'],{'基础':0,'中等':1,'困难':2}[q['difficulty']],r.rank(q['id'])))
    for i,q in enumerate(selected,1):q['authoring_index']=i
    assert len(selected)==300 and len({q['family_id'] for q in selected})==300
    assert Counter(q['difficulty'] for q in selected)==Counter({'基础':120,'中等':120,'困难':60})
    r.jsonl(REV/'parents.jsonl',selected)
    r.jsonl(REV/'authoring_input.jsonl',[{k:q[k] for k in ['authoring_index','id','grade','module','knowledge_point','difficulty','question','options','answer','image_assets']} for q in selected])
    report={'revision':'v2_regeneration','parents':300,'difficulty':dict(Counter(q['difficulty'] for q in selected)),'grades':dict(Counter(q['grade'] for q in selected)),
      'image_parents':sum(bool(q['image_assets']) for q in selected),'cross_difficulty_fallback_allowed':False,'protected_development_families_excluded':True,
      'matrix':[dict(grade=g,module=m,基础=e,中等=n,困难=h) for g,m,e,n,h in CELLS],
      'parent_sha256':r.sha(REV/'parents.jsonl'),'source_difficulty_labels_unchanged':True,
      'note':'按全体300道控制难度比例；年级模块总额不变，不强求每个年级或模块都4:4:2。母题来源标签及变式暂定任务难度均非学生实测校准。'}
    r.dump(REV/'selection.json',report);print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
