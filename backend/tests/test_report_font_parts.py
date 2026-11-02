"""Tests for declaring and embedding administrator-provided fonts in finished Word and OpenDocument files
(`services.report_font_parts`). Fonts are copies of the bundled Liberation Mono; documents come from the real renderers."""

from __future__ import annotations

import io
import shutil
import uuid
import zipfile
from pathlib import Path

import pytest
from docx import Document
from lxml import etree

from app.config import get_settings
from app.services import report_font_catalogue as catalogue
from app.services import report_fonts
from app.services.report_docx import render_docx_document
from app.services.report_font_parts import FontUse, _obfuscate, embed_in_docx, embed_in_odt, fallback_name
from app.services.report_model import Heading, Paragraph, ReportDocument
from app.services.report_odt import render_odt_document

_LIBERATION = Path(report_fonts.__file__).resolve().parent.parent / "assets" / "report_fonts"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture
def use(tmp_path, monkeypatch) -> FontUse:
    """A FontUse for 'Courier Prime' (regular and bold files) as the administrator would have set it up."""
    directory = tmp_path / "fonts"
    directory.mkdir()
    for style in ("Regular", "Bold"):
        shutil.copyfile(_LIBERATION / f"LiberationMono-{style}.ttf", directory / f"mono-{style}.ttf")
    monkeypatch.setenv("REPORT_FONTS_DIR", str(directory))
    get_settings.cache_clear()
    catalogue.reset()
    family = catalogue.rescan().families["x-liberation-mono"]
    from dataclasses import replace

    yield FontUse(replace(family, word_name="Courier Prime", generic="monospace"), frozenset({"regular", "bold", "italic"}))
    get_settings.cache_clear()
    catalogue.reset()


def _docx() -> bytes:
    return render_docx_document(ReportDocument("Fonts", [Heading("Heading", 1), Paragraph("Some text")]))


def _odt() -> bytes:
    return render_odt_document(ReportDocument("Fonts", [Heading("Heading", 1), Paragraph("Some text")]))


def test_fallback_names():
    assert [fallback_name(g) for g in ("sans-serif", "serif", "monospace")] == ["Arial", "Times New Roman", "Courier New"]


def test_no_fonts_returns_the_file_unchanged():
    data = _docx()
    assert embed_in_docx(data, [], embed=True) is data
    odt = _odt()
    assert embed_in_odt(odt, [], embed=True) is odt


def test_docx_declares_without_embedding(use):
    out = embed_in_docx(_docx(), [use], embed=False)
    zf = zipfile.ZipFile(io.BytesIO(out))
    assert not [n for n in zf.namelist() if n.endswith(".odttf")]
    font = next(f for f in etree.fromstring(zf.read("word/fontTable.xml")) if f.get(f"{W}name") == "Courier Prime")
    assert [etree.QName(c).localname for c in font] == ["altName", "charset", "family", "pitch"]
    assert font.find(f"{W}altName").get(f"{W}val") == "Courier New" and font.find(f"{W}pitch").get(f"{W}val") == "fixed"
    assert b"embedTrueTypeFonts" not in zf.read("word/settings.xml")
    Document(io.BytesIO(out))  # still a valid Word file


def test_docx_embeds_only_used_real_faces_in_schema_order(use):
    out = embed_in_docx(_docx(), [use], embed=True)
    zf = zipfile.ZipFile(io.BytesIO(out))
    parts = sorted(n for n in zf.namelist() if n.endswith(".odttf"))
    assert len(parts) == 2  # regular and bold are real files; italic is not, so it is never faked
    font = next(f for f in etree.fromstring(zf.read("word/fontTable.xml")) if f.get(f"{W}name") == "Courier Prime")
    assert [etree.QName(c).localname for c in font] == ["altName", "charset", "family", "pitch", "embedRegular", "embedBold"]
    rels = etree.fromstring(zf.read("word/_rels/fontTable.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels}
    regular = font.find(f"{W}embedRegular")
    rid = regular.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    assert targets[rid].startswith("fonts/font") and f"word/{targets[rid]}" in parts
    # The part is the font with its first 32 bytes masked by the key; unmasking restores the original.
    key = uuid.UUID(regular.get(f"{W}fontKey").strip("{}"))
    original = (_LIBERATION / "LiberationMono-Regular.ttf").read_bytes()
    stored = zf.read(f"word/{targets[rid]}")
    assert stored != original and stored[32:] == original[32:] and _obfuscate(stored, key) == original
    settings = etree.fromstring(zf.read("word/settings.xml"))
    names = [etree.QName(c).localname for c in settings]
    assert "embedTrueTypeFonts" in names
    for later in ("compat", "rsids", "themeFontLang", "decimalSymbol"):
        if later in names:
            assert names.index("embedTrueTypeFonts") < names.index(later)
    assert b'Extension="odttf"' in zf.read("[Content_Types].xml")
    Document(io.BytesIO(out))


def test_docx_output_is_deterministic(use):
    data = _docx()
    assert embed_in_docx(data, [use], embed=True) == embed_in_docx(data, [use], embed=True)


def test_docx_that_is_not_word_is_refused():
    with pytest.raises(ValueError):
        embed_in_docx(b"not a zip", [FontUse(report_fonts.FAMILIES["sans"], frozenset())], embed=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("x", "y")
    with pytest.raises(ValueError):
        embed_in_docx(buffer.getvalue(), [FontUse(report_fonts.FAMILIES["sans"], frozenset())], embed=True)


def test_odt_declares_and_embeds(use):
    out = embed_in_odt(_odt(), [use], embed=True)
    zf = zipfile.ZipFile(io.BytesIO(out))
    assert zf.namelist()[0] == "mimetype" and zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
    assert zf.read("Fonts/x-liberation-mono-regular.ttf") == (_LIBERATION / "LiberationMono-Regular.ttf").read_bytes()
    assert "Fonts/x-liberation-mono-italic.ttf" not in zf.namelist()
    manifest = zf.read("META-INF/manifest.xml").decode()
    assert 'full-path="Fonts/x-liberation-mono-bold.ttf"' in manifest and "application/x-font-ttf" in manifest
    ns = {"style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0", "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
          "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0"}
    for part in ("content.xml", "styles.xml"):
        decls = etree.fromstring(zf.read(part)).find("office:font-face-decls", ns)
        faces = [f for f in decls if f.get(f"{{{ns['style']}}}name") == "Courier Prime"]
        assert len(faces) == 2
        assert {f.get(f"{{{ns['svg']}}}font-weight") for f in faces} == {"normal", "bold"}
        assert faces[0].get(f"{{{ns['style']}}}font-family-generic") == "modern"
        assert any(f.get(f"{{{ns['style']}}}name") == "Arial" for f in decls)  # the writer's own declaration is kept


def test_odt_without_embedding_declares_one_face(use):
    zf = zipfile.ZipFile(io.BytesIO(embed_in_odt(_odt(), [use], embed=False)))
    assert not [n for n in zf.namelist() if n.startswith("Fonts/")]
    content = zf.read("content.xml").decode()
    assert content.count('style:name="Courier Prime"') == 1 and "font-face-src" not in content


def test_odt_that_is_not_opendocument_is_refused():
    with pytest.raises(ValueError):
        embed_in_odt(b"nope", [FontUse(report_fonts.FAMILIES["sans"], frozenset())], embed=False)
