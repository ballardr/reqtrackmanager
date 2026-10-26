"""Tests for math in reports (`services.report_math`): the TeX allow-list, finding equations in text, drawing
them as SVG and PNG, and Word's native markup for the tested subset (a golden test, so a converter upgrade
cannot change what Word is given without a person looking)."""

from __future__ import annotations

import re

import pytest
from lxml import etree

from app.services import report_math as rm

OMML = f' xmlns:m="{rm.OMML_NS}"'

_ONE_ARGUMENT = (
    "sqrt overline underline hat bar vec dot ddot tilde widehat widetilde overrightarrow overbrace underbrace mathrm "
    "mathbf mathit mathbb mathcal mathsf mathtt boldsymbol"
).split()
_TWO_ARGUMENTS = "frac dfrac tfrac binom stackrel".split()
_SIZES = "big Big bigg Bigg".split()
_SIZES_PAIRED = {"bigl": "bigr", "Bigl": "Bigr", "biggl": "biggr", "Biggl": "Biggr", "bigr": "bigl", "Bigr": "Bigl",
                 "biggr": "biggl", "Biggr": "Biggl"}


def sample(command: str) -> str:
    """A valid equation using `command`."""
    if command in _ONE_ARGUMENT:
        return rf"\{command}{{x}}"
    if command in _TWO_ARGUMENTS:
        return rf"\{command}{{a}}{{b}}"
    if command in rm.TEXT_COMMANDS:
        return rf"\{command}{{plain words}}"
    if command in ("left", "right"):
        return r"\left( x \right)"
    if command in _SIZES:
        return rf"\{command}( x \{command})"
    if command in _SIZES_PAIRED:
        opener, closer = (command, _SIZES_PAIRED[command]) if command.endswith("l") else (_SIZES_PAIRED[command], command)
        return rf"\{opener}( x \{closer})"
    if command in ("begin", "end"):
        return r"\begin{matrix}a&b\\c&d\end{matrix}"
    if command == "not":
        return r"a \not= b"
    return rf"a \{command} b"


# --- the allow-list -------------------------------------------------------------------------------


@pytest.mark.parametrize("command", sorted(rm.ALLOWED_COMMANDS))
def test_every_allowed_command_is_accepted_and_can_be_drawn(command):
    tex = sample(command)

    assert rm.tex_problem(tex) is None, tex
    assert rm.typeset(tex) is not None, f"{command} is allowed but ziamath cannot draw {tex}"


@pytest.mark.parametrize("environment", sorted(rm.ALLOWED_ENVIRONMENTS))
def test_every_allowed_environment_can_be_drawn(environment):
    body = r"{cc}a&b\\c&d" if environment == "array" else r"a&b\\c&d"
    tex = rf"\begin{{{environment}}}{body}\end{{{environment}}}"

    assert rm.tex_problem(tex) is None
    assert rm.typeset(tex) is not None


@pytest.mark.parametrize("tex", [
    r"\href{http://example.com}{x}", r"\url{http://example.com}", r"\input{/etc/passwd}", r"\include{x}",
    r"\includegraphics{x.png}", r"\write18{ls}", r"\def\x{1}", r"\newcommand{\x}{1}", r"\csname x\endcsname",
    r"\verb|x|", r"\special{x}", r"\style{color:red}{x}", r"\color{red}{x}", r"\unknown", r"\(", r"\[", "x \\",
])
def test_a_command_outside_the_list_is_refused(tex):
    assert rm.tex_problem(tex)


@pytest.mark.parametrize("tex", [
    r"\text{<img src=x>}", r"\text{a & b}", r"\text{a \href b}", r"\text{a {b} c}", r"\text{50% off}", r"\text{x",
    r"\text x", r"\operatorname{a<b}",
])
def test_the_text_of_a_text_command_is_plain(tex):
    assert rm.tex_problem(tex)


@pytest.mark.parametrize("tex, why", [
    ("", "empty"), ("   ", "empty"), ("x%y", "%"), ("x # y", "#"), ("$x", "$"), ("a~b", "~"), ('a"b', '"'),
    ("a & b", "&"), ("{a", "never closed"), ("a}", "no matching"), ("x\u0000y", "control"), ("x​y", "invisible"),
    (r"\begin{matrix}a", "never closed"), (r"\begin{matrix}a\end{pmatrix}", "does not match"),
    (r"\end{matrix}", "does not match"), (r"\begin{tabular}a\end{tabular}", "must name"),
    (r"\begin{document}x\end{document}", "must name"), ("{" * 11 + "x" + "}" * 11, "nested"),
    ("x" * (rm.MAX_TEX_CHARS + 1), "limited to"),
])
def test_other_unsafe_or_malformed_tex_is_refused(tex, why):
    problem = rm.tex_problem(tex)

    assert problem and why in problem


