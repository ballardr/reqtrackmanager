"""Tests for PDF text Helvetica cannot print (Cyrillic, Polish letters, Greek) and the document font families.

The PDF renderer used only the built-in Helvetica, which printed such characters as black boxes.
These tests pin the fix: only the characters Helvetica cannot print switch to the bundled Unicode
font, everything else is untouched, and every place text reaches the PDF (headings, paragraphs,
table cells and headers, the footer, column sizing) goes through that rule. They check which fonts
the PDF embeds rather than extracting its text, as this suite does elsewhere.
"""

from __future__ import annotations

import io

import pytest
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import FF_FORCEBOLD, FF_ITALIC, TTFont
from reportlab.pdfgen.canvas import Canvas

from app.services import report_fonts
from app.services.report_document import ReportBranding, safe, styled_table
from app.services.report_fonts import (
    UNICODE_FONT,
    UNICODE_FONT_BOLD,
    draw_centred,
    mark_fallback,
    needs_fallback,
    text_width,
)
from app.services.report_model import BulletList, Heading, Note, Paragraph, ReportDocument, Table
from app.services.report_pdf import render_pdf_document

CYRILLIC = "Привет мир"
POLISH = "Zażółć gęślą jaźń"
GREEK = "αβγ Ωμέγα"


def _fonts(pdf: bytes) -> set[str]:
    """The base font names the PDF refers to, without the subset prefix."""
    names = set()
    for chunk in pdf.split(b"/BaseFont /")[1:]:
        name = chunk.split(b"\n")[0].split(b" ")[0].decode("latin-1")
        names.add(name.split("+")[-1])
    return names


def test_latin1_text_is_left_exactly_as_it_was() -> None:
    for text in ("Plain ASCII", "café ñ ü £ € “quoted” – dash — ©", ""):
        assert not needs_fallback(text)
        assert safe(text) == safe(text, bold=True)
        assert "<font" not in safe(text)


def test_markup_characters_are_still_escaped_before_the_font_tag_is_added() -> None:
    marked = safe("<img src=\"file:///etc/passwd\"> & Привет")
    assert "<img" not in marked and "&lt;img" in marked and "&amp;" in marked
    assert marked.count("<font") == 1 and marked.endswith("</font>")


def test_each_run_of_other_script_text_is_wrapped_once_and_keeps_inner_spaces() -> None:
    assert mark_fallback(f"A {CYRILLIC} B") == f'A <font name="{UNICODE_FONT}">{CYRILLIC}</font> B'
    assert mark_fallback("x Ł y Ż") == f'x <font name="{UNICODE_FONT}">Ł</font> y <font name="{UNICODE_FONT}">Ż</font>'
    assert mark_fallback(f"{CYRILLIC} ") == f'<font name="{UNICODE_FONT}">{CYRILLIC}</font> '


def test_bold_text_gets_the_bold_unicode_font() -> None:
    assert f'name="{UNICODE_FONT_BOLD}"' in safe(POLISH, bold=True)
    assert f'name="{UNICODE_FONT}"' in safe(POLISH)


def test_width_uses_the_font_each_character_prints_in() -> None:
    assert text_width("abc", 10) < text_width("abc", 10, bold=True)
    assert text_width(CYRILLIC, 10) > 0
    mixed = text_width(f"ab {CYRILLIC}", 10)
    assert mixed > text_width("ab ", 10) and mixed > text_width(CYRILLIC, 10)


def test_pdf_embeds_the_unicode_font_only_when_text_needs_it() -> None:
    plain = render_pdf_document(ReportDocument(title="Report", blocks=[Heading("Intro", 1), Paragraph("café €")]))
    assert not any("DejaVu" in n for n in _fonts(plain))
    other = render_pdf_document(ReportDocument(title="Report", blocks=[Paragraph(CYRILLIC)]))
    assert any("DejaVuSans" in n and "Bold" not in n for n in _fonts(other))


def test_every_block_type_and_the_footer_print_other_scripts() -> None:
    blocks = [
        Heading(POLISH, 1), Paragraph(CYRILLIC), Note(GREEK), BulletList([CYRILLIC, "plain"]),
        Table([POLISH, "Name"], [[CYRILLIC, "x"], ["a", GREEK]], compact=True),
        Table([POLISH, "Name"], [[CYRILLIC, "x"]], col_widths_cm=[4, 4]),
    ]
    branding = ReportBranding(footer_text=f"{CYRILLIC} · Confidential", include_cover_page=True)
    pdf = render_pdf_document(ReportDocument(title=POLISH, blocks=blocks, branding=branding))
    fonts = _fonts(pdf)
    assert any("DejaVuSans-Bold" in n for n in fonts), "headings and table headers print bold"
    assert any(n.endswith("DejaVuSans") for n in fonts)


def test_plain_string_cells_become_paragraphs_only_when_needed() -> None:
    table = styled_table([["Name", "Note"], ["a", CYRILLIC], [POLISH, "b"]], col_widths=[100, 100], accent_color=colors.HexColor("#2f855a"))
    cells = table._cellvalues
    assert cells[0] == ["Name", "Note"] and cells[1][0] == "a"
    assert not isinstance(cells[1][1], str) and not isinstance(cells[2][0], str) and cells[2][1] == "b"


