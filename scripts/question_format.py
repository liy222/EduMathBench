"""Create reversible canonical inputs without modifying the archived source draft."""
import hashlib
import html
import json
import re

VERSION = 'question-format-v1.1'
SUPERSCRIPTS = str.maketrans('0123456789+-=()', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾')
SOURCE_FIELDS = ['question', 'option_a', 'option_b', 'option_c', 'option_d']
CONGRUENCE = r'\stackrel{\Large\lower.2em\backsim}{\lower.1em=}'


def normalize_text(text):
    value, rules = text, []
    substitutions = [
        (r'\textless', '<', 'textless_to_less_than'),
        (r'\textgreater', '>', 'textgreater_to_greater_than'),
        (r'\textbar', r'\vert ', 'textbar_to_absolute_bar'),
        (r'\overparen', r'\overset{\frown}', 'overparen_to_arc_notation'),
        (CONGRUENCE, r'\cong ', 'source_custom_congruence_to_cong'),
        (r'\allequal', r'\cong ', 'source_allequal_to_congruence'),
    ]
    for original, replacement, rule in substitutions:
        if original in value:
            value = value.replace(original, replacement)
            rules.append(rule)
    # Only accept numeral superscripts; unknown HTML must remain an audit issue.
    def exponent(match):
        return html.unescape(match[1]).translate(SUPERSCRIPTS)
    changed = re.sub(r'<sup>\s*([0-9+\-=()]+)\s*</sup>', exponent, value, flags=re.I)
    if changed != value:
        rules.append('html_numeral_superscript_to_unicode')
        value = changed
    changed = re.sub(r'<br\s*/?>', ' ', value, flags=re.I)
    if changed != value:
        rules.append('table_cell_linebreak_to_space')
        value = changed
    changed = html.unescape(value)
    if changed != value:
        rules.append('html_entity_decoding')
        value = changed
    # Source datasets wrap individual variables in display delimiters; keep them inline.
    if '$$' in value:
        value = value.replace('$$', '$')
        rules.append('display_delimiter_to_inline')
    # Only repair prose outside math delimiters; valid mathematical ellipses stay intact.
    def prose(part):
        for pattern, replacement, rule in [
            (r'~*\\uline\{[~\s]+\}~*', '____', 'prose_underlined_blank_to_blank'),
            (r'\\emph\{([A-Za-z])\}', r'\1', 'prose_emphasis_preserve_variable'),
            (r'(?:\\ldots\s*)+', '……', 'prose_ldots_to_ellipsis'),
        ]:
            changed = re.sub(pattern, replacement, part)
            if changed != part:
                part = changed
                if rule not in rules:
                    rules.append(rule)
        return part
    pieces, cursor = [], 0
    for match in re.finditer(r'(?<!\\)\$[^$]*\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]', value):
        pieces.extend([prose(value[cursor:match.start()]), match[0]])
        cursor = match.end()
    pieces.append(prose(value[cursor:]))
    value = ''.join(pieces)
    if 'S_{△ABD}' in value:
        value = value.replace('S_{△ABD}', r'$S_{\triangle ABD}$')
        rules.append('reviewed_triangle_area_subscript_delimiter')
    def glyphs(match):
        formula = match[1]
        for index, character in enumerate('①②③④⑤⑥⑦⑧⑨⑩', 1):
            formula = formula.replace(character, r'\textcircled{' + str(index) + '}')
        formula = formula.replace(r'\mathrm{≌}', r'\cong ')
        # These two source symbols occur at top level and use the normal text font.
        for character in ['※', '▱']:
            if character in formula:
                formula = formula.replace(character, '$' + character + '$')
        return '$' + formula + '$'
    changed = re.sub(r'(?<!\\)\$([^$]*)\$', glyphs, value)
    if changed != value:
        value = changed
        rules.append('unsupported_math_glyph_typography')
    # Splitting a leading text symbol can create an empty formula, which is unnecessary.
    value = re.sub(r'\$\$(?=[※▱])', '', value)
    return value, rules


def input_hash(fields):
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def canonical_question(q):
    original = {key: q[key] for key in SOURCE_FIELDS}
    canonical, applied = {}, {}
    for key, value in original.items():
        canonical[key], rules = normalize_text(value)
        if rules:
            applied[key] = rules
    return {**q, **canonical, 'source_input': original,
            'format_normalization': {'version': VERSION, 'field_rules': applied,
                'source_input_sha256': input_hash(original),
                'canonical_input_sha256': input_hash(canonical),
                'scope': '公式记号、HTML转义及显示分隔符规范化；不改条件、数值、选项顺序或源答案'}}
