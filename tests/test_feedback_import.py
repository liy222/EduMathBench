"""Safety and preservation checks for feedback intake, not tests of mathematical truth."""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from intake_review_archives import safe_path
from merge_review_feedback import normalized_review

class ImportRules(unittest.TestCase):
    def test_safe_relative_file(self):
        root=Path('D:/EduMathBench/AI复核/test-only')
        self.assertEqual(safe_path(root,'P01/images/q0008.png'),(root/'P01/images/q0008.png').resolve())
    def test_traversal_and_absolute_names_rejected(self):
        for name in ['../escape.txt','P01/../../escape.txt','C:/escape.txt','/escape.txt','\\\\host\\share\\file','images/a.png:stream']:
            with self.subTest(name=name),self.assertRaises(ValueError):safe_path(Path('D:/EduMathBench/test-only'),name)
    def test_only_lossless_aliases_are_changed(self):
        row={'suggested_fix':None,'issue_types':['provided_answer_incorrect'],'reason':'原反馈推导','reviewer':'','image_access':'not_viewed','verdict':'correct'};before=copy.deepcopy(row)
        fixed,notes=normalized_review(row)
        self.assertEqual(row,before);self.assertEqual(fixed['suggested_fix'],'');self.assertEqual(fixed['issue_types'],['answer_mismatch']);self.assertEqual(len(notes),2)
        self.assertEqual(fixed['reason'],row['reason']);self.assertEqual(fixed['reviewer'],'');self.assertEqual(fixed['image_access'],'not_viewed');self.assertEqual(fixed['verdict'],'correct')
    def test_no_new_reason_or_image_claim(self):
        row={'suggested_fix':'','issue_types':['image_mismatch'],'reason':'','image_access':'not_viewed'}
        fixed,notes=normalized_review(row);self.assertEqual(fixed,row);self.assertEqual(notes,[])

if __name__=='__main__':unittest.main()
