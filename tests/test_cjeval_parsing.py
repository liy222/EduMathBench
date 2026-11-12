import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare_cjeval_collection import split_choices


class CJEvalParsingTests(unittest.TestCase):
    def test_reordered_source_labels_preserve_their_meaning(self):
        stem, options, risks = split_choices('题干选项：B. 6个 A. 8个C. 7个D. 5个')
        self.assertEqual(stem, '题干')
        self.assertEqual(options, ['8个', '6个', '7个', '5个'])
        self.assertEqual(risks, [])

    def test_missing_or_duplicate_label_is_never_guessed(self):
        for content in ['题干选项：A. 1 B. 2 B. 3 C. 4',
                        '题干选项：1. 1 2. 2 3. 3 4. 4',
                        {'ques_content': '题干'}]:
            _, options, risks = split_choices(content)
            self.assertTrue(risks)
            self.assertEqual(options, ['', '', '', ''])


if __name__ == '__main__':
    unittest.main()