def test_an_ampersand_is_fine_inside_an_environment_and_braces_may_nest_to_the_limit():
    assert rm.tex_problem(r"\begin{cases}a&b\\c&d\end{cases}") is None
    assert rm.tex_problem("{" * rm.MAX_TEX_DEPTH + "x" + "}" * rm.MAX_TEX_DEPTH) is None


def test_comparison_signs_and_unicode_letters_are_allowed():
    assert rm.tex_problem("a < b > c ≤ d") is None
    assert rm.tex_problem("α + β") is None


def test_the_problem_names_the_command_but_never_more_than_thirty_letters():
    problem = rm.tex_problem("\\" + "a" * 100)

    assert problem and "a" * 30 in problem and "a" * 31 not in problem


# --- finding equations in text --------------------------------------------------------------------


def kinds(text, eligible=None):
    return [(s.kind, s.value) for s in rm.split_math(text, eligible)]


def test_inline_and_display_delimiters_are_found():
    assert kinds(r"Let \(x<y\) and $$ a=b $$ done") == [
        ("text", "Let "), ("inline", "x<y"), ("text", " and "), ("display", " a=b "), ("text", " done"),
    ]


def test_text_with_no_delimiter_is_one_text_segment_and_empty_text_is_none():
    assert kinds("plain") == [("text", "plain")]
    assert kinds("") == []


@pytest.mark.parametrize("text", [
    "costs $5 or $6", r"an open \(x", r"a lone \) close", "an open $$ x", r"empty \(\) pair", "empty $$   $$ pair",
    "a single $x$ is not math",
])
def test_a_stray_or_empty_delimiter_is_ordinary_text(text):
    assert kinds(text) == [("text", text)]


def test_adjacent_equations_and_equations_at_the_ends():
    assert kinds(r"\(a\)\(b\)") == [("inline", "a"), ("inline", "b")]
    assert kinds("$$a$$") == [("display", "a")]


def test_a_delimiter_only_counts_where_the_mask_allows_it():
    text = r"A \(x\) B"
    mask = [i not in (2, 3) for i in range(len(text))]  # the opener is inside a value that is not math-capable

    assert kinds(text, mask) == [("text", text)]
    assert kinds(text, [True] * len(text)) == [("text", "A "), ("inline", "x"), ("text", " B")]


def test_a_closer_from_another_value_does_not_close_an_equation():
    text = r"\(x then \) y \)"
    mask = [not (8 <= i < 10) for i in range(len(text))]

    assert kinds(text, mask) == [("inline", r"x then \) y ")]


def test_a_mask_of_the_wrong_length_is_a_programming_error():
    with pytest.raises(ValueError):
        rm.split_math("abc", [True])


# --- drawing ---------------------------------------------------------------------------------------


def test_typeset_returns_a_sanitised_svg_with_its_size_and_baseline():
    drawn = rm.typeset(r"\frac{a}{b}")
    plain = rm.typeset("x")

    assert drawn is not None and plain is not None
    assert drawn.svg.startswith("<svg") and "<script" not in drawn.svg and "<text" not in drawn.svg
    assert drawn.width > 0 and drawn.height > 0
    assert 0 < drawn.descent < drawn.height  # a fraction hangs below the baseline
    assert plain.descent < drawn.descent


def test_a_display_equation_is_larger_than_the_same_inline():
    inline, display = rm.typeset(r"\sum_{i=1}^n i", False), rm.typeset(r"\sum_{i=1}^n i", True)

    assert inline and display and display.height > inline.height


def test_whitespace_is_normalised_and_the_result_is_cached():
    assert rm.typeset("a   +\n b") is rm.typeset("a + b")


@pytest.mark.parametrize("tex", [r"\frac{a}", "{", r"\href{http://x}{y}", r"\text{<img src=x>}", "", "x%y"])
def test_tex_that_cannot_be_drawn_gives_none_never_an_error(tex):
    assert rm.typeset(tex) is None
    assert rm.omml(tex) is None


def test_the_svg_holds_only_paths_and_rectangles():
    drawn = rm.typeset(r"\sqrt{\frac{\alpha}{\beta}} + \int_0^1 x\,dx")

    assert drawn is not None
    assert set(re.findall(r"<([a-zA-Z]+)", drawn.svg)) <= {"svg", "path", "rect", "g"}


def test_png_of_is_a_transparent_png_sized_by_zoom():
    drawn = rm.typeset("x^2")
    assert drawn is not None
    small, large = rm.png_of(drawn, zoom=1), rm.png_of(drawn, zoom=4)

    assert small and large and small[:8] == b"\x89PNG\r\n\x1a\n" and len(large) > len(small)


