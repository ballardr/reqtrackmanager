"""
Module: diagram_worker

Draws one Mermaid diagram as an SVG, in a process of its own that `converter.render_diagram` starts and confines.

Responsibilities:
- Read one JSON request (`{"source": ..., "theme": "light" | "dark"}`) from standard input, draw it with the real Mermaid
  library through `mermaidx` (an embedded JavaScript engine with a minimal fake DOM, no browser), and write one JSON
  reply (`{"svg": ...}` or `{"error": ...}`) to standard output.

Design decisions:
- **One diagram, one process.** The embedded engine cannot be interrupted from inside (its time limit cannot be
  combined with the callbacks that measure text), so a runaway layout is stopped only by killing the process. The
  parent sets the memory, CPU and wall-clock limits and kills the process group; nothing carries over between diagrams.
- The configuration is the screen's (`diagram_config.json`): strict security level, SVG text labels, the shared font
  family and the same limits, so the drawing matches the application's.
- The reply carries the SVG only; the backend sanitises it before it goes into a document.

Dependencies: `mermaidx` (MIT; bundles Mermaid, its layout engines and DejaVu Sans), Python 3.12 standard library.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG = json.loads((Path(__file__).resolve().parent / "diagram_config.json").read_text(encoding="utf-8"))

#: The largest SVG written back, in characters (the parent reads at most this much).
MAX_SVG_CHARS = 8 * 1024**2


def mermaid_config() -> dict[str, object]:
    """The Mermaid configuration the screen uses (`frontend/src/utils/mermaidRender.ts`).

    Returns:
        The settings passed to Mermaid: strict security, SVG labels, the shared font and size limits.
    """
    return {
        "securityLevel": "strict",
        "htmlLabels": False,
        "flowchart": {"htmlLabels": False},
        "fontFamily": f'"{CONFIG["fontFamily"]}"',
        "maxTextSize": CONFIG["limits"]["sourceChars"],
        "maxEdges": CONFIG["limits"]["edges"],
    }


def draw(source: str, theme: str) -> str:
    """Draws `source`.

    Args:
        source: Mermaid text.
        theme: `light` (Mermaid's default theme) or `dark`.

    Returns:
        The SVG markup (not yet sanitised).

    Raises:
        Exception: Mermaid refused the text (the message is the library's own).
    """
    import mermaidx  # noqa: PLC0415 - loaded here so the parent never imports the engine

    return mermaidx.render(source, theme="dark" if theme == "dark" else "default", config=mermaid_config()).svg()


def main() -> int:
    """Reads the request, draws, writes the reply.

    Returns:
        The process exit status: 0 whenever a reply was written (a refused diagram is a reply, not a crash).
    """
    request = json.loads(sys.stdin.read())
    try:
        svg = draw(str(request["source"]), str(request.get("theme", "light")))
    except Exception as exc:  # noqa: BLE001 - every library failure is a message for the author
        message = " ".join(str(exc).split("\n")[:3])[:300] or "The diagram could not be drawn."
        sys.stdout.write(json.dumps({"error": message}))
        return 0
    if len(svg) > MAX_SVG_CHARS:
        sys.stdout.write(json.dumps({"error": "The diagram is too large to draw."}))
        return 0
    sys.stdout.write(json.dumps({"svg": svg}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
