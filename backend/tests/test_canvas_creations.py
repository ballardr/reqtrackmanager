"""
Pins frontend/src/modules/architecture/canvasCreations.json: every creation on the two diagram canvases (block diagram and
state machine diagram) is listed with the path it takes, and the editor pages render no dialog that the list does not name
(docs/ux-style-guide.md, "Pattern: add, then edit in the selection").

A new creation or a new dialog in an editor page fails here until it is listed, so adding a form between the person and the
drawing is a decision recorded with a reason, not a default. Skipped when the repository root is not visible (the backend
container mounts only backend/).
"""

import json
import re
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "modules" / "architecture"
REGISTRY = MODULE_DIR / "canvasCreations.json"
DIALOG_TAG = re.compile(r"<([A-Z][A-Za-z]*(?:Modal|Dialog))\b")
PATHS = {"at-once", "dialog"}
ROLES = {"edit", "not-creation"}

pytestmark = pytest.mark.skipif(not REGISTRY.is_file(), reason="repository root not visible")


def _editors() -> dict:
    return json.loads(REGISTRY.read_text())["editors"]


def test_every_creation_names_a_path_and_a_reason_when_it_opens_a_dialog():
    for page, editor in _editors().items():
        for creation in editor["creations"]:
            assert creation["path"] in PATHS, f"{page}: {creation['kind']} has an unknown path"
            if creation["path"] == "dialog":
                assert creation.get("reason"), f"{page}: {creation['kind']} opens a dialog first and needs a reason"


def test_every_creation_handler_exists_in_its_editor_page():
    for page, editor in _editors().items():
        source = (MODULE_DIR / page).read_text()
        for creation in editor["creations"]:
            handler = creation["handler"]
            assert re.search(rf"function {handler}\b|const {handler}\b", source), (
                f"{page}: no handler {handler} for {creation['kind']}"
            )


def test_editor_pages_render_only_the_listed_dialogs():
    for page, editor in _editors().items():
        rendered = set(DIALOG_TAG.findall((MODULE_DIR / page).read_text()))
        listed = set(editor["dialogs"])
        assert rendered == listed, (
            f"{page}: dialogs rendered but not listed: {sorted(rendered - listed)}; listed but not rendered: "
            f"{sorted(listed - rendered)}. A creation form on a canvas needs a decision in canvasCreations.json."
        )
        for name, entry in editor["dialogs"].items():
            assert entry["role"] in ROLES and entry.get("reason"), f"{page}: {name} needs a role and a reason"
