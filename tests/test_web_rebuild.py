"""Checks for quota selection, immutable provenance and image-answer gates."""
import importlib.util,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import rebuild_web_benchmark as r

class RebuildTests(unittest.TestCase):
    def test_answer_content_comparison_uses_image_bytes(self):
        a={'image_assets':[{'asset_id':'url1','role':'option_A','sha256':'same'}]}
        b={'image_assets':[{'asset_id':'url2','role':'option_D','sha256':'same'}]}
        self.assertEqual(r.canonical_content(a,'[图片:url1]'),r.canonical_content(b,'[图片:url2]'))

    def test_shared_file_cache_preserves_occurrence_role(self):
        first={'asset_id':'same','role':'question','url':'https://example/a.png'}
        cached={'asset_id':'same','role':'option_D','url':'https://example/a.png','local_path':'assets/a.png','download_status':'saved','sha256':'123'}
        merged={**first,**r.downloaded_fields(cached)}
        self.assertEqual(merged['role'],'question')
        self.assertEqual(merged['local_path'],'assets/a.png')

    def test_numeric_superscript_spilled_prose_is_restored(self):
        from lxml import html
        text=r.site.readable(html.fromstring('<div>10<sup>﹣9米。后面的题干</sup></div>'),'https://example/','question',[])
        self.assertIn('米。后面的题干',text)
        self.assertNotIn('米。后面的题干}',text)

    def test_baseline_manifest_matches_immutable_original(self):
        snapshot=json.loads((r.OUT/'baseline/snapshot.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['sha256'],r.sha(ROOT/snapshot['source_path']))
        self.assertEqual(len(r.read(r.OUT/'baseline/retained_original.jsonl')),363)
        self.assertEqual(len(r.read(r.OUT/'baseline/retired_public.jsonl')),1137)

    def test_quota_flow_avoids_greedy_difficulty_starvation(self):
        f=r.Flow();f.edge('s','a',1);f.edge('s','b',1)
        a_easy=f.edge('a','easy',1);a_hard=f.edge('a','hard',1)
        f.edge('b','easy',1);f.edge('easy','t',1);f.edge('hard','t',1)
        self.assertEqual(f.run('s','t'),2)
        self.assertEqual(a_hard[3]-a_hard[1],1)
        self.assertEqual(a_easy[3]-a_easy[1],0)

    def test_missing_source_answer_is_not_accepted(self):
        q={'question':'题目','options':dict(zip('ABCD','1234')),'answer':'','difficulty':'基础','image_assets':[]}
        self.assertIn('source_answer_missing_or_unrecognized',r.rejection_reasons(q))

    def test_pending_images_never_count_as_final_ready(self):
        q={'question':'[图片:x]','options':dict(zip('ABCD','1234')),'answer':'A','difficulty':'基础',
           'image_assets':[{'role':'question','download_status':'pending'}]}
        self.assertEqual(r.rejection_reasons(q,require_assets=False),[])
        self.assertIn('required_image_not_saved',r.rejection_reasons(q))

    def test_ocr_pending_is_not_a_standard_answer(self):
        q={'question':'题目','options':dict(zip('ABCD','1234')),'answer':'','difficulty':'基础',
           'image_assets':[{'role':'answer','download_status':'saved'}]}
        self.assertEqual(r.rejection_reasons(q,allow_pending_answer_image=True),[])
        self.assertIn('source_answer_missing_or_unrecognized',r.rejection_reasons(q))

    def test_missing_figure_is_held_even_if_answer_present(self):
        q={'question':'如图，求角度','options':dict(zip('ABCD','1234')),'answer':'A','difficulty':'中等','image_assets':[]}
        self.assertIn('figure_reference_without_archived_input',r.rejection_reasons(q))

    def test_retained_model_annotations_not_misrepresented_as_new(self):
        for q in r.read(r.OUT/'retained/questions.jsonl'):
            self.assertEqual(q['acquisition_origin'],'retained_legacy_web')
            self.assertEqual(q['solution_format'],'not_requested')

if __name__=='__main__':unittest.main()
