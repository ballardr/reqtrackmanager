"""
Module: converter

A small, isolated HTTP service that turns an uploaded EPS or PDF logo into an SVG, and a Mermaid diagram into an SVG, so
the backend never runs a PostScript interpreter, a PDF parser or a JavaScript engine itself.

Responsibilities:
- `POST /convert/eps`: Ghostscript (EPS to a one-page PDF cropped to the bounding box), then poppler's `pdftocairo`
  (PDF to SVG). `POST /convert/pdf`: `pdftocairo` on the first page.
- `POST /diagram`: Mermaid text (JSON `{"source", "theme"}`) to an SVG, drawn by `diagram_worker.py` with the same
  version, font and limits as the screen.
- `GET /health`: whether the tools and the diagram renderer are installed.
- Confine each conversion: a private working directory, a cleared environment, no stdin, a wall-clock timeout, CPU,
  memory and output-size limits, and a cap on conversions at once.

Design decisions:
- **This container is the sandbox.** Ghostscript has a long history of `-dSAFER` bypasses, so the interpreter runs
  where a successful exploit finds nothing: no network (Compose puts it only on an `internal` network shared with the
  backend), no secrets, no application code, a non-root user, a read-only filesystem with a small `tmpfs`, no Linux
  capabilities. The limits in this file are a second layer.
- **Input and output are untrusted.** The backend sanitises the SVG (`app.services.report_svg.sanitize_svg`) and
  decides what is stored; the input type is checked here from its bytes, never from the request.
- **Stateless.** Standard library only; nothing is stored; no file name, diagram text or content is logged.
- **A diagram is drawn in a process of its own**, killed at the wall-clock limit: the embedded JavaScript engine
  cannot be interrupted from inside, and some diagrams (a wide flowchart) run for minutes. The reply is checked
  against the screen's element limit.
- The listener is dual-stack IPv6 (`::`), falling back to IPv4 where the host has no IPv6.

Dependencies: the `gs` (Ghostscript) and `pdftocairo` (poppler-utils) executables, `mermaidx` (for the diagram worker
only), Python 3.12 standard library.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

PORT = int(os.environ.get("CONVERTER_PORT", "8300"))
#: Largest request body accepted, in bytes (the backend refuses a larger upload before it calls this).
MAX_BODY_BYTES = int(os.environ.get("CONVERTER_MAX_BODY_BYTES", str(64 * 1024**2)))
#: Conversions that may run at once; another request waits `QUEUE_SECONDS`, then is told the service is busy.
MAX_CONCURRENT = int(os.environ.get("CONVERTER_MAX_CONCURRENT", "2"))
QUEUE_SECONDS = 10
#: Wall-clock seconds each tool may run.
CONVERT_TIMEOUT_SECONDS = 30
#: Limits applied to each tool process: address space, CPU seconds and the size of any file it writes.
# Two conversions at once plus the 512 MB scratch space must fit the container's 2560 MB limit.
MAX_MEMORY_BYTES = 900 * 1024**2
MAX_CPU_SECONDS = 30
MAX_OUTPUT_BYTES = 64 * 1024**2
#: Largest SVG returned, in bytes.
MAX_SVG_BYTES = 32 * 1024**2
#: Seconds a client may take to send its request before the connection is dropped.
CLIENT_TIMEOUT_SECONDS = 30

#: What a diagram is drawn with: the screen's version, font and limits (`diagram_config.json`).
DIAGRAM_CONFIG = json.loads((Path(__file__).resolve().parent / "diagram_config.json").read_text(encoding="utf-8"))
#: Wall-clock seconds a diagram may take (the engine is an interpreter, far slower than a browser on a large diagram).
DIAGRAM_TIMEOUT_SECONDS = DIAGRAM_CONFIG["serverRenderMilliseconds"] / 1000
#: Limits on a diagram's process: address space (the engine's own heap limit is 512 MiB), CPU seconds, written file size.
DIAGRAM_MAX_MEMORY_BYTES = 1536 * 1024**2
DIAGRAM_MAX_CPU_SECONDS = int(DIAGRAM_TIMEOUT_SECONDS) + 5
#: Largest request body for a diagram: its text (at most `sourceChars`) as JSON, with room for escapes.
MAX_DIAGRAM_REQUEST_BYTES = DIAGRAM_CONFIG["limits"]["sourceChars"] * 8
#: Largest reply read from the worker, in bytes (its own SVG cap, JSON-escaped).
MAX_DIAGRAM_REPLY_BYTES = 24 * 1024**2
_ELEMENT = re.compile(r"<[a-zA-Z]")

_DOS_EPS_MAGIC = b"\xc5\xd0\xd3\xc6"
_PS_MAGIC = b"%!PS-Adobe"
_PDF_MAGIC = b"%PDF-"

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


class ConversionError(ValueError):
    """The file could not be converted (the message is shown to the person who uploaded it)."""


class ToolMissingError(ConversionError):
    """A converter executable is not installed."""


def is_eps(data: bytes) -> bool:
    """Whether `data` is an EPS, judged by its first bytes (a `%!PS-Adobe` header or the DOS EPS wrapper)."""
    return data.startswith(_PS_MAGIC) or data.startswith(_DOS_EPS_MAGIC)


def is_pdf(data: bytes) -> bool:
    """Whether `data` is a PDF: the `%PDF-` header may follow up to 1 KiB of leading bytes."""
    return _PDF_MAGIC in data[:1024]


def postscript_of(data: bytes) -> bytes:
    """The PostScript text of an EPS, unwrapping the DOS EPS binary header when there is one.

    Args:
        data: A file for which `is_eps` is true.

    Returns:
        The PostScript section.

    Raises:
        ConversionError: The wrapper's offsets point outside the file.
    """
    if not data.startswith(_DOS_EPS_MAGIC):
        return data
    if len(data) < 12:
        raise ConversionError("The EPS file is damaged.")
    offset, length = struct.unpack_from("<II", data, 4)
    if length == 0 or offset + length > len(data):
        raise ConversionError("The EPS file is damaged.")
    return data[offset : offset + length]


def _limits(
    memory: int = MAX_MEMORY_BYTES, cpu: int = MAX_CPU_SECONDS, output: int = MAX_OUTPUT_BYTES,
) -> Callable[[], None] | None:
    """A `preexec_fn` applying the resource limits in the child (POSIX only).

    Args:
        memory: Address-space limit, in bytes.
        cpu: CPU-time limit, in seconds.
        output: Size limit for any file the child writes, in bytes.
    """
    try:
        import resource
    except ImportError:  # pragma: no cover - not POSIX
        return None

    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_FSIZE, (output, output))

    return apply


def _run(args: list[str], workdir: Path) -> None:
    """Runs one tool confined to `workdir`.

    Args:
        args: The command (an executable name resolved on `PATH`, then its arguments).
        workdir: The private directory that is its working directory, `HOME` and `TMPDIR`.

    Raises:
        ToolMissingError: The executable is not installed.
        ConversionError: The tool ran too long, or exited with an error.
    """
    if shutil.which(args[0]) is None:
        raise ToolMissingError("The converter is missing a tool it needs.")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(workdir), "TMPDIR": str(workdir), "LC_ALL": "C"}
    process = subprocess.Popen(  # noqa: S603 - fixed argument list, no shell
        args, cwd=workdir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=_limits(), start_new_session=True,
    )
    try:
        code = process.wait(timeout=CONVERT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise ConversionError("The file took too long to convert.") from None
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)  # anything the tool left behind
        except ProcessLookupError:
            pass
    if code != 0:
        raise ConversionError("The file could not be read.")


def _pdf_to_svg(pdf: Path, svg: Path, workdir: Path) -> bytes:
    """Runs `pdftocairo` on the first page of `pdf` and returns the SVG bytes."""
    _run(["pdftocairo", "-svg", "-f", "1", "-l", "1", pdf.name, svg.name], workdir)
    if not svg.is_file() or svg.stat().st_size > MAX_SVG_BYTES:
        raise ConversionError("The file is too complex to use.")
    return svg.read_bytes()


def eps_to_svg(data: bytes) -> bytes:
    """Converts an EPS to an SVG (not yet sanitised).

    Args:
        data: A file for which `is_eps` is true.

    Returns:
        SVG bytes.

    Raises:
        ConversionError: The file is damaged, too complex, or the conversion failed or timed out.
    """
    postscript = postscript_of(data)
    with tempfile.TemporaryDirectory(prefix="eps-") as tmp:
        workdir = Path(tmp)
        source, pdf, svg = workdir / "in.eps", workdir / "out.pdf", workdir / "out.svg"
        source.write_bytes(postscript)
        _run(
            [
                "gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dNOPROMPT", "-dEPSCrop", "-sDEVICE=pdfwrite",
                f"-sOutputFile={pdf.name}", source.name,
            ],
            workdir,
        )
        if not pdf.is_file():
            raise ConversionError("The file could not be read.")
        return _pdf_to_svg(pdf, svg, workdir)


def pdf_to_svg(data: bytes) -> bytes:
    """Converts the first page of a PDF to an SVG (not yet sanitised).

    Args:
        data: A file for which `is_pdf` is true.

    Returns:
        SVG bytes.

    Raises:
        ConversionError: The file is damaged, encrypted, too complex, or the conversion failed or timed out.
    """
    with tempfile.TemporaryDirectory(prefix="pdf-") as tmp:
        workdir = Path(tmp)
        pdf, svg = workdir / "in.pdf", workdir / "out.svg"
        pdf.write_bytes(data)
        return _pdf_to_svg(pdf, svg, workdir)


def render_diagram(source: str, theme: str) -> bytes:
    """Draws Mermaid text as an SVG (not yet sanitised) in a confined process.

    Args:
        source: The Mermaid text.
        theme: `light` or `dark`.

    Returns:
        SVG bytes.

    Raises:
        ToolMissingError: The renderer is not installed.
        ConversionError: The text is empty, over the size limit, refused by Mermaid, too large to draw, or took too long.
    """
    text = source.strip()
    if not text:
        raise ConversionError("The diagram is empty.")
    if len(text) > DIAGRAM_CONFIG["limits"]["sourceChars"]:
        raise ConversionError(f"The diagram text is over the limit of {DIAGRAM_CONFIG['limits']['sourceChars']} characters.")
    if theme not in ("light", "dark"):
        raise ConversionError("The theme must be light or dark.")
    if not diagram_renderer_available():
        raise ToolMissingError("The converter is missing the diagram renderer.")
    request = json.dumps({"source": text, "theme": theme}).encode()
    with tempfile.TemporaryDirectory(prefix="diagram-") as tmp:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "TMPDIR": tmp, "LC_ALL": "C"}
        with subprocess.Popen(  # noqa: S603 - fixed argument list, no shell
            [sys.executable, "-I", str(Path(__file__).with_name("diagram_worker.py"))],
            cwd=tmp, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            preexec_fn=_limits(DIAGRAM_MAX_MEMORY_BYTES, DIAGRAM_MAX_CPU_SECONDS, 1024**2), start_new_session=True,
        ) as process:
            try:
                out, _ = process.communicate(request, timeout=DIAGRAM_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                raise ConversionError("The diagram took too long to draw.") from None
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)  # a runaway layout, or anything the worker left behind
                except ProcessLookupError:
                    pass
    if len(out) > MAX_DIAGRAM_REPLY_BYTES:
        raise ConversionError("The diagram is too large to draw.")
    try:
        reply = json.loads(out)
    except ValueError:
        raise ConversionError("The diagram could not be drawn (it used too much memory or time).") from None
    if "error" in reply:
        raise ConversionError(str(reply["error"])[:300])
    svg = str(reply.get("svg", ""))
    if len(_ELEMENT.findall(svg)) > DIAGRAM_CONFIG["limits"]["elements"]:
        raise ConversionError("The diagram is too large to draw.")
    return svg.encode()


def _render_diagram_request(body: bytes) -> bytes:
    """Reads a `/diagram` request body (JSON) and draws it.

    Raises:
        ConversionError: The body is not a JSON object with a text `source`, or the drawing failed (see `render_diagram`).
    """
    try:
        request = json.loads(body)
    except ValueError:
        raise ConversionError("The request must be JSON.") from None
    if not isinstance(request, dict) or not isinstance(request.get("source"), str):
        raise ConversionError("The request needs a text `source`.")
    theme = request.get("theme", "light")
    return render_diagram(request["source"], theme if isinstance(theme, str) else "")


#: Route to (type check, converter, message for a file of the wrong type).
ROUTES: dict[str, tuple[Callable[[bytes], bool], Callable[[bytes], bytes], str]] = {
    "/convert/eps": (is_eps, eps_to_svg, "This is not an EPS file."),
    "/convert/pdf": (is_pdf, pdf_to_svg, "This is not a PDF file."),
}


def diagram_renderer_available() -> bool:
    """Whether the diagram renderer (`mermaidx`) is installed (found without loading its 6 MB engine)."""
    return importlib.util.find_spec("mermaidx") is not None


def tools_available() -> bool:
    """Whether both executables and the diagram renderer are installed."""
    return shutil.which("gs") is not None and shutil.which("pdftocairo") is not None and diagram_renderer_available()


class Handler(BaseHTTPRequestHandler):
    """Handles `GET /health`, the `POST /convert/...` routes and `POST /diagram`."""

    server_version = "converter"
    protocol_version = "HTTP/1.1"
    timeout = CLIENT_TIMEOUT_SECONDS

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, detail: str) -> None:
        self._send(status, json.dumps({"detail": detail}).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        """Health probe."""
        if self.path != "/health":
            self._error(404, "Not found.")
        elif tools_available():
            self._send(200, b"ok", "text/plain")
        else:
            self._error(503, "The converter is missing a tool it needs.")

    def do_POST(self) -> None:  # noqa: N802 - http.server's name
        """Converts the request body."""
        diagram = self.path == "/diagram"
        route = ROUTES.get(self.path)
        if route is None and not diagram:
            self._error(404, "Not found.")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error(411, "A Content-Length is required.")
            return
        if length <= 0 or length > (MAX_DIAGRAM_REQUEST_BYTES if diagram else MAX_BODY_BYTES):
            self.close_connection = True
            self._error(413, "The diagram is too large." if diagram else "The file is too large.")
            return
        # The slot is taken before the body is read, so waiting requests hold no upload in memory (up to 64 MiB each).
        if not _slots.acquire(timeout=QUEUE_SECONDS):
            self.close_connection = True
            self._error(503, "The converter is busy. Try again in a moment.")
            return
        started = time.monotonic()
        try:
            data = self.rfile.read(length)
            if route is None:
                svg = _render_diagram_request(data)
            else:
                check, convert, wrong_type = route
                if not check(data):
                    self._error(422, wrong_type)
                    return
                svg = convert(data)
        except ToolMissingError as exc:
            self._error(503, str(exc))
        except ConversionError as exc:
            self._error(422, str(exc))
        except Exception:  # noqa: BLE001 - never leak a traceback or file content to the caller
            self._error(500, "The file could not be converted.")
        else:
            self._send(200, svg, "image/svg+xml")
        finally:
            _slots.release()
            sys.stderr.write(f"converted {self.path} in {time.monotonic() - started:.2f}s ({length} bytes in)\n")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - signature of the base class
        """Silences the default access log (it would carry nothing useful, and no content is ever logged)."""


class DualStackServer(ThreadingHTTPServer):
    """A threaded HTTP server on `::`, accepting IPv4 as well, or on `0.0.0.0` where IPv6 is unavailable."""

    daemon_threads = True
    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        """Binds with `IPV6_V6ONLY` off so one socket serves both families."""
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def make_server(port: int = PORT) -> ThreadingHTTPServer:
    """Creates the listener.

    Args:
        port: TCP port (0 for any free one).

    Returns:
        A dual-stack server, or an IPv4 one where the host cannot bind IPv6.
    """
    try:
        return DualStackServer(("::", port), Handler)
    except OSError:
        sys.stderr.write("IPv6 is not available here; listening on IPv4 only\n")
        return ThreadingHTTPServer(("0.0.0.0", port), Handler)  # noqa: S104 - container listener, internal network only


def main() -> None:
    """Runs the service until it is stopped."""
    server = make_server()
    sys.stderr.write(f"converter listening on port {server.server_address[1]}\n")
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    server.serve_forever()


if __name__ == "__main__":
    main()
