"""
Module: tests.test_diagram_config

Pins the agreement between everything that draws a Mermaid diagram: the interface (`mermaidRenderConfig.json`), the converter
that draws it for reports (`diagram_config.json`, its requirements and its tests' corpus) and the backend's own constants. A
diagram reads the same in a report as on the screen only while they agree, so a change to one without the others fails here.
"""

import json
from pathlib import Path

import pytest

from app.services import markdown_text, report_diagram

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
CONVERTER = ROOT / "converter"

pytestmark = pytest.mark.skipif(
    not CONVERTER.is_dir() or not FRONTEND.is_dir(), reason="frontend and converter sources are not available (backend-only image)",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_converter_draws_with_the_version_font_and_limits_of_the_screen() -> None:
    screen = load(FRONTEND / "src" / "utils" / "mermaidRenderConfig.json")
    server = load(CONVERTER / "diagram_config.json")

    assert server["version"] == screen["version"]
    assert server["fontFamily"] == screen["fontFamily"]
    assert {key: server["limits"][key] for key in ("sourceChars", "elements", "edges", "renderMilliseconds")} == screen["limits"]


def test_the_backends_constants_are_the_same_version_font_and_limit() -> None:
    screen = load(FRONTEND / "src" / "utils" / "mermaidRenderConfig.json")

    assert report_diagram.MERMAID_VERSION == screen["version"]
    assert report_diagram.FONT_FAMILY == screen["fontFamily"]
    assert markdown_text.MAX_MERMAID_SOURCE_CHARS == screen["limits"]["sourceChars"]


def test_the_screen_draws_with_the_exact_package_that_names_the_version() -> None:
    screen = load(FRONTEND / "src" / "utils" / "mermaidRenderConfig.json")

    assert load(FRONTEND / "package.json")["dependencies"]["mermaid"] == screen["version"]


def test_the_servers_own_time_limit_is_longer_than_the_screens() -> None:
    """The server's engine is an interpreter, far slower than a browser, so the same limit would refuse diagrams the screen draws."""
    server = load(CONVERTER / "diagram_config.json")

    assert server["serverRenderMilliseconds"] > server["limits"]["renderMilliseconds"]


def test_the_renderer_and_its_engine_are_pinned_to_exact_versions() -> None:
    lines = [line.strip() for line in (CONVERTER / "requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]

    assert sorted(line.split("==")[0] for line in lines) == ["mermaidx", "novasvg", "quickjs-ng"]
    assert all("==" in line for line in lines)


def test_the_shared_corpus_and_the_reference_are_the_same_files_in_the_interface_and_the_converter() -> None:
    for name, copy in (("diagram_corpus.json", "diagramCorpus.json"), ("diagram_reference.json", "diagramReference.json")):
        assert (CONVERTER / "tests" / name).read_bytes() == (FRONTEND / "src" / "utils" / copy).read_bytes(), (
            f"{copy} differs from converter/tests/{name}; run `node scripts/generate-diagram-reference.mjs` in frontend/"
        )


def test_the_reference_covers_every_diagram_of_the_corpus() -> None:
    corpus = load(CONVERTER / "tests" / "diagram_corpus.json")
    reference = load(CONVERTER / "tests" / "diagram_reference.json")

    assert [entry["name"] for entry in corpus] == [entry["name"] for entry in reference]
