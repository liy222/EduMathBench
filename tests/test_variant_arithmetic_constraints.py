import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verify_pilot_variants import calculate,check_spec

class VariantConstraintChecks(unittest.TestCase):
    def test_exact_rationals_and_equivalent_distractors(self):
        self.assertEqual(calculate('1/3+1/6'),calculate('1/2'))
        self.assertTrue(calculate('6/sqrt(3)==2*sqrt(3)'))
        self.assertFalse(calculate('sqrt(3)!=3/sqrt(3)'))
        with self.assertRaisesRegex(ValueError,'equivalent options'):
            check_spec({'kind':'derived_value','derived_expr':'3/2','option_exprs':{'A':'3/2','B':'6/4','C':'2','D':'3'}})
    def test_integer_search_keeps_strict_boundary_and_exclusion(self):
        choices,detail=check_spec({'kind':'finite_integer_search','variable':'n','lower':-5,'upper':8,'predicate_expr':'n>0 and n<5 and n!=2','aggregate':'sum','option_exprs':{'A':'8','B':'10','C':'4','D':'9'}})
        self.assertEqual(choices,['A']);self.assertEqual(detail['solutions'],[1,3,4])
    def test_offset_inequality_not_just_sign_of_factor(self):
        correct,_=check_spec({'kind':'affine_inequality_implication','options':{'A':{'factor':'-3','shift':'4','rhs_shift':'1','relation':'>'},'B':{'factor':'2','shift':'0','rhs_shift':'0','relation':'>'}}})
        self.assertEqual(correct,['B'])
    def test_chain_count_does_not_check_final_result_only(self):
        correct,detail=check_spec({'kind':'equality_chain_count','chains':[['3/4-1/4*2','1/2*2','1'],['-3**2-(-2)**3','-9+8','-1']],'option_exprs':{'A':'0','B':'1','C':'2','D':'3'}})
        self.assertEqual(correct,['B']);self.assertEqual(detail['chain_truth'],[False,True])
    def test_expressions_cannot_access_modules_or_attributes(self):
        for expression in ['__import__(1)','(1).__class__','[n for n in (1,2)]']:
            with self.subTest(expression=expression),self.assertRaises(ValueError):calculate(expression)
    def test_integer_triangle_search_is_complete_and_unique(self):
        correct,detail=check_spec({'kind':'integer_right_triangle_perimeter','perimeter':40,'option_exprs':{'A':'225/4','B':'289/4','C':'81','D':'100'}})
        self.assertEqual(correct,['B']);self.assertEqual(detail['complete_integer_triples'],[(8,15,17)])
    def test_quadratic_vertex_and_endpoint_cases(self):
        correct,_=check_spec({'kind':'quadratic_min_parameter','constant':2,'lower':-2,'upper':3,'minimum':-7,'option_exprs':{'A':'(6,)','B':'(-13/2,)','C':'(-13/2,6)','D':'(-6,6)'}})
        self.assertEqual(correct,['C'])
if __name__=='__main__':unittest.main()
