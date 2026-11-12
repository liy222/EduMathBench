"""Prevent formatting repairs from changing inequalities, exponents or source inputs."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from question_format import canonical_question, normalize_text


class QuestionFormatTests(unittest.TestCase):
    def test_browser_report_prose_commands_preserve_blank_variable_and_ellipsis(self):
        value, rules = normalize_text(r'间隔是~\uline{~~~~~~~~~~}~分钟；与\emph{x}轴相交；反复操作\ldots\ldots 如此下去。')
        self.assertEqual(value, '间隔是____分钟；与x轴相交；反复操作……如此下去。')
        self.assertEqual(normalize_text(value)[0], value)
        # An underline around real content is not silently treated as an empty blank.
        self.assertEqual(normalize_text(r'\uline{a+b}')[0], r'\uline{a+b}')
        self.assertEqual(normalize_text(r'$1+2+\ldots+n$')[0], r'$1+2+\ldots+n$')

    def test_inequalities_and_absolute_bars_keep_their_meaning(self):
        text = r'$$-2\textless{}x\textgreater 0; \left\textbar x-2\right\textbar^2$$'
        value, rules = normalize_text(text)
        self.assertEqual(value, r'$-2<{}x> 0; \left\vert  x-2\right\vert ^2$')
        self.assertNotIn('≤', value)
        self.assertNotIn('≥', value)
        self.assertEqual(normalize_text(value)[0], value)

    def test_input_archive_and_answer_are_preserved(self):
        q = dict(id='Q', question='y=x<sup>2</sup>-4x+3', option_a='$$1$$', option_b='2', option_c='3', option_d='4', answer='B')
        normalized = canonical_question(q)
        self.assertEqual(normalized['question'], 'y=x²-4x+3')
        self.assertEqual(normalized['source_input']['question'], q['question'])
        self.assertEqual(q['question'], 'y=x<sup>2</sup>-4x+3')
        self.assertEqual(normalized['answer'], 'B')
        self.assertEqual(normalized['source_input']['option_a'], '$$1$$')

    def test_defined_unicode_operation_symbol_is_retained(self):
        normalized, _ = normalize_text('定义※：$a ※ b=a^{b}+a b$')
        self.assertEqual(normalized, '定义※：$a $※$ b=a^{b}+a b$')
        self.assertEqual(normalize_text(normalized)[0], normalized)


if __name__ == '__main__':
    unittest.main()
