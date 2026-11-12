import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('parent_selection',ROOT/'data/variants/parents/select_parents.py')
selection=importlib.util.module_from_spec(spec);spec.loader.exec_module(selection)
class ImageDetectionRegression(unittest.TestCase):
    def test_separate_assets_without_placeholder(self):
        q={'question':'如图，矩形ABCD…','image_assets':[{'path':'diagram.png'}]}
        self.assertTrue(selection.is_image(q))
        self.assertFalse(selection.diagram_reference_without_picture(q))
    def test_image_modality_without_inline_marker(self):
        self.assertTrue(selection.is_image({'question':'图中x的值','input_modality':'text_image'}))
    def test_text_only_reference_still_requires_check(self):
        q={'question':'如图，求x','image_assets':[],'input_modality':'text'}
        self.assertFalse(selection.is_image(q))
        self.assertTrue(selection.diagram_reference_without_picture(q))
    def test_selected_asset_records_match_files(self):
        rows=[json.loads(s) for s in (ROOT/'data/variants/parents/parents_300.jsonl').read_text(encoding='utf-8').splitlines()]
        images=[q for q in rows if q.get('image_assets')]
        self.assertEqual(len(images),21)
        for q in images:
            self.assertTrue(q['has_image'],q['id'])
            self.assertFalse(q['diagram_reference_without_embedded_image'],q['id'])
            for a in q['image_assets']:
                path=ROOT/a['path'];self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),a['sha256'])
if __name__=='__main__':unittest.main()
