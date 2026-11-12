"""Contract tests: complete corrections, image evidence, and conflicting AI proposals."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import analyze_ai_full_reviews as a

class FullReturns(unittest.TestCase):
    def setUp(self):
        self.q={'dataset_id':'test','batch_id':'P01','review_no':1,'question_id':'original-1','input_sha256':'test-hash','kind':'public','grade':7,'module':'数与式','difficulty_provisional':'基础','question':'1+1=（ ）','options':{'A':'1','B':'2','C':'3','D':'4'},'provided_answer':'B','parent_review_no':None,'source_url':'https://example.org/test','requires_image':False,'image_file':None,'image_sha256':None}
        self.registry={1:self.q}
    def result(self):
        x=a.blank(self.q);x.update(reviewer='test reviewer',verdict='pass',independent_answer='B',reason='1+1=2，对应B。',correction_status='unchanged');return x
    def check(self,x):return a.validate(x,self.registry,'test')
    def proposal(self,text='2+2=（ ）'):
        x=self.result();x.update(verdict='issue',correction_status='proposed',issue_types=['other'],suggested_fix='测试修改流程')
        x['revised_question'].update(question=text,options={'A':'1','B':'4','C':'3','D':'5'},answer='B');return x
    def test_pending_not_reviewed(self):
        x=a.blank(self.q);self.assertIsNone(self.check(x));full,proposals,_,_=a.aggregate(self.registry,[x]);self.assertEqual(full[0]['review_status'],'pending');self.assertEqual(proposals,[])
    def test_pass_complete(self):self.assertIsNone(self.check(self.result()))
    def test_pass_cannot_rewrite(self):
        x=self.result();x['revised_question']['question']='同原题';self.assertIsNotNone(self.check(x))
    def test_missing_full_options_rejected(self):
        x=self.result();del x['revised_question']['options']['D'];self.assertIsNotNone(self.check(x))
    def test_proposal_export_and_changes(self):
        x=self.proposal();self.assertIsNone(self.check(x));full,p,c,d=a.aggregate(self.registry,[x]);self.assertEqual(p[0]['revised_question'],x['revised_question']);self.assertEqual(p[0]['question_id'],'original-1');self.assertFalse(p[0]['human_approved']);self.assertEqual({v['field'] for v in d},{'question','options'});self.assertEqual(c,[])
    def test_same_answer_different_text_conflicts(self):
        x=self.proposal();y=self.proposal('3+1=（ ）');y['reviewer']='another';full,p,c,_=a.aggregate(self.registry,[x,y]);self.assertEqual(len(c),1);self.assertEqual(p,[]);self.assertEqual(full[0]['review_status'],'conflict');self.assertIsNone(full[0]['revised_question']['answer'])
    def test_wrong_version_rejected(self):
        x=self.result();x['input_sha256']='wrong';self.assertIsNotNone(self.check(x))
    def test_unresolved_preserves_text_null_answer(self):
        x=self.result();x.update(verdict='uncertain',correction_status='unresolved',independent_answer=None);x['revised_question']['answer']=None;self.assertIsNone(self.check(x));x['revised_question']['question']='猜测的新题';self.assertIsNotNone(self.check(x))
    def test_unseen_image_not_pass(self):
        self.q['requires_image']=True;x=self.result();x['image_access']='not_viewed';x['image_consistency']='not_checked';self.assertIsNotNone(self.check(x))
    def test_unseen_image_unresolved_accepted(self):
        self.q['requires_image']=True;x=a.blank(self.q);x.update(reviewer='test',reason='附件未提供必要图片。',verdict='needs_image',correction_status='unresolved');x['revised_question']['answer']=None;self.assertIsNone(self.check(x))
    def test_image_needs_redraw_not_finished(self):
        self.q['requires_image']=True;x=self.proposal();x.update(image_access='viewed',image_consistency='needs_redraw');self.assertIsNone(self.check(x));full,p,_,_=a.aggregate(self.registry,[x]);self.assertEqual(full[0]['review_status'],'needs_image_redraw')
    def test_boolean_number_rejected(self):
        x=self.result();x['review_no']=True;self.assertIsNotNone(self.check(x))
    def test_v1_missing_full_rejected(self):
        x=self.result();del x['revised_question'];self.assertIsNotNone(self.check(x))

if __name__=='__main__':unittest.main()
