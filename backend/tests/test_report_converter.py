"""Tests for EPS and PDF logos: recognising the files, the client for the converter service (against a stand-in server
over real HTTP), the upload path that stores an SVG, and (where the real converter is reachable, as in the container
stack) true conversions including a hostile file."""

from __future__ import annotations

import json
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.config import get_settings
from app.services import report_converter, report_images
from app.services.report_converter import ConversionError, eps_to_svg, is_eps, is_pdf, pdf_to_svg
from app.services.report_images import ImageRejectedError, prepare_upload
from tests.conftest import auth_headers
from tests.test_report_images import World, project_images, upload, world  # noqa: F401 - the world fixture

BOX_EPS = b"""%!PS-Adobe-3.0 EPSF-3.0
%%BoundingBox: 0 0 100 50
newpath 0 0 100 50 rectfill
1 0 0 setrgbcolor 10 10 80 30 rectfill
0 0 1 setrgbcolor 50 25 12 0 360 arc fill
/Helvetica findfont 14 scalefont setfont 0 setgray 5 2 moveto (EPS) show
showpage
"""
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
SAFE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#cc0000"/></svg>'


def dos_eps(postscript: bytes) -> bytes:
    """The binary DOS EPS wrapper: a 30-byte header pointing at the PostScript section, which follows it."""
    header = b"\xc5\xd0\xd3\xc6" + struct.pack("<IIIIIIH", 30, len(postscript), 0, 0, 0, 0, 0xFFFF)
    return header + postscript


