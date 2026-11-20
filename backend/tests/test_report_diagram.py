"""Tests for `services.report_diagram`: the client for the converter's `/diagram` route (against a stand-in server over real
HTTP), making the reply safe and sized, the drawing cache, the run's budget, and (where the real converter is reachable, as in
the container stack) real drawings of every diagram type."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.services import report_diagram
from app.services.report_diagram import MAX_DIAGRAMS_PER_RUN, UNAVAILABLE, DiagramBudget, DiagramError, DrawnDiagram, draw
from tests.test_report_converter import FakeConverter, _real_converter_url, converter  # noqa: F401 - the converter fixture

#: What the converter returns for a small flowchart: the engine's fixed drawing name, a style sheet and a relative size.
MERMAID_SVG = (
    '<svg id="my-svg" width="100%" xmlns="http://www.w3.org/2000/svg" style="max-width: 200px; background-color: white;" '
    'viewBox="4 4 200 100" role="graphics-document document">'
    '<style>#my-svg{font-family:"DejaVu Sans";font-size:16px;fill:#333;}#my-svg .node rect{fill:#ececff;stroke:#9370db;}'
    "#my-svg .label{animation:dash 5s;}@keyframes dash{to{stroke-dashoffset:0}}</style>"
    '<marker id="my-svg_pointEnd" markerWidth="8" markerHeight="8"><path d="M0,0L8,4L0,8z"/></marker>'
    '<g class="node"><rect width="100" height="40" marker-end="url(#my-svg_pointEnd)"/>'
    '<text x="10" y="20" class="label">Start &amp; <tspan>End</tspan></text><text x="10" y="30">Start</text></g></svg>'
)
FLOWCHART = "flowchart LR\n A-->B"


@pytest.fixture(autouse=True)
def _fresh_cache():
    report_diagram.clear_cache()
    yield
    report_diagram.clear_cache()


@pytest.fixture()
def drawn(converter):  # noqa: F811
    converter.reply = (200, MERMAID_SVG.encode(), "image/svg+xml")
    return converter


# ---- the client --------------------------------------------------------------------------------------------------


def test_the_text_and_theme_are_posted_as_json_to_the_diagram_route(drawn):
    draw(f"  {FLOWCHART}\n", "light")

    path, body, headers = drawn.requests[0]
    assert path == "/diagram" and headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"source": FLOWCHART, "theme": "light"}


def test_the_reply_is_flattened_sized_and_made_safe(drawn):
    result = draw(FLOWCHART)

    assert isinstance(result, DrawnDiagram)
    assert (result.width, result.height) == (200.0, 100.0)
    assert 'width="200" height="100"' in result.svg and "100%" not in result.svg
    assert "<style" not in result.svg and 'fill="#ececff"' in result.svg and 'stroke="#9370db"' in result.svg
    assert "animation" not in result.svg and "role=" not in result.svg


def test_every_drawing_has_its_own_identifiers(converter):  # noqa: F811
    converter.reply = (200, MERMAID_SVG.encode(), "image/svg+xml")
    first, second = draw("flowchart LR\n A-->B"), draw("flowchart LR\n C-->D")

    ids = [set(re.findall(r'id="([^"]+)"', d.svg)) for d in (first, second)]
    assert "my-svg" not in first.svg and ids[0].isdisjoint(ids[1])
    assert re.search(r'marker-end="url\(#diagram-[0-9a-f]{12}_pointEnd\)"', first.svg)


def test_the_text_alternative_lists_the_words_the_drawing_prints(drawn):
    assert draw(FLOWCHART).labels == "Start & End, Start"


def test_the_converters_reasons_are_shown_and_a_failure_is_a_plain_message(converter):  # noqa: F811
    converter.error(422, "Parse error on line 2")
    with pytest.raises(DiagramError, match="Parse error on line 2"):
        draw("nonsense")
    converter.error(503, "The converter is busy. Try again in a moment.")
    with pytest.raises(DiagramError, match="busy"):
        draw("nonsense")
    converter.reply = (500, b"Traceback (most recent call last): secret", "text/plain")
    with pytest.raises(DiagramError, match="could not be drawn") as caught:
        draw("nonsense")
    assert "Traceback" not in str(caught.value) and "secret" not in str(caught.value)


def test_an_empty_or_oversize_text_is_refused_before_the_converter_is_called(converter):  # noqa: F811
    for text in ("   ", "x" * 20_001):
        with pytest.raises(DiagramError):
            draw(text)

    assert converter.requests == []


def test_an_unconfigured_or_unreachable_converter_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(get_settings(), "report_converter_url", "")
    with pytest.raises(DiagramError, match="not available"):
        draw(FLOWCHART)
    monkeypatch.setattr(get_settings(), "report_converter_url", "http://127.0.0.1:1")
    with pytest.raises(DiagramError) as caught:
        draw(FLOWCHART)
    assert str(caught.value) == UNAVAILABLE and report_diagram.is_configured()


def test_a_huge_reply_is_cut_off_rather_than_held_in_memory(drawn, monkeypatch):
    monkeypatch.setattr(report_diagram, "MAX_REPLY_BYTES", 100)

    with pytest.raises(DiagramError, match="too large"):
        draw(FLOWCHART)


# ---- the reply is never trusted ------------------------------------------------------------------------------------


@pytest.mark.parametrize("hostile, kept_out", [
    ('<script>alert(1)</script><rect id="r" width="5" height="5" onclick="x()"/>', ("script", "onclick")),
    ('<foreignObject><div>hi</div></foreignObject><rect width="5" height="5"/>', ("foreignObject", "<div")),
    ('<image href="http://evil.example/x.png" width="5" height="5"/><rect width="5" height="5"/>', ("evil.example", "<image")),
    ('<a href="javascript:alert(1)"><rect width="5" height="5"/></a>', ("javascript", "<a")),
])
def test_script_and_external_content_in_a_drawing_never_reach_the_document(converter, hostile, kept_out):  # noqa: F811
    converter.reply = (200, f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">{hostile}</svg>'.encode(), "image/svg+xml")

    result = draw(FLOWCHART)

    assert all(word not in result.svg for word in kept_out)


@pytest.mark.parametrize("css", [
    "#my-svg .node rect{fill:url(http://evil.example/x)}",
    "#my-svg .node rect{fill:url(javascript:alert(1))}",
])
def test_a_style_sheet_that_points_outside_the_drawing_makes_the_drawing_unusable_not_the_report(converter, css):  # noqa: F811
    svg = MERMAID_SVG.replace("</style>", css + "</style>")
    converter.reply = (200, svg.encode(), "image/svg+xml")

    with pytest.raises(DiagramError, match="could not be used"):
        draw(FLOWCHART)


def test_a_style_sheet_cannot_restyle_anything_outside_the_drawing(converter):  # noqa: F811
    svg = MERMAID_SVG.replace("</style>", "body{background:url(http://evil.example/)}@import url(http://evil.example/x.css);</style>")
    converter.reply = (200, svg.encode(), "image/svg+xml")

    result = draw(FLOWCHART)

    assert "evil.example" not in result.svg and "<style" not in result.svg


def test_an_entity_declaration_or_malformed_reply_is_refused(converter):  # noqa: F811
    for reply in (
        '<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect/></svg>',
        "<svg", "not a drawing", '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>',
    ):
        converter.reply = (200, reply.encode(), "image/svg+xml")
        with pytest.raises(DiagramError):
            draw(FLOWCHART)
        report_diagram.clear_cache()


# ---- the cache -----------------------------------------------------------------------------------------------------


def test_a_diagram_is_drawn_once_and_a_different_text_or_theme_is_drawn_again(drawn):
    draw(FLOWCHART)
    draw(FLOWCHART)
    assert len(drawn.requests) == 1

    draw(FLOWCHART + "\n B-->C")
    draw(FLOWCHART, "dark")
    assert len(drawn.requests) == 3


def test_a_failure_is_not_cached(converter):  # noqa: F811
    converter.error(422, "bad")
    with pytest.raises(DiagramError):
        draw(FLOWCHART)
    converter.reply = (200, MERMAID_SVG.encode(), "image/svg+xml")

    assert draw(FLOWCHART).width == 200.0


def test_the_key_names_the_mermaid_version_so_an_upgrade_draws_everything_again():
    key = report_diagram.cache_key(FLOWCHART, "light")

    assert key != report_diagram.cache_key(FLOWCHART, "dark") and key != report_diagram.cache_key(FLOWCHART + " ", "light")
    original = report_diagram.MERMAID_VERSION
    try:
        report_diagram.MERMAID_VERSION = "99.0.0"
        assert report_diagram.cache_key(FLOWCHART, "light") != key
    finally:
        report_diagram.MERMAID_VERSION = original


def test_the_cache_is_bounded(drawn, monkeypatch):
    monkeypatch.setattr(report_diagram, "CACHE_MAX_ENTRIES", 3)
    for number in range(6):
        draw(f"flowchart LR\n A-->N{number}")
    first_again = len(drawn.requests)
    draw("flowchart LR\n A-->N5")  # the newest is still held
    draw("flowchart LR\n A-->N0")  # the oldest is not

    assert len(drawn.requests) == first_again + 1


# ---- the run's budget ------------------------------------------------------------------------------------------------


def test_a_run_draws_at_most_its_number_of_diagrams_and_cached_ones_do_not_count(drawn):
    budget = DiagramBudget(max_diagrams=2)
    budget.draw("flowchart LR\n A-->B")
    budget.draw("flowchart LR\n A-->C")
    budget.draw("flowchart LR\n A-->B")  # cached: free
    with pytest.raises(DiagramError, match="at most 2 diagrams"):
        budget.draw("flowchart LR\n A-->D")

    assert len(drawn.requests) == 2 and MAX_DIAGRAMS_PER_RUN >= 20  # a field may hold 20, so the budget covers a full field


def test_a_run_stops_drawing_when_its_time_is_spent(drawn, monkeypatch):
    clock = iter([0.0, 5.0])  # the first drawing starts at 0 and ends at 5 seconds
    monkeypatch.setattr(report_diagram, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    budget = DiagramBudget(max_seconds=2.0)
    budget.draw("flowchart LR\n A-->B")

    with pytest.raises(DiagramError, match="took too long"):
        budget.draw("flowchart LR\n A-->C")


def test_after_the_converter_fails_the_rest_of_the_run_does_not_try_again(monkeypatch):
    monkeypatch.setattr(get_settings(), "report_converter_url", "http://127.0.0.1:1")
    budget = DiagramBudget()
    with pytest.raises(DiagramError):
        budget.draw("flowchart LR\n A-->B")
    monkeypatch.setattr(report_diagram, "_post", lambda *_: pytest.fail("the converter was asked again"))

    with pytest.raises(DiagramError, match="not available"):
        budget.draw("flowchart LR\n A-->C")


def test_a_refused_diagram_does_not_stop_the_others(converter):  # noqa: F811
    budget = DiagramBudget()
    converter.error(422, "Parse error")
    with pytest.raises(DiagramError, match="Parse error"):
        budget.draw("nonsense")
    converter.reply = (200, MERMAID_SVG.encode(), "image/svg+xml")

    assert budget.draw(FLOWCHART).width == 200.0


# ---- the real converter (reachable in the container stack, skipped elsewhere) ---------------------------------------

#: One diagram of each of the families the converter draws differently (the converter's own tests draw all 38 types).
REAL_DIAGRAMS = {
    "flowchart": "flowchart TD\n A[Start] --> B{Decision?}\n B -- Yes --> C[Do it]\n B -- No --> D[(Store)]\n C --> E((End))\n D --> E",
    "sequence": "sequenceDiagram\n autonumber\n A->>B: Hello\n B-->>A: Great\n Note over A,B: A note",
    "class": "classDiagram\n Animal <|-- Duck\n Animal : +int age\n class Duck{\n +swim()\n }",
    "state": "stateDiagram-v2\n [*] --> Still\n Still --> Moving\n Moving --> [*]",
    "er": "erDiagram\n CUSTOMER ||--o{ ORDER : places\n CUSTOMER { string name }",
    "gantt": "gantt\n dateFormat YYYY-MM-DD\n section S\n A task :a1, 2024-01-01, 30d",
    "pie": 'pie showData\n "A" : 40\n "B" : 60',
    "mindmap": "mindmap\n root((mindmap))\n  Origins\n  Tools",
}
needs_converter = pytest.mark.skipif(not _real_converter_url(), reason="the diagram converter is not reachable from this host")


@needs_converter
@pytest.mark.parametrize("name", list(REAL_DIAGRAMS))
def test_a_real_diagram_is_drawn_safe_and_sized(name):
    result = draw(REAL_DIAGRAMS[name])

    assert result.width > 0 and result.height > 0 and result.svg.startswith("<svg")
    assert "<style" not in result.svg and "<script" not in result.svg and "<foreignObject" not in result.svg.lower()
    assert "my-svg" not in result.svg and result.labels or name in ("gantt", "mindmap")


@needs_converter
def test_a_real_refused_diagram_gives_the_librarys_message():
    with pytest.raises(DiagramError):
        draw("this is not a diagram")


@needs_converter
def test_a_real_drawing_prints_through_every_format(tmp_path):
    from app.services.report_docx import render_docx_document
    from app.services.report_html import render_html_document
    from app.services.report_markdown import record_markdown_blocks
    from app.services.report_model import ReportDocument
    from app.services.report_odt import render_odt_document
    from app.services.report_pdf import render_pdf_document

    blocks = record_markdown_blocks(f"```mermaid\n{REAL_DIAGRAMS['flowchart']}\n```\n", diagrams=DiagramBudget())
    document = ReportDocument("Real", blocks)

    assert b"<svg" in render_html_document(document)
    assert all(len(render(document)) > 5_000 for render in (render_pdf_document, render_docx_document, render_odt_document))
