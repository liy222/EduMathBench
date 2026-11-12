import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verify_web_variant_math import expression,check_spec

class MathChecks(unittest.TestCase):
    def test_positive_inverse_cannot_meet_second_quadrant(self):
        spec={'kind':'line_inverse_pair_constraints','slope':'1/2','quadrants':['III','I'],'horizontal_gap':'3','AC_BC_ratio':'2','option_exprs':{'A':'(1,1/2)','B':'(1/2,1)','C':'(2,1/2)','D':'(1,1)'}}
        self.assertEqual(check_spec(spec)[0],['A'])
        spec['quadrants']=['II','I']
        self.assertEqual(check_spec(spec)[0],[])
    def test_ast_disallows_execution(self):
        for value in ["__import__('os').system('bad')","x.__class__","sqrt(4,**{})","2**100000"]:
            with self.assertRaises((ValueError,TypeError,SyntaxError)):expression(value)
    def test_polynomial_identity_not_a_single_point_sample(self):
        matches,_=check_spec({'kind':'symbolic_identity','variables':['x'],'target_expr':'x**2-1','option_exprs':{'A':'(x-1)*(x+1)','B':'x-1','C':'x**2+1','D':'x**2'}})
        self.assertEqual(matches,['A'])
    def test_rational_equation_discards_pole(self):
        matches,_=check_spec({'kind':'equation_with_predicate','variable':'x','lhs':'2/(x-1)','rhs':'3/x','condition':'x!=0 and x!=1','option_exprs':{'A':'1','B':'3','C':'0','D':'-3'}})
        self.assertEqual(matches,['B'])
    def test_degenerate_quadratic_parameter_excluded(self):
        matches,_=check_spec({'kind':'quadratic_parameter','parameter':'k','coefficients':['k','4','-2'],'root_count':'two','option_regions':{'A':'k>-2','B':'k>-2 and k!=0','C':'k>=-2 and k!=0','D':'k<-2'}})
        self.assertEqual(matches,['B'])
    def test_repeated_colors_use_labeled_without_replacement_outcomes(self):
        matches,detail=check_spec({'kind':'finite_probability','values':[0,0,1,1,1],'draws':2,'replacement':False,'predicate':'x!=y','option_exprs':{'A':'3/10','B':'12/25','C':'1/2','D':'3/5'}})
        self.assertEqual(matches,['D']);self.assertEqual(detail['outcomes'],20)
    def test_all_real_roots_retained(self):
        matches,_=check_spec({'kind':'real_solution_set','variable':'x','lhs':'x**2-x-6','option_exprs':{'A':'(3,)','B':'(-2,)','C':'(-2,3)','D':'(2,-3)'}})
        self.assertEqual(matches,['C'])

    def test_empty_real_root_set_counts_as_zero(self):
        matches,detail=check_spec({'kind':'real_solution_aggregate','lhs':'x**2+1','aggregate':'count','option_exprs':{'A':'0','B':'1','C':'2','D':'4'}})
        self.assertEqual(matches,['A']);self.assertEqual(detail['complete_real_roots'],[])

    def test_all_real_negativity_includes_constant_case_but_not_linear(self):
        matches,detail=check_spec({'kind':'quadratic_all_real','parameter':'m','coefficients':['m','0','-1'],'relation':'negative','option_regions':{'A':'m<0','B':'m<=0','C':'m>0','D':'m>=0'}})
        self.assertEqual(matches,['B']);self.assertEqual(detail['constant_case'],'{0}')
        matches,_=check_spec({'kind':'quadratic_all_real','parameter':'m','coefficients':['m','1','-1'],'relation':'negative','option_regions':{'A':'m<0','B':'m<=0','C':'m<-1/4','D':'m<=-1/4'}})
        self.assertEqual(matches,['C'])

    def test_integer_transform_is_not_sum_of_roots(self):
        matches,detail=check_spec({'kind':'finite_integer_search','lower':-3,'upper':5,'variable':'x','predicate_expr':'(x+2)*(x-4)<=0','transform':'x**2','aggregate':'sum','option_exprs':{'A':'7','B':'35','C':'9','D':'14'}})
        self.assertEqual(matches,['B']);self.assertEqual(detail['solutions'],list(range(-2,5)))

    def test_rational_parameters_with_no_real_roots_and_excluded_poles(self):
        matches,detail=check_spec({'kind':'parameter_integer_rational','parameter':'a','variable':'y','lower':-5,'upper':-4,'lhs':'(1-a*y)/(2*y+1)+6/(y-2)-1','condition':'y!=-1/2 and y!=2','aggregate':'sum','option_exprs':{'A':'-5','B':'-4','C':'-9','D':'0'}})
        self.assertEqual(matches,['B']);self.assertEqual(detail['parameters'],[-4])

    def test_fair_coin_race_uses_stopping_paths(self):
        matches,detail=check_spec({'kind':'race_to_two','coins':2,'heads_for_A':2,'option_exprs':{'A':'1/4','B':'5/32','C':'1/16','D':'1/2'}})
        self.assertEqual(matches,['B']);self.assertEqual(detail['winning_score_sequences'],['AA','ABA','BAA'])

    def test_independent_pairs_reset_deck_between_players(self):
        matches,detail=check_spec({'kind':'independent_pair_parity','cards':[1,2,3],'option_exprs':{'A':'4/9','B':'2/3','C':'1/3','D':'1/2'}})
        self.assertEqual(matches,['A']);self.assertEqual(detail['independent_labeled_outcomes'],36)

    def test_all_help_allocations_compared(self):
        matches,detail=check_spec({'kind':'help_allocation','remaining_choices':[3,4,5],'helps':2,'option_allocations':{'A':[2,0,0],'B':[0,2,0],'C':[0,0,2],'D':[1,1,0]}})
        self.assertEqual(matches,['A']);self.assertEqual(len(detail['all_feasible_allocations']),6)

    def test_referee_next_round_loser_and_underdetermined(self):
        options={'A':'甲','B':'乙','C':'丙','D':'undetermined'}
        spec={'kind':'referee_sequence','rounds':7,'players':['甲','乙','丙'],'referee_counts':{'甲':1,'乙':2,'丙':4},'game_index':4,'option_players':options}
        self.assertEqual(check_spec(spec)[0],['C'])
        spec['game_index']=3
        self.assertEqual(check_spec(spec)[0],['D'])

    def test_reward_equalizes_both_other_players(self):
        spec={'kind':'fair_reward','coins':5,'winning_head_counts':[[0,5],[1,4],[2,3]],'other_rewards':[2,1],'option_exprs':{'A':'5','B':'8','C':'10','D':'20'}}
        self.assertEqual(check_spec(spec)[0],['C'])
        spec['other_rewards']=[1,1]
        with self.assertRaises(ValueError):check_spec(spec)

    def test_polygon_must_use_both_types(self):
        matches,detail=check_spec({'kind':'polygon_angle_pairs','sides':[3,4,6,12],'option_exprs':{'A':'1/3','B':'1/2','C':'2/3','D':'1'}})
        self.assertEqual(matches,['B']);self.assertEqual(len(detail['feasible_pairs']),3)

    def test_positive_minimum_requires_positive_coefficients(self):
        spec={'kind':'positive_rational_minimum','a':'5/2','b':'40','c':'20','option_exprs':{'A':'20','B':'30','C':'40','D':'50'}}
        self.assertEqual(check_spec(spec)[0],['C'])
        spec['a']='-1'
        with self.assertRaises(ValueError):check_spec(spec)

if __name__=='__main__':unittest.main()
