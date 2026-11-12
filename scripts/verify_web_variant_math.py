"""Restricted AST to SymPy; no eval/parse_expr on imported strings."""
import ast,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.runtime_deps'))
import sympy as sp
from verify_pilot_variants import check_spec as legacy,calculate

def expression(text,names=None):
    if len(text)>2000:raise ValueError('表达式过长')
    tree=ast.parse(text,mode='eval');symbols=names or {}
    if sum(1 for _ in ast.walk(tree))>300:raise ValueError('表达式过于复杂')
    def visit(n):
        if isinstance(n,ast.Constant) and isinstance(n.value,(int,float)) and not isinstance(n.value,bool):return sp.Rational(str(n.value))
        if isinstance(n,ast.Name) and n.id in symbols:return symbols[n.id]
        if isinstance(n,(ast.Tuple,ast.List)):return tuple(visit(x) for x in n.elts)
        if isinstance(n,ast.UnaryOp):
            v=visit(n.operand)
            if isinstance(n.op,ast.USub):return -v
            if isinstance(n.op,ast.UAdd):return v
        if isinstance(n,ast.BinOp):
            a,b=visit(n.left),visit(n.right)
            if isinstance(n.op,ast.Add):return a+b
            if isinstance(n.op,ast.Sub):return a-b
            if isinstance(n.op,ast.Mult):return a*b
            if isinstance(n.op,ast.Div):return a/b
            if isinstance(n.op,ast.Pow) and b.is_number and abs(b)<=10:return a**b
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and not n.keywords and n.func.id in {'sqrt','abs'}:
            return {'sqrt':sp.sqrt,'abs':sp.Abs}[n.func.id](*(visit(x) for x in n.args))
        if isinstance(n,ast.Compare):
            funcs={ast.Eq:sp.Eq,ast.NotEq:sp.Ne,ast.Lt:sp.Lt,ast.LtE:sp.Le,ast.Gt:sp.Gt,ast.GtE:sp.Ge}
            values=[visit(n.left)]+[visit(x) for x in n.comparators]
            return sp.And(*(funcs[type(op)](values[i],values[i+1]) for i,op in enumerate(n.ops)))
        if isinstance(n,ast.BoolOp):return (sp.And if isinstance(n.op,ast.And) else sp.Or)(*(visit(x) for x in n.values))
        raise ValueError('不允许的表达式节点：'+type(n).__name__)
    return visit(tree.body)

