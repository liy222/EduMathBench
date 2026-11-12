"""Create ten traceable pilot drafts; public source records remain unchanged."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
parents = [json.loads(s) for s in (ROOT/'data/variants/parents/pilot_parents_g9.jsonl').read_text(encoding='utf-8').splitlines()]
drafts = []
def add(i, question, choices, answer, solution, change, expr, options, reason):
    p = parents[i-1]
    drafts.append(dict(id=f'EMB-V-PILOT-G9-{i:03}', parent_id=p['id'], family_id=p['family_id'], source_type='variant', question=question, options=dict(zip('ABCD', choices)), answer=answer, grade=9, module=p['module'], knowledge_point=p['knowledge_point'], difficulty=p['difficulty'], input_modality='text', image_assets=[], solution=solution, change_description=change, generation_metadata=dict(agent='primary_agent',model='inherited_parent_model',generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')), difficulty_annotation=dict(reason=reason,empirical=False), risk_flags=['variant_draft','math_review_pending'], status='variant_draft_pending_review', verification_spec=dict(kind='derived_value',derived_expr=expr,option_exprs=dict(zip('ABCD',options)),derivation=solution)))

add(1,r'方程 $x^2+6x+2=0$ 的两个根是（ ）',
    [r'$3+\sqrt7,\ 3-\sqrt7$',r'$-3+\sqrt7,\ 3-\sqrt7$',r'$-3+\sqrt7,\ -3-\sqrt7$',r'$-3+\sqrt5,\ -3-\sqrt5$'],'C',
    '配方得(x+3)²=7，因此两根为−3±√7。两根的和为−6，积为2。',
    '一次项系数4改6，常数1改2；仍用配方或求根公式求两个实根。',
    '((-6+sqrt(6**2-4*2))/2,(-6-sqrt(6**2-4*2))/2)',
    ['(3+sqrt(7),3-sqrt(7))','(-3+sqrt(7),3-sqrt(7))','(-3+sqrt(7),-3-sqrt(7))','(-3+sqrt(5),-3-sqrt(5))'],
    '直接配方或套公式，判别式为正；暂定基础。')
add(2,r'抛物线 $y=x^2-16$ 与 $x$ 轴交于 $C,D$ 两点，线段 $CD$ 的长为（ ）',
    ['$4$','$8$','$16$','$32$'],'B','令y=0得x=±4，两交点距离为|4−(−4)|=8。',
    '常数−9改−16，交点和距离随之改变，保留函数与坐标轴交点任务。','abs(sqrt(16)-(-sqrt(16)))',['4','8','16','32'],'求零点后计算距离，暂定基础。')
add(3,r'在原坐标系中，抛物线为 $y=(x-1)^2+2$。将 $x$ 轴向上平移4个单位、$y$ 轴向左平移2个单位，方向和单位长度不变。用 $(X,Y)$ 表示新坐标，则抛物线方程为（ ）',
    [r'$Y=(X-3)^2-2$',r'$Y=(X+1)^2-2$',r'$Y=(X-3)^2+6$',r'$Y=(X+1)^2+6$'],'A',
    '新原点在原坐标系中为(−2,4)，故x=X−2、y=Y+4；代入得Y=(X−3)²−2，即X²−6X+7。',
    '顶点(2,1)改(1,2)，两轴平移量3/1改4/2，明确区分新旧坐标。',
    '(1,-2*(1+2),(1+2)**2+2-4)', ['(1,-6,7)','(1,2,-1)','(1,-6,15)','(1,2,7)'],
    '要区分坐标系平移与图像平移，并完成代换，暂定中等。')
add(4,r'抛物线 $y=x^2+bx+c$ 与 $x$ 轴只有一个交点，且经过不同的两点 $A(m,n)$、$B(m-10,n)$，则 $n$ 等于（ ）',
    ['$10$','$20$','$25$','$100$'],'C','唯一交点说明判别式为0，顶点纵坐标为0。等高的两点横坐标相差10，对称轴是m−5；两点距对称轴均为5，所以n=5²=25。',
    '等高点横坐标差8改10；保留判别式为零与轴对称的组合推理。','(10/2)**2',['10','20','25','100'],'结合一交点与等高点对称，暂定中等。')
add(5,r'点 $A(-2,0)$、$B(0,2)$ 在平面直角坐标系中。抛物线 $y=ax^2-2x+2$（$a\ne0$）与从 $A$ 出发、经过 $B$ 的射线 $AB$ 有两个不同的交点，则 $a$ 的取值范围为（ ）',
    [r'$a\le-\frac32$ 或 $a>0$',r'$a<-\frac32$ 或 $a>0$',r'$a\ge-\frac32$ 且 $a\ne0$',r'$a<0$'],'A',
    '射线方程y=x+2且x≥−2。联立得x(ax−3)=0，两根0和3/a因a≠0而不同。a>0时第二根为正；a<0时要求3/a≥−2，乘负数a须反向，得到a≤−3/2。边界交点A属于射线，应取等号。',
    '射线起点由(−1,0)改(−2,0)，B由(0,1)改(0,2)，抛物线一次项和常数同步改变，保留根位置及参数分类。',
    '(3/(-2),True,0,False)', ['(-3/2,True,0,False)','(-3/2,False,0,False)','(-3/2,True,0,True)','(0,False,0,False)'],
    '须联立、限制射线范围、按参数符号分类并检验端点，暂定困难。')
drafts[-1]['verification_spec']['representation']='(negative_boundary,negative_boundary_included,positive_boundary,zero_included); option C additionally has opposite inequality direction, recorded below'
drafts[-1]['verification_spec']['kind']='ray_parameter_range'
drafts[-1]['verification_spec']['parameters']={'ray_min_x':-2,'other_root_numerator':3}
drafts[-1]['verification_spec']['option_ranges']={'A':[['negative',-1.5,True],['positive',0,False]],'B':[['negative',-1.5,False],['positive',0,False]],'C':[['greater_equal',-1.5,True],['exclude',0,False]],'D':[['negative',0,False]]}
add(6,r'数轴上点 $Q$ 表示实数 $-2$，以 $Q$ 为圆心、半径为4的圆内有点 $P$（不含圆周），点 $P$ 表示实数 $x$，则（ ）',
    [r'$x<-6$ 或 $x>2$',r'$-6\le x\le2$',r'$-6<x<2$',r'$-2<x<4$'],'C','内部要求|x−(−2)|<4，解得−6<x<2，两端点均不含。',
    '圆心5改−2，半径3改4，强调内部不含圆周，保留距离不等式。','(-2-4,-2+4,False,False)', ['(-6,2,True,True,1)','(-6,2,True,True)','(-6,2,False,False)','(-2,4,False,False)'],'利用点与圆位置关系直接列距离范围，暂定基础。')
add(7,r'在非退化三角形 $ABC$ 中，$D,E$ 分别在边 $AB,AC$ 过 $A$ 的反向延长线上，且 $DE\parallel BC$。若 $AD:DB=2:5$，$DE=4$，则 $BC$ 长为（ ）',
    ['$6$','$8$','$10$','$14$'],'A','D、A、B依次共线，DB=DA+AB。令AD=2t、DB=5t，得AB=3t；因平行而△ADE∼△ABC，BC/DE=AB/AD=3/2，故BC=6。',
    'AD:DB由1:4改2:5，DE由2改4，保留反向延长线下的对应边关系。','4*(5-2)/2',['6','8','10','14'],'先辨清延长线的和差，再应用相似，暂定中等。')
add(8,r'等腰三角形的底边长为8，腰长是一元二次方程 $(x-4)(x-6)=0$ 的一个根，则其外接圆半径为（ ）',
    [r'$\frac{8\sqrt5}{5}$',r'$\frac{9\sqrt5}{5}$',r'$\frac{6\sqrt5}{5}$','$6$'],'B','根为4和6。腰4时两腰之和等于底边，不能成三角形，故腰6。高h=√(6²−4²)=2√5，面积Δ=8h/2=8√5。由R=abc/(4Δ)，R=6×6×8/(32√5)=9√5/5。',
    '底边6改8，候选腰长3/5改4/6，保留退化根排除与外接圆半径计算。','6*6*8/(4*(8*sqrt(6**2-(8/2)**2)/2))', ['8*sqrt(5)/5','9*sqrt(5)/5','6*sqrt(5)/5','6'],'须先排除退化根，再结合勾股、面积与外接圆半径，暂定困难。')
add(9,r'从标有 $-2,3,-5,7$ 的四张卡片中等可能地抽出两张（不放回），两数乘积为正数的概率是（ ）',
    [r'$\frac16$',r'$\frac13$',r'$\frac12$',r'$\frac23$'],'B','无序两张共有C(4,2)=6组；两负数或两正数各1组，因此概率为2/6=1/3。',
    '3个数改4个数，增加一个正数并明确不放回；仍按同号数对计数。','(2*(2-1)/2+2*(2-1)/2)/(4*(4-1)/2)',['1/6','1/3','1/2','2/3'],'列举6个等可能数对即可，暂定基础。')
add(10,r'盒中有3个红球和2个黑球，除颜色外完全相同。每次随机摸出一球后放回并搅匀，共摸两次。设 $P_1$ 为两次均为黑球的概率，$P_2$ 为两次恰好一红一黑的概率，则（ ）',
    [r'$P_1=P_2$',r'$P_1=3P_2$',r'$P_2=2P_1$',r'$P_2=3P_1$'],'D','放回保证两次独立。P1=(2/5)²=4/25；一红一黑有红黑、黑红两序，P2=2×(3/5)×(2/5)=12/25。因此P2/P1=3。',
    '红球数2改3，保持黑球2与有放回规则，比较的倍数由2改3。','(2*(3/5)*(2/5))/((2/5)**2)',['1','1/3','2','3'],'有放回并区分两个颜色顺序后比较概率，暂定中等。')
out=ROOT/'data/variants/pilot/g9.jsonl'
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in drafts),encoding='utf-8')
print(f'{len(drafts)} grade-9 pilot drafts written')
