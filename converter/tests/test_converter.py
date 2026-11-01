"""Tests for the picture converter: type recognition, confinement, real conversions (this image has Ghostscript and
poppler) including hostile files, and the HTTP interface. Run inside the container: `python -m unittest discover -s tests`."""

from __future__ import annotations

import http.client
import json
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import converter  # noqa: E402

BOX_EPS = b"""%!PS-Adobe-3.0 EPSF-3.0
%%BoundingBox: 0 0 100 50
newpath 0 0 100 50 rectfill
1 0 0 setrgbcolor 10 10 80 30 rectfill
0 0 1 setrgbcolor 50 25 12 0 360 arc fill
/Helvetica findfont 14 scalefont setfont 0 setgray 5 2 moveto (EPS) show
showpage
"""


def dos_eps(postscript: bytes) -> bytes:
    """The binary DOS EPS wrapper: a 30-byte header pointing at the PostScript section, which follows it."""
    header = b"\xc5\xd0\xd3\xc6" + struct.pack("<IIIIIIH", 30, len(postscript), 0, 0, 0, 0, 0xFFFF)
    return header + postscript


def make_pdf() -> bytes:
    """A real one-page PDF, made by Ghostscript from the sample EPS."""
    with tempfile.TemporaryDirectory() as tmp:
        source, out = Path(tmp, "in.eps"), Path(tmp, "out.pdf")
        source.write_bytes(BOX_EPS)
        subprocess.run(  # noqa: S603, S607 - fixed arguments
            ["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dEPSCrop", "-sDEVICE=pdfwrite", f"-sOutputFile={out}", str(source)],
            check=True,
        )
        return out.read_bytes()


class Recognising(unittest.TestCase):
    def test_a_file_is_recognised_by_its_bytes(self) -> None:
        self.assertTrue(converter.is_eps(BOX_EPS) and converter.is_eps(dos_eps(BOX_EPS)))
        self.assertFalse(converter.is_eps(b"<svg/>") or converter.is_eps(b"%PDF-1.4"))
        self.assertTrue(converter.is_pdf(b"%PDF-1.7\n") and converter.is_pdf(b"\n\n%PDF-1.4"))
        self.assertFalse(converter.is_pdf(BOX_EPS) or converter.is_pdf(b"x" * 2000 + b"%PDF-"))

    def test_the_dos_wrapper_is_removed_and_a_damaged_one_refused(self) -> None:
        self.assertEqual(converter.postscript_of(dos_eps(BOX_EPS)), BOX_EPS)
        with self.assertRaises(converter.ConversionError):
            converter.postscript_of(b"\xc5\xd0\xd3\xc6" + struct.pack("<II", 30, 9999) + b"x" * 30)
        with self.assertRaises(converter.ConversionError):
            converter.postscript_of(b"\xc5\xd0\xd3\xc6")


class Confinement(unittest.TestCase):
    def test_a_tool_runs_with_a_fixed_command_cleared_environment_new_session_and_no_shell(self) -> None:
        seen: list[tuple[list[str], dict]] = []

        class Fake:
            pid = 99999999

            def __init__(self, args, **kwargs) -> None:
                seen.append((args, kwargs))

            def wait(self, timeout=None) -> int:
                return 0

        with mock.patch.object(converter.subprocess, "Popen", Fake), mock.patch.object(converter.os, "killpg"):
            converter._run(["gs", "-q"], Path("/tmp"))

        args, kwargs = seen[0]
        self.assertEqual(args[0], "gs")
        self.assertNotIn("shell", kwargs)
        self.assertEqual(set(kwargs["env"]), {"PATH", "HOME", "TMPDIR", "LC_ALL"})
        self.assertIs(kwargs["start_new_session"], True)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIsNotNone(kwargs["preexec_fn"])

    def test_a_missing_tool_is_reported_as_missing(self) -> None:
        with self.assertRaises(converter.ToolMissingError):
            converter._run(["definitely-not-installed"], Path("/tmp"))