def check_spec(s):
    kind=s['kind']
    if kind=='draining_tank_affine_domain':
        t=sp.Symbol('t',real=True);initial=expression(s['initial']);rate=expression(s['rate'])
        if initial<=0 or rate<=0:raise ValueError('Tank amount and drain rate must be positive')
        target=initial-rate*t;end=sp.simplify(initial/rate);matches=[]
        for letter,v in s['options'].items():
            candidate=expression(v['expr'],{'t':t})
            if sp.expand(candidate-target)==0 and expression(v['lower'])==0 and expression(v['upper'])==end:matches.append(letter)
        return matches,{'affine_relation':str(target),'physical_domain':'[0, '+str(end)+']','empty_tank_at':str(end),'method':'exact affine identity plus nonnegative time/remaining water constraints'}
    if kind=='line_inverse_pair_constraints':
        x=sp.Symbol('x',real=True);slope=expression(s['slope']);matches=[];evidence={}
        for letter,value in s['option_exprs'].items():
            k,b=expression(value)
            roots=sp.solveset(slope*x*x+b*x-k,x,domain=sp.S.Reals)
            if not isinstance(roots,sp.FiniteSet) or len(roots)!=2 or k<=0:continue
            a,z=sorted(roots);ys=[slope*t+b for t in (a,z)]
            def quadrant(t,y):
                if t==0 or y==0:return 'axis'
                return ('I' if y>0 else 'IV') if t>0 else ('II' if y>0 else 'III')
            quadrants=[quadrant(t,y) for t,y in zip((a,z),ys)]
            ok=quadrants==s['quadrants'] and sp.simplify(z-a-expression(s['horizontal_gap']))==0 and sp.simplify(sp.Abs(a)-expression(s['AC_BC_ratio'])*sp.Abs(z))==0
            evidence[letter]={'roots':[str(a),str(z)],'quadrants':quadrants,'satisfies_all_constraints':bool(ok)}
            if ok:matches.append(letter)
        return matches,{'complete_option_coordinate_checks':evidence,'scope':'solve both intersections, check both quadrants, horizontal gap and collinear segment ratio'}
    if kind=='real_solution_aggregate':
        var=sp.Symbol(s.get('variable','x'),real=True);names={str(var):var}
        roots=sp.solveset(expression(s['lhs'],names)-expression(s.get('rhs','0'),names),var,domain=sp.S.Reals)
        if roots!=sp.S.EmptySet and not isinstance(roots,sp.FiniteSet):raise ValueError('未获得完整有限实数解集')
        roots=[v for v in roots if 'condition' not in s or bool(expression(s['condition'],{str(var):v}))]
        values=[expression(s.get('transform',str(var)),{str(var):v}) for v in roots]
        target={'count':lambda a:sp.Integer(len(a)),'sum':lambda a:sp.Add(*a),'min':min,'max':max}[s['aggregate']](values)
        return [k for k,v in s['option_exprs'].items() if sp.simplify(expression(v)-target)==0],{'complete_real_roots':[str(v) for v in roots],'transformed_values':[str(v) for v in values],'result':str(target)}
    if kind=='quadratic_all_real':
        p=sp.Symbol(s.get('parameter','m'),real=True);names={str(p):p}
        a,b,c=[expression(v,names) for v in s['coefficients']];delta=sp.expand(b*b-4*a*c)
        conditions=[a<0,delta<0] if s['relation']=='negative' else [a>0,delta<=0]
        result=sp.reduce_inequalities(conditions,p).as_set()
        constant=sp.reduce_inequalities([sp.Eq(a,0),sp.Eq(b,0),c<0 if s['relation']=='negative' else c>=0],p).as_set()
        result=sp.Union(result,constant)
        return [k for k,v in s['option_regions'].items() if expression(v,names).as_set()==result],{'parameter_set':str(result),'delta':str(delta),'constant_case':str(constant)}
    if kind=='positive_rational_minimum':
        a,b,c=[expression(s[v]) for v in ['a','b','c']]
        if not (a>0 and b>0):raise ValueError('最小值证明需a、b正数')
        target=c+2*sp.sqrt(a*b);witness=sp.sqrt(b/a)
        return [k for k,v in s['option_exprs'].items() if sp.simplify(expression(v)-target)==0],{'domain':'x>0','minimum':str(target),'attained_at':str(witness),'identity':'a*x+b/x-2*sqrt(a*b)=(sqrt(a)*x-sqrt(b))**2/x'}
    if kind=='parameter_integer_rational':
        p=s['parameter'];x=s.get('variable','x');variable=sp.Symbol(x,real=True);valid=[];evidence=[]
        if s['upper']-s['lower']>1000:raise ValueError('参数枚举超界')
        for v in range(s['lower'],s['upper']+1):
            names={p:sp.Integer(v),x:variable}
            roots=sp.solveset(expression(s['lhs'],names)-expression(s.get('rhs','0'),names),variable,domain=sp.S.Reals)
            if roots!=sp.S.EmptySet and not isinstance(roots,sp.FiniteSet):raise ValueError('参数方程实根集未完整求解')
            kept=[z for z in roots if z.is_integer and ('condition' not in s or bool(expression(s['condition'],{p:sp.Integer(v),x:z})))]
            evidence.append({'parameter':v,'roots':str(roots),'valid_integer_roots':[str(z) for z in kept]})
            if kept:valid.append(v)
        target=sp.Integer(len(valid) if s['aggregate']=='count' else sum(valid))
        return [k for k,v in s['option_exprs'].items() if expression(v)==target],{'parameters':valid,'complete_cases':evidence}
    if kind=='independent_pair_parity':
        import itertools
        cards=s['cards'];pairs=list(itertools.permutations(cards,2));count=sum((sum(a)%2)!=(sum(b)%2) for a in pairs for b in pairs)
        target=sp.Rational(count,len(pairs)**2)
        return [k for k,v in s['option_exprs'].items() if expression(v)==target],{'independent_labeled_outcomes':len(pairs)**2,'favorable':count,'probability':str(target)}
    if kind=='referee_sequence':
        import itertools
        n=s['rounds'];players=s['players'];found=[]
        if n>10:raise ValueError('局数枚举超界')
        for seq in itertools.product(players,repeat=n):
            if any(seq[i]==seq[i+1] for i in range(n-1)):continue
            if any(seq.count(p)!=s['referee_counts'][p] for p in players):continue
            found.append(seq)
        if not found:raise ValueError('比赛约束无解')
        losers={seq[s['game_index']] for seq in found}
        return [k for k,v in s['option_players'].items() if (v in losers and len(losers)==1) or (v=='undetermined' and len(losers)>1)],{'possible_referee_sequences':found,'loser_values':sorted(losers),'reason':'The next round referee lost the current round.'}
    if kind=='help_allocation':
        import itertools
        counts=s['remaining_choices'];budget=s['helps'];cases=[]
        for alloc in itertools.product(range(budget+1),repeat=len(counts)):
            if sum(alloc)!=budget or any(n-a<1 for n,a in zip(counts,alloc)):continue
            chance=sp.prod(sp.Rational(1,n-a) for n,a in zip(counts,alloc));cases.append((alloc,chance))
        best=max(v for a,v in cases);winners=[a for a,v in cases if v==best]
        return [k for k,v in s['option_allocations'].items() if tuple(v) in winners],{'all_feasible_allocations':[{'allocation':a,'pass_probability':str(v)} for a,v in cases],'maximum_probability':str(best)}
    if kind=='race_to_two':
        import itertools
        flips=s['coins'];wins=s['heads_for_A'];outcomes=list(itertools.product([0,1],repeat=flips));p=sp.Rational(sum(sum(v)==wins for v in outcomes),len(outcomes))
        target=sp.expand(p*p+2*p*p*(1-p))
        return [k for k,v in s['option_exprs'].items() if expression(v)==target],{'single_round_A_probability':str(p),'winning_score_sequences':['AA','ABA','BAA'],'race_probability':str(target)}
    if kind=='fair_reward':
        import itertools,math
        n=s['coins'];outcomes=list(itertools.product([0,1],repeat=n));counts=[sum(sum(v) in group for v in outcomes) for group in s['winning_head_counts']]
        if len(counts)!=3 or counts[0]==0:raise ValueError('奖励规则无效')
        right=sp.Rational(counts[1]*s['other_rewards'][0],len(outcomes));last=sp.Rational(counts[2]*s['other_rewards'][1],len(outcomes))
        if right!=last:raise ValueError('其他两方长期平均得分不一致，不能仅调整第一方')
        target=sp.simplify(right/(sp.Rational(counts[0],len(outcomes))))
        return [k for k,v in s['option_exprs'].items() if expression(v)==target],{'outcomes':len(outcomes),'winning_counts':counts,'reward':str(target),'equal_mean_reward':str(right)}
    if kind=='polygon_angle_pairs':
        import itertools
        polygons=s['sides'];pairs=list(itertools.combinations(polygons,2));good=[]
        for a,b in pairs:
            angle_a=sp.Rational(180*(a-2),a);angle_b=sp.Rational(180*(b-2),b)
            solutions=[(i,j) for i in range(1,7) for j in range(1,7) if angle_a*i+angle_b*j==360]
            if solutions:good.append({'sides':[a,b],'angle_count_solutions':solutions})
        target=sp.Rational(len(good),len(pairs))
        return [k for k,v in s['option_exprs'].items() if expression(v)==target],{'all_pairs':pairs,'feasible_pairs':good,'probability':str(target),'scope':'Local 360-degree angle condition explicitly specified in the question, not a general global tiling theorem.'}
    if kind=='real_solution_set':
        var=sp.Symbol(s.get('variable','x'),real=True);names={str(var):var}
        roots=sp.solveset(expression(s['lhs'],names)-expression(s.get('rhs','0'),names),var,domain=sp.S.Reals)
        if roots!=sp.S.EmptySet and not isinstance(roots,sp.FiniteSet):raise ValueError('未获得完整有限实数解集')
        roots=sp.FiniteSet(*(v for v in roots if 'condition' not in s or bool(expression(s['condition'],{str(var):v}))))
        correct=[]
        for k,v in s['option_exprs'].items():
            values=expression(v);values=values if isinstance(values,tuple) else (values,)
            if sp.FiniteSet(*values)==roots:correct.append(k)
        return correct,{'real_roots':str(roots),'method':'complete_real_solveset'}
    if kind=='quadratic_parameter':
        p=sp.Symbol(s.get('parameter','k'),real=True);names={str(p):p}
        a,b,c=[expression(x,names) for x in s['coefficients']];delta=sp.expand(b*b-4*a*c)
        conditions=[sp.Ne(a,0),{'two':delta>0,'one':sp.Eq(delta,0),'none':delta<0}[s['root_count']]]
        result=sp.reduce_inequalities(conditions,p).as_set()
        correct=[k for k,v in s['option_regions'].items() if expression(v,names).as_set()==result]
        return correct,{'parameter_set':str(result),'discriminant':str(delta),'method':'nonzero_leading_coefficient_and_discriminant'}
    if kind=='finite_probability':
        import itertools
        from fractions import Fraction
        from verify_pilot_variants import equal
        values=s['values'];draws=s.get('draws',2)
        if not 1<=draws<=3 or len(values)**draws>10000:raise ValueError('枚举规模超界')
        outcomes=list(itertools.product(range(len(values)),repeat=draws)) if s.get('replacement',True) else list(itertools.permutations(range(len(values)),draws))
        wins=sum(bool(calculate(s['predicate'],dict(zip(['x','y','z'],(values[i] for i in indices))))) for indices in outcomes)
        result=Fraction(wins,len(outcomes))
        return [k for k,v in s['option_exprs'].items() if equal(calculate(v),result)],{'wins':wins,'outcomes':len(outcomes),'probability':str(result),'method':'complete_labeled_outcome_enumeration'}
    if kind=='symbolic_identity':
        variables={v:sp.Symbol(v,real=True) for v in s.get('variables',['x'])}
        target=expression(s['target_expr'],variables);sp.Poly(target,*variables.values())
        correct=[]
        for letter,value in s['option_exprs'].items():
            candidate=expression(value,variables);sp.Poly(candidate,*variables.values())
            if sp.expand(candidate-target)==0:correct.append(letter)
        return correct,{'method':'exact_polynomial_expansion','target_expanded':str(sp.expand(target))}
    if kind=='equation_with_predicate':
        var=sp.Symbol(s.get('variable','x'),real=True);names={str(var):var}
        roots=sp.solveset(expression(s['lhs'],names)-expression(s.get('rhs','0'),names),var,domain=sp.S.Reals)
        if roots!=sp.S.EmptySet and not isinstance(roots,sp.FiniteSet):raise ValueError('解集未被有限求解器完整处理')
        valid=[x for x in roots if 'condition' not in s or bool(expression(s['condition'],{str(var):x}))]
        if len(valid)!=1:raise ValueError('约束后的解不唯一')
        correct=[letter for letter,value in s['option_exprs'].items() if sp.simplify(expression(value)-valid[0])==0]
        return correct,{'all_real_roots':str(roots),'valid_root':str(valid[0]),'method':'real_solveset_and_exact_predicate'}
    if kind=='quadratic_positive_roots_parameter':
        p=sp.Symbol(s.get('parameter','k'),real=True);names={str(p):p}
        a,b,c=[expression(x,names) for x in s['coefficients']];delta=sp.expand(b*b-4*a*c)
        result=sp.reduce_inequalities([sp.Ne(a,0),delta>0,-b/a>0,c/a>0],p).as_set()
        correct=[letter for letter,value in s['option_regions'].items() if expression(value,names).as_set()==result]
        return correct,{'parameter_set':str(result),'discriminant':str(delta),'method':'leading_coefficient_discriminant_vieta_constraints'}
    if kind=='finite_probability_fairness':
        sides=s['die_sides']
        if not 2<=sides<=12:raise ValueError('枚举范围超过已验证界限')
        counts={letter:sum(bool(calculate(predicate,{'x':x,'y':y})) for x in range(1,sides+1) for y in range(1,sides+1)) for letter,predicate in s['option_predicates'].items()}
        return [letter for letter,count in counts.items() if count*2==sides*sides],{'complete_outcomes':sides*sides,'winning_counts':counts}
    return legacy(s)