def test_scaled_svg_rewrites_only_the_root_size():
    drawn = rm.typeset(r"\frac{a}{b}")
    assert drawn is not None
    scaled = rm.scaled_svg(drawn, 0.1, "em")

    assert f'width="{drawn.width * 0.1:.3f}em"' in scaled and f'height="{drawn.height * 0.1:.3f}em"' in scaled
    assert scaled.count("viewBox") == 1 and scaled.endswith("</svg>")


def test_source_of_writes_the_delimiters_the_author_used():
    assert rm.source_of("x", display=False) == r"\(x\)"
    assert rm.source_of("x", display=True) == "$$x$$"


# --- Word's equations ------------------------------------------------------------------------------

def compact(markup: str) -> str:
    """Word markup with the namespace dropped and each plain run written `[style:text]` (`i` italic, `p` upright,
    `nor` normal text), so the pinned structure stays readable."""
    markup = markup.replace(OMML, "").replace("m:", "")
    markup = re.sub(r'<r><rPr><nor/></rPr><t xml:space="preserve">([^<]*)</t></r>', r"[nor:\1]", markup)
    return re.sub(r'<r><rPr><sty val="(\w)"/></rPr><t xml:space="preserve">([^<]*)</t></r>', r"[\1:\2]", markup)


GOLDEN = [
    ('\\frac{a}{b}',
     '<oMath><f><num>[i:a]</num><den>[i:b]</den></f></oMath>'),
    ('\\sqrt{x}',
     '<oMath><rad><radPr><degHide val="1"/></radPr><deg/><e>[i:x]</e></rad></oMath>'),
    ('\\sqrt[3]{x}',
     '<oMath><rad><deg>[p:3]</deg><e>[i:x]</e></rad></oMath>'),
    ('x^2_i',
     '<oMath><sSubSup><e>[i:x]</e><sub>[i:i]</sub><sup>[p:2]</sup></sSubSup></oMath>'),
    ('\\sum_{i=1}^n i',
     '<oMath><nary><naryPr><chr val="∑"/><limLoc val="undOvr"/></naryPr><sub>[i:i][p:=][p:1]</sub><sup>[i:n]</sup><e>[i:i]</e></nary></oMath>'),
    ('\\begin{pmatrix}a&b\\\\c&d\\end{pmatrix}',
     '<oMath><d><dPr><begChr val="("/><endChr val=")"/></dPr>'
     '<e><m><mr><e>[i:a]</e><e>[i:b]</e></mr><mr><e>[i:c]</e><e>[i:d]</e></mr></m></e></d></oMath>'),
    ('\\text{if } x \\geq 0',
     '<oMath>[nor:if\xa0][i:x][p:≥][p:0]</oMath>'),
    ('\\left(\\alpha\\right)',
     '<oMath><d><dPr><begChr val="("/><endChr val=")"/></dPr><e>[i:α]</e></d></oMath>'),
]


@pytest.mark.parametrize("tex, expected", GOLDEN)
def test_the_word_markup_for_the_supported_subset_is_pinned(tex, expected):
    produced = rm.omml(tex)

    assert produced is not None
    assert compact(produced) == expected


def test_a_square_root_always_carries_the_degree_word_requires():
    assert "<m:degHide" in (rm.omml(r"\sqrt{x}") or "") and "<m:deg>" in (rm.omml(r"\sqrt[3]{x}") or "")


def test_the_converters_empty_boxes_are_unwrapped():
    assert "<m:box" not in (rm.omml(r"\frac{a}{b}") or "<m:box")


@pytest.mark.parametrize("tex", [
    r"\hat{x}", r"\overline{x}", r"\vec{v}", r"\overbrace{abc}", r"\lim_{x \to 0} f(x)", r"\limsup a_n",
    r"\begin{aligned}a&=b\\c&=d\end{aligned}",
])
def test_an_equation_outside_the_subset_is_drawn_as_a_picture_not_given_to_word(tex):
    assert rm.omml(tex) is None
    assert rm.typeset(tex) is not None  # the picture exists


def test_every_element_of_every_golden_sample_is_in_the_subset():
    for tex, _ in GOLDEN:
        root = etree.fromstring((rm.omml(tex) or "").encode())
        names = {etree.QName(e).localname for e in root.iter()}
        assert names <= rm.OMML_ELEMENTS, (tex, names - rm.OMML_ELEMENTS)


def test_text_in_an_equation_keeps_its_spaces():
    assert 'xml:space="preserve"' in (rm.omml(r"\text{if } x") or "")
