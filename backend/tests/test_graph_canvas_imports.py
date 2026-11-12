"""
Pins scripts/check_graph_canvas_imports.py: React Flow (`@xyflow/react`) is imported only by
`components/GraphCanvasView.tsx`, which `GraphCanvas` loads lazily, so the library stays out of the main bundle
and every consumer draws through the one shared canvas.

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_graph_canvas_imports.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_graph_canvas_imports", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_only_the_canvas_view_imports_react_flow():
    """No other source file imports `@xyflow/*`."""
    assert checker.violations() == []


def test_the_wrapper_loads_the_view_lazily():
    """`GraphCanvas.tsx` reaches the view only through `lazy(() => import(...))`, never a static import."""
    source = (checker.SRC / "components" / "GraphCanvas.tsx").read_text(encoding="utf-8")
    assert 'import("./GraphCanvasView")' in source
    assert 'from "./GraphCanvasView"' not in source


@pytest.mark.parametrize(
    "text",
    ['import { ReactFlow } from "@xyflow/react";', "import '@xyflow/react/dist/style.css';", 'await import("@xyflow/system")'],
)
def test_an_xyflow_import_is_caught(text):
    """Named, side-effect and dynamic imports are all violations outside the view."""
    assert checker.IMPORT.search(text)


def test_a_mention_is_not_an_import():
    """A comment naming the package is not an import."""
    assert not checker.IMPORT.search("// uses @xyflow/react under the hood")