class RealConversions(unittest.TestCase):
    def test_a_real_eps_becomes_an_svg(self) -> None:
        svg = converter.eps_to_svg(BOX_EPS).decode()
        self.assertTrue("<svg" in svg and "<path" in svg and "viewBox" in svg)

    def test_a_dos_wrapped_eps_converts_too(self) -> None:
        self.assertIn(b"<path", converter.eps_to_svg(dos_eps(BOX_EPS)))

    def test_a_real_pdf_becomes_an_svg(self) -> None:
        self.assertIn(b"<path", converter.pdf_to_svg(make_pdf()))

    def test_postscript_cannot_read_or_write_files_or_run_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp, "pwned")
            hostile = (
                f"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n"
                f"(%pipe%touch {marker}) (w) file closefile\n"
                f"({marker}) (w) file closefile\n"
                "(/etc/passwd) (r) file closefile\n"
                "0 0 10 10 rectfill showpage\n"
            ).encode()
            with self.assertRaises(converter.ConversionError):
                converter.eps_to_svg(hostile)
            self.assertFalse(marker.exists())

    def test_a_non_terminating_file_is_stopped_by_the_timeout(self) -> None:
        loop = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n{ } loop\n"
        with mock.patch.object(converter, "CONVERT_TIMEOUT_SECONDS", 2), self.assertRaisesRegex(converter.ConversionError, "too long"):
            converter.eps_to_svg(loop)

    def test_a_damaged_pdf_is_refused_with_a_message_that_leaks_nothing(self) -> None:
        with self.assertRaises(converter.ConversionError) as caught:
            converter.pdf_to_svg(b"%PDF-1.4\nthis is not really a pdf")
        self.assertEqual(str(caught.exception), "The file could not be read.")


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

    def request(self, method: str, path: str, body: bytes | None = None, host: str = "127.0.0.1", headers: dict | None = None):
        connection = http.client.HTTPConnection(host, self.port, timeout=60)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()

    def test_health_is_ok_while_the_tools_are_installed(self) -> None:
        self.assertEqual(self.request("GET", "/health")[0], 200)
        with mock.patch.object(converter, "tools_available", return_value=False):
            self.assertEqual(self.request("GET", "/health")[0], 503)

    def test_it_answers_on_ipv6_too_where_the_host_has_it(self) -> None:
        if self.server.address_family.name != "AF_INET6":
            self.skipTest("this host cannot listen on IPv6")
        self.assertEqual(self.request("GET", "/health", host="::1")[0], 200)

    def test_an_eps_and_a_pdf_come_back_as_svg(self) -> None:
        for path, body in (("/convert/eps", BOX_EPS), ("/convert/pdf", make_pdf())):
            status, kind, payload = self.request("POST", path, body)
            self.assertEqual((status, kind), (200, "image/svg+xml"), path)
            self.assertIn(b"<svg", payload)

    def test_the_type_is_judged_from_the_bytes_not_the_route(self) -> None:
        status, _, payload = self.request("POST", "/convert/pdf", BOX_EPS)
        self.assertEqual((status, json.loads(payload)["detail"]), (422, "This is not a PDF file."))
        self.assertEqual(self.request("POST", "/convert/eps", b"%PDF-1.4")[0], 422)

    def test_unknown_routes_missing_lengths_and_oversize_bodies_are_refused(self) -> None:
        self.assertEqual(self.request("GET", "/nope")[0], 404)
        self.assertEqual(self.request("POST", "/convert/other", b"x")[0], 404)
        with mock.patch.object(converter, "MAX_BODY_BYTES", 10):
            self.assertEqual(self.request("POST", "/convert/eps", b"x" * 11)[0], 413)

    def test_a_conversion_that_fails_returns_a_plain_message(self) -> None:
        status, _, payload = self.request("POST", "/convert/eps", b"%!PS-Adobe-3.0 EPSF-3.0\n(unterminated")
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(payload)["detail"], "The file could not be read.")

    def test_a_request_waiting_too_long_for_a_free_slot_is_told_the_service_is_busy(self) -> None:
        taken = threading.BoundedSemaphore(1)
        taken.acquire()
        with mock.patch.object(converter, "_slots", taken), mock.patch.object(converter, "QUEUE_SECONDS", 0.2):
            self.assertEqual(self.request("POST", "/convert/eps", BOX_EPS)[0], 503)


if __name__ == "__main__":
    unittest.main()