def test_footer_switches_font_per_run_and_is_centred() -> None:
    drawn: list[tuple[str, str, float]] = []

    class Recorder(Canvas):
        def setFont(self, name, size, leading=None):  # noqa: N802 - ReportLab's own method name
            self._last_font = name
            super().setFont(name, size, leading)

        def drawString(self, x, y, text, *args, **kwargs):  # noqa: N802
            drawn.append((self._last_font, text, x))
            super().drawString(x, y, text, *args, **kwargs)

    canvas = Recorder(io.BytesIO())
    draw_centred(canvas, 300, 20, f"Acme {CYRILLIC}", 7)
    assert [(font, text) for font, text, _ in drawn] == [("Helvetica", "Acme "), (UNICODE_FONT, "Привет"), ("Helvetica", " "), (UNICODE_FONT, "мир")]
    first_x = drawn[0][2]
    assert abs((300 - first_x) - text_width(f"Acme {CYRILLIC}", 7) / 2) < 0.01


# --- Document font families (the table every renderer will read) -------------------------------------------------

# The PDF standard fonts whose widths Arial, Times New Roman and Courier New share for the Latin letters,
# digits and punctuation a report uses; a Liberation face that drifts from them stops matching Word.
_STANDARD = {
    "sans": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "serif": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "mono": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}
# Characters where the Adobe core metrics and Microsoft's differ, so they are not a fair reference.
_NOT_COMPARABLE = set("¯±µ·÷")
_WRAP_CHARS = [chr(c) for c in range(32, 256) if not 127 <= c < 160 and chr(c) not in _NOT_COMPARABLE]


def test_families_are_the_closed_list():
    assert list(report_fonts.FAMILIES) == ["sans", "serif", "mono", "unicode"]
    with pytest.raises(KeyError):
        report_fonts.get_family("comic")


@pytest.mark.parametrize("key", list(report_fonts.FAMILIES))
def test_every_family_has_four_real_faces_with_a_licence_beside_them(key):
    family = report_fonts.get_family(key)
    assert list(family.files) == list(report_fonts.STYLES)
    for style, path in family.files.items():
        assert path.is_file(), f"{key} {style}"
        # ReportLab refuses to load a face whose licence forbids embedding, so loading is the licence check
        face = TTFont("probe", str(path)).face
        flags = (bool(face.flags & FF_FORCEBOLD), bool(face.flags & FF_ITALIC))
        assert flags == (style in ("bold", "bolditalic"), style in ("italic", "bolditalic")), (key, style)
    licence = "LICENSE_DEJAVU" if key == "unicode" else "LICENSE_LIBERATION"
    assert (next(iter(family.files.values())).parent / licence).is_file()


@pytest.mark.parametrize("key", ["sans", "serif", "mono"])
def test_liberation_widths_match_the_font_word_is_told(key):
    """Line breaks agree across formats only while the PDF face has the named font's advance widths."""
    report_fonts.register_family(key)
    family = report_fonts.get_family(key)
    for style, standard in zip(report_fonts.STYLES, _STANDARD[key], strict=True):
        for char in _WRAP_CHARS:
            ours = stringWidth(char, family.pdf_name(style), 1000)
            assert abs(ours - stringWidth(char, standard, 1000)) <= 1.0, (key, style, char)


def test_names_and_fallbacks_for_the_other_formats():
    assert [(f.word_name, f.generic, f.odf_generic) for f in list(report_fonts.FAMILIES.values())[:3]] == [
        ("Arial", "sans-serif", "swiss"), ("Times New Roman", "serif", "roman"), ("Courier New", "monospace", "modern"),
    ]
    assert report_fonts.get_family("serif").css_stack == '"Times New Roman", serif'
    assert report_fonts.get_family("unicode").word_name == "DejaVu Sans"


def test_pdf_face_registers_the_right_weight_and_slant():
    assert report_fonts.pdf_face("serif") == "Report-serif-regular"
    assert report_fonts.pdf_face("serif", bold=True, italic=True) == "Report-serif-bolditalic"
    assert report_fonts.pdf_face("mono", italic=True) == "Report-mono-italic"
    assert report_fonts.pdf_face("sans", bold=True) == "Report-sans-bold"  # registers the face the next line reads
    assert pdfmetrics.getFont("Report-sans-bold").face.name == b"LiberationSans-Bold"


@pytest.mark.parametrize("key", ["sans", "serif", "mono"])
def test_liberation_prints_latin_cyrillic_greek_and_polish_without_the_fallback(key):
    for char in CYRILLIC + POLISH + GREEK + "ÀÿŁłŐő€–—“”…":
        assert report_fonts.covers(key, char), (key, char)


@pytest.mark.parametrize("key", ["sans", "serif", "mono"])
def test_symbols_beyond_liberation_need_the_unicode_family(key):
    for char in "✓✔☐★":
        assert not report_fonts.covers(key, char)
        assert report_fonts.covers("unicode", char)
    assert report_fonts.covers(key, " ")


def test_the_unicode_family_has_real_italic_faces():
    """A fallback run in an italic paragraph has an oblique face, not the upright one."""
    report_fonts.register_family("unicode")
    assert pdfmetrics.getFont("Report-unicode-italic").face.name == b"DejaVuSans-Oblique"
    assert pdfmetrics.getFont("Report-unicode-bolditalic").face.name == b"DejaVuSans-BoldOblique"
    report_fonts.mark_fallback("✓")  # the existing fallback still registers its names
    assert pdfmetrics.getFont(UNICODE_FONT_BOLD).face.name == b"DejaVuSans-Bold"
    assert pdfmetrics.getFont(report_fonts.UNICODE_FONT_ITALIC).face.name == b"DejaVuSans-Oblique"
