"""Bounded arithmetic checks, not a general theorem prover or approval gate."""
import ast
import json
import math
import operator
from fractions import Fraction
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Pow:operator.pow,ast.Mod:operator.mod,ast.FloorDiv:operator.floordiv}
CMP={ast.Eq:lambda a,b:equal(a,b),ast.NotEq:lambda a,b:not equal(a,b),ast.Lt:operator.lt,ast.LtE:operator.le,ast.Gt:operator.gt,ast.GtE:operator.ge}
FUNCS={'sqrt':math.sqrt,'abs':abs,'min':min,'max':max,'sum':sum}
def calculate(expr,variables=None):
    if len(expr)>2000: raise ValueError('expression too long')
    tree=ast.parse(expr,mode='eval')
    if sum(1 for _ in ast.walk(tree))>500:raise ValueError('too many nodes')
    def visit(n):
        if isinstance(n,ast.Constant) and isinstance(n.value,(int,float,bool)):
            return n.value if isinstance(n.value,bool) else Fraction(str(n.value))
        if isinstance(n,ast.Name) and n.id in (variables or {}):return variables[n.id]
        if isinstance(n,(ast.List,ast.Tuple)):return tuple(visit(x) for x in n.elts)
        if isinstance(n,ast.UnaryOp):
            v=visit(n.operand)
            if isinstance(n.op,ast.USub):return -v
            if isinstance(n.op,ast.UAdd):return v
            if isinstance(n.op,ast.Not):return not v
        if isinstance(n,ast.BinOp) and type(n.op) in OPS:
            a,b=visit(n.left),visit(n.right)
            if isinstance(n.op,ast.Pow) and abs(b)>100:raise ValueError('power limit')
            return OPS[type(n.op)](a,b)
        if isinstance(n,ast.Compare):
            lhs=visit(n.left)
            for op,r in zip(n.ops,n.comparators):
                rhs=visit(r)
                if not CMP[type(op)](lhs,rhs):return False
                lhs=rhs
            return True
        if isinstance(n,ast.BoolOp):
            values=[visit(v) for v in n.values]
            return all(values) if isinstance(n.op,ast.And) else any(values)
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in FUNCS and not n.keywords:
            return FUNCS[n.func.id](*(visit(a) for a in n.args))
        raise ValueError(f'forbidden expression node {type(n).__name__}')
    return visit(tree.body)

def equal(a,b):
    if isinstance(a,(tuple,list)) or isinstance(b,(tuple,list)):
        return isinstance(a,(tuple,list)) and isinstance(b,(tuple,list)) and len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    if isinstance(a,bool) or isinstance(b,bool):return a==b
    if isinstance(a,float) or isinstance(b,float):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-10)
    return a==b

