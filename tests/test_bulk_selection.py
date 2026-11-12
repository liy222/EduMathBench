import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from select_bulk_collection import deduplicate, fill_quotas


def question(id, options=('1', '2', '3', '4'), answer='A'):
    return dict(id=id, question='同一个题干', **dict(zip(['option_' + c for c in 'abcd'], options)),
                answer=answer, grade=7, module='数与式', status='collected', risk_flags=[])


class BulkSelectionTest(unittest.TestCase):
    def test_reordered_options_merge_only_when_answer_meaning_agrees(self):
        one = question('1')
        two = question('2', ('2', '1', '3', '4'), 'B')
        unique, conflicts, groups = deduplicate([one, two])
        self.assertEqual((len(unique), len(conflicts), len(groups)), (1, 0, 1))
        three = question('3', ('2', '1', '3', '4'), 'A')
        unique, conflicts, _ = deduplicate([question('1'), three])
        self.assertEqual((len(unique), len(conflicts)), (0, 2))
        self.assertTrue(all(q['status'] == 'needs_review' for q in conflicts))

    def test_counts_existing_records_and_keeps_overflow_in_reserve(self):
        cells = [{'grade': 7, 'module': '数与式', 'target': 2},
                 {'grade': 7, 'module': '函数', 'target': 0}]
        rows = [question(str(i)) for i in range(4)]
        rows[-1]['module'] = '函数'
        selected, reserve = fill_quotas(rows, cells, [question('existing')])
        self.assertEqual((len(selected), len(reserve)), (1, 3))
        self.assertFalse(any(q['module'] == '函数' for q in selected))


if __name__ == '__main__':
    unittest.main()