class FakeConverter:
    """A stand-in converter on a free local port: records requests and answers with whatever `reply` says."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, bytes, dict]] = []
        self.reply: tuple[int, bytes, str] = (200, SAFE_SVG.encode(), "image/svg+xml")
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append((self.path, body, dict(self.headers)))
                status, payload, kind = outer.reply
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def error(self, status: int, detail: str) -> None:
        self.reply = (status, json.dumps({"detail": detail}).encode(), "application/json")


@pytest.fixture()
def converter(monkeypatch):
    fake = FakeConverter()
    monkeypatch.setattr(get_settings(), "report_converter_url", fake.url)
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


# ---- recognising -------------------------------------------------------------------------------------------------


def test_files_are_recognised_by_their_bytes_not_their_name():
    assert is_eps(BOX_EPS) and is_eps(dos_eps(BOX_EPS))
    assert not is_eps(b"<svg xmlns='http://www.w3.org/2000/svg'/>") and not is_eps(b"\x89PNG\r\n") and not is_eps(b"")
    assert is_pdf(PDF) and is_pdf(b"\n\n" + PDF)
    assert not is_pdf(BOX_EPS) and not is_pdf(b"x" * 2000 + b"%PDF-") and not is_pdf(b"")


# ---- the client --------------------------------------------------------------------------------------------------


def test_the_file_is_posted_to_the_matching_route_and_the_reply_is_sanitised(converter):
    hostile = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><rect width="5" height="5" onclick="x()"/></svg>'
    converter.reply = (200, hostile.encode(), "image/svg+xml")

    svg = eps_to_svg(BOX_EPS)

    assert "<rect" in svg and "script" not in svg and "onclick" not in svg  # the converter's reply is never trusted
    path, body, headers = converter.requests[0]
    assert path == "/convert/eps" and body == BOX_EPS and headers["Content-Type"] == "application/octet-stream"
    assert "<rect" in pdf_to_svg(PDF) and converter.requests[1][0] == "/convert/pdf"


def test_a_hostile_reply_is_refused(converter):
    entity = '<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
    converter.reply = (200, entity.encode(), "image/svg+xml")
    with pytest.raises(ConversionError, match="could not be used"):
        eps_to_svg(BOX_EPS)


def test_a_reply_with_nothing_drawable_is_refused(converter):
    undecodable = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><image href="data:image/png;base64,AAAA"/></svg>'
    converter.reply = (200, undecodable.encode(), "image/svg+xml")
    with pytest.raises(ConversionError, match="nothing a report can print"):
        eps_to_svg(BOX_EPS)


def test_the_converters_reasons_are_shown_and_a_failure_is_a_plain_message(converter):
    converter.error(422, "The file took too long to convert.")
    with pytest.raises(ConversionError, match="too long to convert. Export an SVG or PNG instead"):
        pdf_to_svg(PDF)
    converter.error(503, "The converter is busy. Try again in a moment.")
    with pytest.raises(ConversionError, match="busy"):
        pdf_to_svg(PDF)
    converter.reply = (413, b"", "text/plain")
    with pytest.raises(ConversionError, match="too large"):
        pdf_to_svg(PDF)
    converter.reply = (500, b"Traceback (most recent call last): secret", "text/plain")
    with pytest.raises(ConversionError, match="could not be converted") as caught:
        pdf_to_svg(PDF)
    assert "Traceback" not in str(caught.value) and "secret" not in str(caught.value)


def test_an_unconfigured_or_unreachable_converter_is_not_available(monkeypatch):
    monkeypatch.setattr(get_settings(), "report_converter_url", "")
    with pytest.raises(ConversionError, match="converter is not available"):
        eps_to_svg(BOX_EPS)
    monkeypatch.setattr(get_settings(), "report_converter_url", "http://127.0.0.1:1")  # nothing listens here
    with pytest.raises(ConversionError, match="converter is not available"):
        eps_to_svg(BOX_EPS)


def test_a_huge_reply_is_cut_off_rather_than_held_in_memory(converter, monkeypatch):
    monkeypatch.setattr(report_converter, "MAX_REPLY_BYTES", 100)
    converter.reply = (200, b"<svg xmlns='http://www.w3.org/2000/svg'>" + b"<g/>" * 100 + b"</svg>", "image/svg+xml")
    with pytest.raises(ConversionError, match="too complex"):
        eps_to_svg(BOX_EPS)


def test_redirects_and_proxy_settings_are_not_followed(converter, monkeypatch):
    seen: dict = {}
    real = httpx.Client

    class Spy(real):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(report_converter.httpx, "Client", Spy)
    eps_to_svg(BOX_EPS)
    assert seen["follow_redirects"] is False and seen["trust_env"] is False


# ---- the upload path ---------------------------------------------------------------------------------------------


def test_prepare_upload_stores_a_converted_file_as_an_svg_and_leaves_other_files_alone(converter):
    name, data = prepare_upload("Logo.EPS", BOX_EPS)
    assert name == "Logo.EPS.svg" and b"<rect" in data
    assert prepare_upload("art.ps", dos_eps(BOX_EPS))[0] == "art.ps.svg"
    name, data = prepare_upload("brand.pdf", PDF)
    assert name == "brand.pdf.svg" and b"<rect" in data and [r[0] for r in converter.requests][-1] == "/convert/pdf"
    n = len(converter.requests)
    assert prepare_upload("pic.png", b"\x89PNG") == ("pic.png", b"\x89PNG")
    assert prepare_upload("a.svg", SAFE_SVG.encode()) == ("a.svg", SAFE_SVG.encode())
    assert len(converter.requests) == n  # only an EPS or PDF reaches the converter


def test_a_file_over_the_size_limit_is_refused_before_the_converter_is_called(converter, monkeypatch):
    monkeypatch.setattr(report_images, "max_image_bytes", lambda: 10)
    for data in (BOX_EPS, PDF):
        with pytest.raises(ImageRejectedError, match="too large"):
            prepare_upload("big", data)
    assert converter.requests == []


def test_the_library_listing_says_whether_eps_and_pdf_can_be_uploaded(world: World, monkeypatch):  # noqa: F811
    project = world.project("Alpha")
    url = project_images(project)
    headers = auth_headers(world.token)

    monkeypatch.setattr(get_settings(), "report_converter_url", "")
    assert world.client.get(url, headers=headers).json()["converter_available"] is False
    refused = upload(world, url, BOX_EPS, "logo.eps")
    assert refused.status_code == 422 and "converter is not available" in refused.json()["detail"]
    assert upload(world, url, PDF, "brand.pdf").status_code == 422

    monkeypatch.setattr(get_settings(), "report_converter_url", "http://converter:8300")
    assert world.client.get(url, headers=headers).json()["converter_available"] is True


def test_the_library_upload_route_stores_the_svg_and_gives_the_reason_for_a_refusal(world: World, converter):  # noqa: F811
    project = world.project("Alpha")
    resp = upload(world, project_images(project), BOX_EPS, "logo.eps")
    assert resp.status_code == 201, resp.text
    assert resp.json()["content_type"] == "image/svg+xml" and resp.json()["filename"] == "logo.eps.svg"
    assert upload(world, project_images(project), PDF, "brand.pdf").json()["filename"] == "brand.pdf.svg"

    converter.error(422, "The file could not be read.")
    bad = upload(world, project_images(project), BOX_EPS, "bad.eps")
    assert bad.status_code == 422 and "Export an SVG or PNG" in bad.json()["detail"]


def test_neither_format_is_a_picture_for_a_record_attachment():
    # Only the library upload converts; a stored attachment is never sent to the converter at report time.
    for data in (BOX_EPS, PDF):
        with pytest.raises(ImageRejectedError):
            report_images.sniff_image(data)


# ---- the real converter (reachable in the container stack, skipped elsewhere) ---------------------------------------


def _real_converter_url() -> str:
    """The configured converter URL if something answers its health probe, else an empty string."""
    url = get_settings().report_converter_url.strip().rstrip("/")
    if not url:
        return ""
    try:
        return url if httpx.get(f"{url}/health", timeout=3, trust_env=False).status_code == 200 else ""
    except httpx.HTTPError:
        return ""


needs_converter = pytest.mark.skipif(not _real_converter_url(), reason="the picture converter is not reachable from this host")


@needs_converter
def test_a_real_eps_and_a_real_dos_wrapped_eps_become_vector_svg():
    for data in (BOX_EPS, dos_eps(BOX_EPS)):
        svg = eps_to_svg(data)
        assert svg.startswith("<svg") and "<path" in svg and "<script" not in svg and "viewBox" in svg


@needs_converter
def test_a_real_pdf_becomes_vector_svg():
    pdf = _handwritten_pdf()
    assert "<path" in pdf_to_svg(pdf)


@needs_converter
def test_a_hostile_postscript_file_is_refused_without_a_trace():
    hostile = (
        b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n"
        b"(%pipe%touch /tmp/pwned) (w) file closefile\n(/etc/passwd) (r) file closefile\n0 0 10 10 rectfill showpage\n"
    )
    with pytest.raises(ConversionError):
        eps_to_svg(hostile)


def _handwritten_pdf() -> bytes:
    """A small real PDF: a one-page document written by hand with a filled rectangle."""
    stream = b"1 0 0 rg 10 10 80 30 re f"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 50] /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