def increasing_optimum(n,total,k):
    # Strictly increasing integers imply prefix sum <= k*xk-k(k-1)/2,
    # and prefix sum <= total-(n-k)*xk-(n-k)(n-k+1)/2.
    candidates=[]
    upper=max(min(k*t-k*(k-1)//2,total-(n-k)*t-(n-k)*(n-k+1)//2) for t in range(1,total+1))
    def search(seq,left,prefix):
        remain=n-len(seq)
        if remain==0:
            if left==0 and prefix==upper:candidates.append(tuple(seq))
            return
        low=seq[-1]+1 if seq else 1
        hi=(left-remain*(remain-1)//2)//remain
        for x in range(low,hi+1):
            newprefix=prefix+(x if len(seq)<k else 0)
            if len(seq)+1>=k and newprefix!=upper:continue
            if len(seq)+1<k:
                pk=k-len(seq)-1
                minprefix=newprefix+pk*x+pk*(pk+1)//2
                if minprefix>upper:continue
                maxrest=left-x-(remain-1-pk)*(x+pk)-(remain-1-pk)*(remain-pk)//2
                if newprefix+maxrest<upper:continue
            search(seq+[x],left-x,newprefix)
    search([],total,0)
    if not candidates:raise ValueError('prefix upper bound not attainable; proof requires other search')
    span=min(s[-1]-s[0] for s in candidates)
    return upper,span,next(s for s in candidates if s[-1]-s[0]==span),len(candidates)

def check_spec(s):
    kind=s['kind']; detail={}
    options=s.get('option_exprs',{})
    if kind=='derived_value':target=calculate(s['derived_expr'])
    elif kind=='integer_right_triangle_perimeter':
        p=s['perimeter'];triples=[]
        if not isinstance(p,int) or not 0<p<=500:raise ValueError('perimeter search bound')
        for a in range(1,p//3+1):
            for b in range(a,(p-a)//2+1):
                c=p-a-b
                if b<c and a*a+b*b==c*c:triples.append((a,b,c))
        cs={t[2] for t in triples}
        if len(cs)!=1:raise ValueError('circumcircle area not unique')
        target=Fraction(next(iter(cs))**2,4);detail['complete_integer_triples']=triples
    elif kind=='circle_point_position':
        r=Fraction(s['diameter'],2);d=Fraction(s['distance'])
        if not r>0 or d<0:raise ValueError('invalid circle radius/distance')
        truth={'inside':d<r,'on':d==r,'outside':d>r,'center':d==0}
        return [key for key,position in s['option_positions'].items() if truth[position]],{'radius':str(r),'distance':str(d)}
    elif kind=='ordering_values':
        values={k:calculate(v) for k,v in s['values'].items()}
        return [key for key,order in s['option_orders'].items() if all(values[a]<values[b] for a,b in zip(order,order[1:]))],{'computed_values':str(values)}
    elif kind=='quadratic_min_parameter':
        c,lo,hi,m=(Fraction(str(s[k])) for k in ['constant','lower','upper','minimum'])
        if lo>=hi:raise ValueError('invalid closed interval')
        candidates=[]
        if c>=m:candidates.extend([2*math.sqrt(c-m),-2*math.sqrt(c-m)])
        for x in (lo,hi):
            if x:candidates.append((x*x+c-m)/x)
        valid=[]
        for b in candidates:
            x=min(hi,max(lo,b/2));value=x*x-b*x+c
            if equal(value,m) and not any(equal(b,v) for v in valid):valid.append(b)
        target=tuple(sorted(valid));detail['all_case_candidates']=str(candidates)
    elif kind=='inverse_function_forms':
        valid=[]
        for key,form in s['forms'].items():
            if form['type']=='power':ok=form['coefficient']!=0 and form['exponent']==-1
            elif form['type']=='linear_fraction':ok=form['numerator']!=0 and form['x_coefficient']!=0 and form['constant']==0
            else:raise ValueError('unknown algebraic form')
            if ok:valid.append(key)
        return valid,{'criterion':'nonzero constant times x**(-1), over its original domain'}
    elif kind=='statement_selection':
        comparisons={'==':equal,'!=':lambda a,b:not equal(a,b),'<':operator.lt,'<=':operator.le,'>':operator.gt,'>=':operator.ge}
        truth={key:comparisons[t['op']](calculate(t['lhs']),calculate(t['rhs'])) for key,t in s['statements'].items()}
        return [key for key,value in truth.items() if value==s['target_truth']],{'statement_truth':truth}
    elif kind=='maximum_option_value':
        values={k:calculate(v) for k,v in options.items()}
        maximum=max(values.values())
        return [key for key,value in values.items() if equal(value,maximum)],{'option_values':str(values)}
    elif kind=='finite_integer_search':
        if s['upper']-s['lower']>100000:raise ValueError('search too large')
        values=[n for n in range(s['lower'],s['upper']+1) if calculate(s['predicate_expr'],{s['variable']:Fraction(n)})]
        transformed=[calculate(s.get('transform',s['variable']),{s['variable']:Fraction(n)}) for n in values]
        target={'sum':sum,'count':len,'min':min,'max':max}[s['aggregate']](transformed);detail['solutions']=values
        detail['transformed_values']=[str(x) for x in transformed]
    elif kind=='option_sign':
        values={k:calculate(v) for k,v in options.items()}
        pred={'negative':lambda v:v<0,'positive':lambda v:v>0,'zero':lambda v:v==0}[s['target_sign']]
        return [k for k,v in values.items() if pred(v)],{'option_values':str(values)}
    elif kind=='equality_chain_count':
        checks=[all(equal(calculate(c[0]),calculate(e)) for e in c[1:]) for c in s['chains']]
        target=sum(checks);detail['chain_truth']=checks
    elif kind=='statement_count':
        functions={'==':equal,'!=':lambda a,b:not equal(a,b),'<':operator.lt,'<=':operator.le,'>':operator.gt,'>=':operator.ge}
        checks=[functions[x['op']](calculate(x['lhs']),calculate(x['rhs'])) for x in s['statements']]
        target=sum(checks);detail['statement_truth']=checks
    elif kind=='affine_inequality_implication':
        entries=s['options'];good=[]
        for key,v in entries.items():
            factor=calculate(str(v['factor']))
            constant=calculate(str(v.get('shift',0)))-calculate(str(v.get('rhs_shift',v.get('shift',0))))
            positive=factor>=0 and constant>=0 and (factor>0 or constant>0)
            negative=factor<=0 and constant<=0 and (factor<0 or constant<0)
            zero=factor==constant==0
            if (v['relation']=='>' and positive) or (v['relation']=='<' and negative) or (v['relation']=='=' and zero):good.append(key)
        return good,{'principle':'For d=a-b>0, inspect factor*d+left_shift-right_shift over the whole positive half-line'}
    elif kind=='statistical_statement_count':
        rules={'population':('measurement_values',s['population_size']), 'individual':('measurement_value',1),'sample':('measurement_values',s['sample_size']),'sample_size':('count',s['sample_size'])}
        checks=[]
        for statement in s['statements']:
            expected_kind,expected_size=rules[statement['claimed_role']]
            checks.append(statement['object_kind']==expected_kind and statement.get('size',statement.get('value'))==expected_size)
        target=sum(checks);detail['statement_truth']=checks
    elif kind=='increasing_integer_optimization':
        upper,span,witness,count=increasing_optimum(s['count'],s['total'],s['prefix_length'])
        target=span;detail={'max_prefix_sum':upper,'minimum_span':span,'witness':witness,'max_prefix_sequences':count}
    elif kind=='ray_parameter_range':
        p=s['parameters'];boundary=p['other_root_numerator']/p['ray_min_x']
        expected=[['negative',boundary,True],['positive',0,False]]
        return [k for k,v in s['option_ranges'].items() if equal(v,expected)],{'negative_boundary':boundary,'proof':'x=0 and numerator/a must be in ray x>=min; a!=0, numerator positive'}
    else:raise ValueError('unsupported kind '+kind)
    values={k:calculate(v) for k,v in options.items()}
    # Equivalent options are a separate defect even if not correct.
    duplicates=[(a,b) for a in values for b in values if a<b and equal(values[a],values[b])]
    if duplicates:raise ValueError('equivalent options '+str(duplicates))
    detail['computed_value']=str(target)
    return [k for k,v in values.items() if equal(v,target)],detail

def main():
    parents={q['id']:q for q in map(json.loads,(ROOT/'data/variants/parents/parents_300.jsonl').read_text(encoding='utf-8').splitlines())}
    allq=[]
    for grade in (7,8,9):allq.extend(json.loads(s) for s in (ROOT/f'data/variants/pilot/g{grade}.jsonl').read_text(encoding='utf-8').splitlines())
    results=[];seen=set()
    for q in allq:
        errors=[];detail={}
        try:
            assert q['id'] not in seen,'duplicate id';seen.add(q['id'])
            p=parents[q['parent_id']]
            assert q['family_id']==p['family_id'],'family mismatch'
            assert int(q['grade'])==int(p['grade']) and q['module']==p['module'],'classification mismatch'
            assert q['source_type']=='variant' and q['status']=='variant_draft_pending_review','status mismatch'
            assert set(q['options'])==set('ABCD') and all(q['options'].values()),'options missing'
            assert q['question']!=p['question'] and q['change_description'] and q['solution'],'missing meaningful-change evidence'
            for field in [q['question'],*q['options'].values(),q['solution']]:
                assert not any(ord(c)<32 and c not in '\n\t\r' for c in field),'unexpected control character'
            matches,detail=check_spec(q['verification_spec'])
            assert matches==[q['answer']],f'correct options {matches}, stored answer {q["answer"]}'
        except (AssertionError,ValueError,KeyError,TypeError,ZeroDivisionError) as e:errors.append(str(e))
        results.append({'id':q['id'],'passed':not errors,'errors':errors,'kind':q.get('verification_spec',{}).get('kind'),'detail':detail})
    report={'scope':'Structure and explicit arithmetic constraints; derivations and mapping from prose require independent review. Not final mathematical approval.','count':len(allq),'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),'grades':dict(Counter(str(q['grade']) for q in allq)),'difficulty':dict(Counter(q['difficulty'] for q in allq)),'results':results}
    path=ROOT/'data/reports/variant_pilot_check.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))
    for r in results:
        if r['errors']:print(r['id'],r['errors'])
    return report

if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    main()
