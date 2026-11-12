"""验证收集统计不会把冲突答案、缺出处或重复题计入完成数量。"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('collection', Path(__file__).resolve().parents[1] / 'scripts/check_collection.py')
collection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collection)


class CollectionTests(unittest.TestCase):
    def test_original_figures_are_part_of_duplicate_identity(self):
        q = dict(question='如图<ImageHere>', option_a='1', option_b='2', option_c='3', option_d='4')
        left = {**q, 'image_assets': [{'role': 'stem', 'sha256': 'first'}]}
        right = {**q, 'image_assets': [{'role': 'stem', 'sha256': 'second'}]}
        self.assertNotEqual(collection.fingerprint(left), collection.fingerprint(right))
        self.assertNotEqual(collection.fingerprint(left, True), collection.fingerprint(right, True))
        left['image_assets'][0]['path'] = 'different-local-filename.jpg'
        self.assertEqual(collection.fingerprint(left), collection.fingerprint({**q, 'image_assets': [{'role': 'stem', 'sha256': 'first'}]}))

    def test_solution_images_cannot_enter_question_inputs(self):
        q = dict(id='Q', question='如图<ImageHere>', option_a='1', option_b='2', option_c='3', option_d='4',
                 answer='A', grade=7, module='几何', knowledge_point='测试', difficulty='困难',
                 source_id='S', source_ref='题1', source_type='public', status='collected', batch_id='test',
                 input_modality='text_image', image_assets=[{'path': 'nonexistent.jpg', 'role': 'analysis',
                  'contains_answer_or_solution': True, 'source_url': 'https://example.com', 'source_ref': '图1'}])
        errors = collection.question_problems(q, {'S': {}}, {})
        self.assertIn('image_asset_answer_leakage_or_invalid_role', errors)
        self.assertIn('image_placeholder_mapping_mismatch:question', errors)

    def test_existing_difficulty_documentation_cannot_change_native_label(self):
        q = {'difficulty':'中等'}
        a = {'difficulty':'基础', 'decision':'document_existing_label', 'reason':'direct definition'}
        collection.apply_difficulty_annotation(q, a)
        self.assertEqual(q, {'difficulty':'中等'})
        a['difficulty'] = '中等'
        collection.apply_difficulty_annotation(q, a)
        self.assertEqual(q['difficulty'], '中等')
        self.assertEqual(q['difficulty_annotation'], a)
        reviewed = {'difficulty':'基础', 'previous_difficulty':'困难',
                    'decision':'review_existing_label', 'reason':'weighted mean direct calculation'}
        q = {'difficulty':'中等'}
        collection.apply_difficulty_annotation(q, reviewed)
        self.assertEqual(q, {'difficulty':'中等'})
        q = {'difficulty':'困难'}
        collection.apply_difficulty_annotation(q, reviewed)
        self.assertEqual(q['difficulty'], '基础')
        self.assertEqual(q['difficulty_annotation'], reviewed)
        q = {'difficulty':'pending'}
        collection.apply_difficulty_annotation(q, a)
        self.assertEqual(q['difficulty'], '中等')

    def test_reviewed_duplicate_keeps_explicit_primary_even_if_loaded_later(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'config').mkdir()
            (root / 'config/quotas.json').write_text(json.dumps({'version':'test', 'public_target':1,
                'cells':[{'grade':7, 'module':'数与式', 'target':1, 'owner':'test'}]}), encoding='utf-8')
            batch = root / 'data/batches/test'
            batch.mkdir(parents=True)
            (batch / 'raw.txt').write_text('测试原件', encoding='utf-8')
            collection.write_jsonl(batch / 'sources.jsonl', [{'source_id':'S', 'title':'来源',
                'url':'https://example.com/a', 'answer_location':'题1', 'accessed_at':'2026-10-13T19:00:00+08:00',
                'raw_path':'data/batches/test/raw.txt'}])
            q = dict(question='题干', option_a='1', option_b='2', option_c='3', option_d='4',
                     answer='A', grade=7, module='数与式', knowledge_point='测试', difficulty='pending',
                     source_id='S', source_ref='题1', source_type='public', status='collected', batch_id='test')
            collection.write_jsonl(batch / 'questions.jsonl', [{**q, 'id':'NEW',
                'provenance':{'dataset':'test', 'line':2, 'original_id':'new-source-id'}}, {**q, 'id':'OLD'}])
            collection.write_jsonl(root / 'data/resolutions/merge.jsonl', [{'id':'NEW',
                'decision':'merge_verified_duplicate', 'primary_id':'OLD', 'reason':'same source question'}])
            old_root = collection.ROOT
            try:
                collection.ROOT = root
                collection.main()
            finally:
                collection.ROOT = old_root
            rows = [json.loads(s) for s in (root / 'data/public_draft/questions.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([q['id'] for q in rows], ['OLD'])
            self.assertEqual(rows[0]['additional_sources'][0]['id'], 'NEW')
            self.assertEqual(rows[0]['additional_sources'][0]['provenance']['original_id'], 'new-source-id')

    def test_manual_semantic_merge_is_pinned_to_reviewed_content_and_options(self):
        p = dict(question='整数点个数', option_a='10', option_b='9', option_c='7', option_d='5', answer='B')
        q = {**p, 'question':'整数坐标对的对数'}
        resolution = dict(primary_fingerprint=collection.fingerprint(p), duplicate_fingerprint=collection.fingerprint(q))
        self.assertTrue(collection.verified_duplicate_match(p, q, 'reviewed_stem_same_options', resolution))
        q['question'] += '另有附加条件'
        self.assertFalse(collection.verified_duplicate_match(p, q, 'reviewed_stem_same_options', resolution))
        q = {**p, 'question':'整数坐标对的对数', 'option_c':'8'}
        self.assertFalse(collection.verified_duplicate_match(p, q, 'reviewed_stem_same_options', resolution))

    def test_reviewed_presentation_merge_preserves_math_content(self):
        p = dict(question='求x（ ）', option_a='$ab$', option_b='-2',
                 option_c='$x^{2}$', option_d='3', answer='B')
        q = {**p, 'question':'求x', 'option_a':'$\\mathrm{ab}$'}
        self.assertTrue(collection.verified_duplicate_match(p, q, 'math_presentation'))
        self.assertFalse(collection.verified_duplicate_match(p, q))
        q['option_c'] = '$x^{3}$'
        self.assertFalse(collection.verified_duplicate_match(p, q, 'math_presentation'))
        q = {**p, 'option_b':'2'}
        self.assertFalse(collection.verified_duplicate_match(p, q, 'math_presentation'))

    def test_reviewed_prose_merge_does_not_ignore_math_punctuation(self):
        p = dict(question='选择正确说法', option_a='解方程后，不需要检验',
                 option_b='需要检验', option_c='无解', option_d='增根', answer='B')
        q = {**p, 'option_a':'解方程后不需要检验'}
        self.assertTrue(collection.verified_duplicate_match(p, q, 'chinese_prose_commas'))
        self.assertFalse(collection.verified_duplicate_match(p, q))
        p['option_a'], q['option_a'] = '(1,2)', '(12)'
        self.assertFalse(collection.verified_duplicate_match(p, q, 'chinese_prose_commas'))
        q = {**p, 'answer':'A'}
        self.assertFalse(collection.verified_duplicate_match(p, q, 'chinese_prose_commas'))

    def test_duplicated_correct_option_is_blocked_even_with_valid_source_answer(self):
        base = dict(id='Q', question='题', option_a='3', option_b='2', option_c='1', option_d=' 3 ',
                    answer='A', grade=7, module='数与式', knowledge_point='测试', difficulty='pending',
                    source_id='S', source_ref='题1', source_type='public', status='collected', batch_id='test')
        self.assertIn('duplicate_correct_option', collection.question_problems(base, {'S': {}}, {}))
        base['answer'] = 'B'
        self.assertNotIn('duplicate_correct_option', collection.question_problems(base, {'S': {}}, {}))

    def test_math_symbols_preserved(self):
        self.assertNotEqual(collection.normalized('x - 1'), collection.normalized('x + 1'))
        self.assertEqual(collection.normalized('x - 1'), collection.normalized('x-1'))

    def test_equation_reversal_is_a_duplicate_except_for_directional_transform_tasks(self):
        q = dict(id='Q', question='符合题意的方程是', option_a='x+1=2x', option_b='x=3',
                 option_c='2x=x+1', option_d='x=4', answer='A', grade=8, module='方程与不等式',
                 knowledge_point='分式方程', difficulty='pending', source_id='S', source_ref='题1',
                 source_type='public', status='collected', batch_id='test')
        self.assertIn('equivalent_correct_equation_options', collection.question_problems(q, {'S': {}}, {}))
        q['question'] = '下列由左到右的变形属于因式分解的是'
        self.assertNotIn('equivalent_correct_equation_options', collection.question_problems(q, {'S': {}}, {}))

    def test_resolution_preserves_source_answer_and_other_risks(self):
        q = {'id':'Q1', 'answer':'C', 'status':'collected',
             'risk_flags':['near_duplicate_candidate','ocr_formula_uncertain']}
        collection.apply_resolution(q, {'decision':'retain_same_family', 'family_id':'F1',
                                         'reason':'different options, same concept'})
        self.assertEqual(q['family_id'], 'F1')
        self.assertNotIn('near_duplicate_candidate', q['risk_flags'])
        self.assertIn('ocr_formula_uncertain', q['risk_flags'])
        collection.apply_resolution(q, {'decision':'reject', 'reason':'source answer conflict',
                                         'answer':'B'})
        self.assertEqual(q['answer'], 'C')
        self.assertEqual(q['status'], 'rejected')

    def test_duplicate_and_answer_conflict_not_counted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'config').mkdir()
            (root / 'config/quotas.json').write_text(json.dumps({
                'version':'test','public_target':3,
                'cells':[{'grade':7,'module':'数与式','target':3,'owner':'test'}]}), encoding='utf-8')
            batch = root / 'data/batches/test'
            batch.mkdir(parents=True)
            (batch / 'raw.txt').write_text('测试原件', encoding='utf-8')
            collection.write_jsonl(batch / 'sources.jsonl', [{
                'source_id':'S1','title':'test','url':'https://example.com/paper',
                'answer_location':'第1题','accessed_at':'2026-10-09T12:00:00+08:00',
                'raw_path':'data/batches/test/raw.txt'}])
            base = {'id':'Q1','question':'x-1','option_a':'1','option_b':'2','option_c':'3',
                    'option_d':'4','answer':'A','grade':7,'module':'数与式',
                    'knowledge_point':'测试','difficulty':'pending','source_id':'S1',
                    'source_ref':'第1题','source_type':'public','status':'collected','batch_id':'test'}
            collection.write_jsonl(batch / 'questions.jsonl', [base, {**base,'id':'Q2'},
                                                                {**base,'id':'Q3','answer':'B'},
                                                                {**base,'id':'Q4','question':'y','source_id':'missing'}])
            original_root = collection.ROOT
            try:
                collection.ROOT = root
                collection.main()
            finally:
                collection.ROOT = original_root
            summary = json.loads((root / 'data/reports/summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['auto_checked_unique'], 0)
            self.assertEqual(summary['remaining'], 3)
            self.assertEqual(summary['duplicate_count'], 0)
            held = [json.loads(l) for l in (root / 'data/candidates/needs_review.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual({q['id'] for q in held}, {'Q1', 'Q2', 'Q3', 'Q4'})
            self.assertTrue(all('source_answer_conflict' in q['automatic_check_errors']
                                for q in held if q['id'] in {'Q1', 'Q2', 'Q3'}))
            self.assertTrue(all(q['status'] != 'approved' for q in held))

    def test_conflict_detected_even_if_copy_is_already_held(self):
        base = {'id': 'Q1', 'question': '题干', 'option_a': '1', 'option_b': '2',
                'option_c': '3', 'option_d': '4', 'answer': 'A'}
        reordered = {**base, 'id': 'Q2', 'option_a': '2', 'option_b': '1',
                     'answer': 'A', 'status': 'needs_review'}
        self.assertEqual(collection.conflicting_answer_ids([base, reordered]), {'Q1', 'Q2'})
        reordered['answer'] = 'B'
        self.assertEqual(collection.conflicting_answer_ids([base, reordered]), set())


if __name__ == '__main__':
    unittest.main()
