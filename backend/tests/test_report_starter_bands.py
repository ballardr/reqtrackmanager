"""
Module: tests.test_report_starter_bands

The header and footer cells of every document starter, as each file format draws them.

Responsibilities:
- Pin the starters' band: none of them writes a header or footer, so each prints the default footer (the page number,
  centred), and the content-sized cell rule must leave that number centred, top aligned, on every paper size.
- Run each document starter in the preview, Word, OpenDocument and PDF formats and check the footer is drawn where
  that rule puts it.

Design decisions:
- The starters set no width or alignment of their own: the default footer has one filled cell, so the content-sized
  rule already gives the room to the centre and the empty sides the same floor. A starter that later needs a fixed
  logo cell sets it in its tree, and the first test fails until it is read as rendered.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile
import zlib

import pytest
from docx import Document as DocxDocument

from app.services.report_band_cells import resolve_band_cells
from app.services.report_model import PageStyle
from app.services.report_running import default_footer
from app.services.report_starters import STARTERS
from tests.conftest import auth_headers
from tests.link_world import World
from tests.test_report_starters import DOCUMENT_STARTER_NAMES, by_name, org_layouts

CM = 72 / 2.54


def test_no_starter_writes_a_header_or_footer_of_its_own():
    """A starter that adds a band must be re-read in all four formats, so this fails until its test is written."""
    for starter in STARTERS:
        tree = starter.tree
        assert "header" not in tree and "footer" not in tree, starter.name
        assert not [n for n in tree.get("nodes", []) if n.get("type") == "page_style"], starter.name


@pytest.mark.parametrize("paper", ["A4", "Letter", "A3"])
def test_the_default_footer_keeps_the_page_number_centred_and_bottom_aligned(paper: str):
    style = PageStyle(page_size=paper)
    left, centre, right = resolve_band_cells(default_footer(), style.usable_width_cm)
    assert left.width_cm == pytest.approx(right.width_cm)
    assert centre.width_cm == pytest.approx(style.usable_width_cm - 2 * left.width_cm)
    assert (left.valign, centre.valign, right.valign) == ("bottom", "bottom", "bottom")


def run(world: World, project: dict, name: str, fmt: str) -> bytes:
    layout = by_name(org_layouts(world), name)
    url = f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run"
    resp = world.client.get(url, params={"format": fmt}, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.content


def pdf_footer_x(pdf: bytes) -> list[float]:
    """The x of every text object low on the first page (the footer)."""
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            content = zlib.decompress(base64.a85decode(raw.strip(), adobe=True)).decode("latin-1")
        except Exception:  # noqa: BLE001 - a font or the document info, not a page
            continue
        found = [(float(x), float(y)) for x, y in re.findall(r"1 0 0 1 ([\d.]+) ([\d.]+) Tm \(", content)]
        low = [x for x, y in found if y < 80]
        if low:
            return low
    return []


@pytest.mark.parametrize("name", DOCUMENT_STARTER_NAMES)
def test_each_starter_draws_its_default_footer_in_every_format(client, admin_token, name):
    world = World(client, admin_token, "Starter Bands", decisions=True, context_strategy=True, keep_starter_layouts=True)
    world.enable("risk_management")
    world.enable("stakeholders")
    project = world.project("Banded")
    world.requirement(project, "The system shall log in users")
    landscape = next(s for s in STARTERS if s.name == name).orientation == "landscape"
    style = PageStyle(landscape=landscape)
    cells = resolve_band_cells(default_footer(), style.usable_width_cm)

    html = run(world, project, name, "html").decode()
    assert len(re.findall(r'<div class="band footer"', html)) >= 1
    fr = [float(v) for v in re.findall(r"minmax\(0, ([\d.]+)fr\)", html)[:3]]
    assert fr == pytest.approx([c.width_cm for c in cells], abs=0.001)
    assert 'class="pf"' in html

    word = DocxDocument(io.BytesIO(run(world, project, name, "docx")))
    xml = word.sections[0].footer._element.xml
    widths = [int(w) for w in re.findall(r'<w:tcW [^>]*w:w="(\d+)"', xml)]
    assert widths == pytest.approx([c.width_cm * 567 for c in cells], abs=2)
    assert "PAGE" in xml

    with zipfile.ZipFile(io.BytesIO(run(world, project, name, "odt"))) as archive:
        styles = archive.read("styles.xml").decode()
    assert "text:page-number" in styles

    xs = pdf_footer_x(run(world, project, name, "pdf"))
    assert xs, "the PDF has no footer text"
    page_centre = style.dimensions_cm[0] / 2 * CM
    assert min(abs(x - page_centre) for x in xs) < 25  # the number starts within a few characters of the page centre
