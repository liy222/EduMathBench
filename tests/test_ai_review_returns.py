import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from analyze_ai_reviews import validate,summarize,parse_text

class ReturnContractTests(unittest.TestCase):
    def setUp(self):
        self.q={1:{'review_no':1,'batch_id':'T001','question_id':'Q1','input_sha256':'hash1','requires_image':False,'provided_answer':'A','kind':'public','grade':7,'module':'数与式'},
                2:{'review_no':2,'batch_id':'V001','question_id':'Q2','input_sha256':'hash2','requires_image':True,'provided_answer':'B','kind':'public','grade':7,'module':'几何'}}
        self.r={'dataset_id':'D','batch_id':'T001','review_no':1,'question_id':'Q1','input_sha256':'hash1','reviewer':'reviewerA','verdict':'pass','independent_answer':'A','image_access':'not_needed','issue_types':[],'reason':'Independent calculation gives A.','suggested_fix':'','confidence':'high'}
    def test_valid_review(self):self.assertIsNone(validate(self.r,self.q,'D'))
    def test_wrong_version_is_not_matched_by_number(self):
        x=copy.deepcopy(self.r);x['input_sha256']='older';self.assertIn('mismatch',validate(x,self.q,'D'))
    def test_boolean_number_rejected(self):
        x=copy.deepcopy(self.r);x['review_no']=True;self.assertIn('non-integer',validate(x,self.q,'D'))
    def test_pass_requires_same_answer_and_no_issues(self):
        x=copy.deepcopy(self.r);x['independent_answer']='B';self.assertIn('contradicts',validate(x,self.q,'D'))
    def test_unseen_image_cannot_be_passed(self):
        x=copy.deepcopy(self.r);x.update(review_no=2,batch_id='V001',question_id='Q2',input_sha256='hash2',independent_answer='B',image_access='not_viewed')
        self.assertIn('not viewed',validate(x,self.q,'D'));x.update(verdict='needs_image',independent_answer=None,reason='Image file was not provided.');self.assertIsNone(validate(x,self.q,'D'))
    def test_pending_template_is_not_completed(self):
        x=copy.deepcopy(self.r);x.update(verdict='pending',reviewer='',reason='',independent_answer=None)
        self.assertIsNone(validate(x,self.q,'D'));stats,*_=summarize(self.q,[x]);self.assertEqual(stats['decided_questions'],0);self.assertEqual(stats['covered_questions'],0);self.assertEqual(stats['unresolved_questions'],2)
    def test_empty_returns_do_not_mutate_coverage(self):
        stats,*_=summarize(self.q,[]);self.assertEqual(stats['covered_questions'],0);self.assertEqual(stats['questions_with_any_return_including_pending'],0);self.assertEqual(stats['unresolved_questions'],2)
    def test_conflicts_not_silently_overwritten(self):
        x=copy.deepcopy(self.r);x.update(reviewer='reviewerB',verdict='issue',independent_answer='C',issue_types=['answer_mismatch'],reason='Derivation gives C.')
        stats,_,issues,conflicts,missing=summarize(self.q,[self.r,x]);self.assertEqual(stats['conflict_questions'],1);self.assertEqual(len(issues),1);self.assertEqual(len(missing),1)
    def test_common_json_wrappers_and_malformed_lines(self):
        rows,errors=parse_text('```json\n'+json.dumps([self.r])+'\n```');self.assertEqual(len(rows),1);self.assertFalse(errors)
        rows,errors=parse_text(json.dumps(self.r)+'\nNOT JSON\n'+json.dumps(self.r));self.assertEqual(len(rows),2);self.assertEqual(len(errors),1)
    def test_issue_needs_concrete_type(self):
        x=copy.deepcopy(self.r);x.update(verdict='issue',reason='Ambiguous condition.');self.assertIn('issue requires',validate(x,self.q,'D'))

if __name__=='__main__':unittest.main()
