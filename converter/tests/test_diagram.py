"""Tests for the diagram renderer: every Mermaid diagram type in the shared corpus is drawn and agrees with what the
browser draws (the reference file), hostile and runaway diagrams are stopped within the limits, and the HTTP route.
Run inside the container: `python -m unittest discover -s tests`."""

from __future__ import annotations

import http.client
import json
import re
import sys
import threading
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import converter  # noqa: E402

HERE = Path(__file__).resolve().parent
CORPUS = json.loads((HERE / "diagram_corpus.json").read_text(encoding="utf-8"))
REFERENCE = {entry["name"]: entry for entry in json.loads((HERE / "diagram_reference.json").read_text(encoding="utf-8"))}
#: How far a drawing's size may differ from the browser's, by the corpus entry's `size` kind (`container` is not compared).
SIZE_TOLERANCE = {"fixed": 0.05, "font": 0.15}


def structure(svg: str) -> tuple[float, float, Counter[str]]:
    """The size and the printed words of a drawing, read as `scripts/generate-diagram-reference.mjs` reads them."""
    root = ET.fromstring(svg)
    box = [float(part) for part in re.split(r"[ ,]+", root.get("viewBox", "0 0 0 0").strip())]
    words: Counter[str] = Counter()
    for element in root.iter():
        if element.tag.split("}")[-1] in ("text", "tspan", "title", "desc") and element.text:
            for token in element.text.split():
                word = token[:-1] if token.endswith("/") else token  # the reference drops one trailing "/"
                if word and not re.fullmatch(r"\d+-[0-9a-f]{7}", word):
                    words[word] += 1
    return box[2], box[3], words


class Agreement(unittest.TestCase):
    def test_the_corpus_and_the_reference_name_the_same_diagrams(self) -> None:
        self.assertEqual([entry["name"] for entry in CORPUS], list(REFERENCE))

    def test_every_diagram_in_the_corpus_is_drawn_as_the_browser_draws_it(self) -> None:
        for entry in CORPUS:
            with self.subTest(diagram=entry["name"]):
                width, height, words = structure(converter.render_diagram(entry["source"], "light").decode())
                expected = REFERENCE[entry["name"]]
                self.assertEqual(words, Counter(expected["words"]), "the words printed differ")
                tolerance = SIZE_TOLERANCE.get(entry["size"])
                if tolerance is not None and expected["width"]:
                    self.assertAlmostEqual(width / expected["width"], 1, delta=tolerance, msg="width")
                    self.assertAlmostEqual(height / expected["height"], 1, delta=tolerance, msg="height")

    def test_the_renderer_is_the_mermaid_version_the_screen_uses(self) -> None:
        svg = converter.render_diagram("info", "light").decode()
        self.assertIn(f"v{converter.DIAGRAM_CONFIG['version']}", svg)

    def test_the_dark_theme_draws_with_dark_colours(self) -> None:
        light = converter.render_diagram("flowchart LR\n A-->B", "light").decode()
        dark = converter.render_diagram("flowchart LR\n A-->B", "dark").decode()
        self.assertNotEqual(light, dark)


class Limits(unittest.TestCase):
    def test_empty_oversize_and_unknown_theme_are_refused_before_anything_runs(self) -> None:
        for source, theme, message in (
            ("  \n ", "light", "empty"),
            ("x" * (converter.DIAGRAM_CONFIG["limits"]["sourceChars"] + 1), "light", "over the limit"),
            ("flowchart LR\n A-->B", "sepia", "theme"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(converter.ConversionError, message):
                converter.render_diagram(source, theme)

    def test_text_mermaid_cannot_read_is_refused_with_its_message(self) -> None:
        with self.assertRaises(converter.ConversionError) as caught:
            converter.render_diagram("this is not a diagram", "light")
        self.assertIn("diagram", str(caught.exception).lower())

    def test_a_runaway_layout_is_killed_at_the_time_limit(self) -> None:
        runaway = "flowchart TD\nA[" + "x" * 19000 + "]"
        with mock.patch.object(converter, "DIAGRAM_TIMEOUT_SECONDS", 3), self.assertRaisesRegex(converter.ConversionError, "too long"):
            converter.render_diagram(runaway, "light")

    def test_a_drawing_with_too_many_elements_is_refused_as_the_screen_refuses_it(self) -> None:
        limits = {**converter.DIAGRAM_CONFIG["limits"], "elements": 20}
        with mock.patch.dict(converter.DIAGRAM_CONFIG, {"limits": limits}), self.assertRaisesRegex(converter.ConversionError, "too large"):
            converter.render_diagram("flowchart TD\n A-->B-->C-->D", "light")

    def test_script_in_a_label_is_not_markup_in_the_drawing(self) -> None:
        svg = converter.render_diagram('flowchart LR\n A["<script>alert(1)</script>"] --> B["<img src=x onerror=alert(1)>"]', "light").decode()
        self.assertNotIn("<script", svg.lower())
        self.assertNotIn("<img", svg.lower())

    def test_a_directive_cannot_lift_the_size_limits(self) -> None:
        source = "%%{init: {'maxTextSize': 99999999, 'securityLevel': 'loose'}}%%\nflowchart TD\n A[" + "x" * 100 + "]"
        self.assertIn(b"<svg", converter.render_diagram(source, "light"))

    def test_a_missing_renderer_is_reported_as_missing(self) -> None:
        with mock.patch.object(converter, "diagram_renderer_available", return_value=False), self.assertRaises(converter.ToolMissingError):
            converter.render_diagram("flowchart LR\n A-->B", "light")


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = converter.make_server(0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def post(self, body: bytes) -> tuple[int, str | None, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=90)
        try:
            connection.request("POST", "/diagram", body=body)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()

    def test_a_diagram_comes_back_as_svg(self) -> None:
        status, kind, payload = self.post(json.dumps({"source": "flowchart LR\n A-->B", "theme": "light"}).encode())
        self.assertEqual((status, kind), (200, "image/svg+xml"))
        self.assertIn(b"<svg", payload)

    def test_a_bad_request_or_a_refused_diagram_returns_a_plain_message(self) -> None:
        for body in (b"not json", b'["a list"]', b'{"theme": "light"}', json.dumps({"source": "nonsense", "theme": "light"}).encode()):
            status, _, payload = self.post(body)
            self.assertEqual(status, 422, body)
            self.assertIn("detail", json.loads(payload))

    def test_an_oversize_body_is_refused_without_being_read(self) -> None:
        with mock.patch.object(converter, "MAX_DIAGRAM_REQUEST_BYTES", 10):
            self.assertEqual(self.post(b"x" * 11)[0], 413)


if __name__ == "__main__":
    unittest.main()
