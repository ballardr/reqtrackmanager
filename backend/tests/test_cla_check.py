"""
Pins the contributor licence agreement check (scripts/check_cla.py) and the product-licence metadata.

- The committed signatories file is valid and its version rule reads CLA.md.
- A commit author passes only as a maintainer, an automation account or a signatory of the current version; an
  author with no linked GitHub account fails; a pull request cannot exempt itself through its own copy of the file.
- The licence the repository states agrees everywhere it is stated: LICENSE, each package.json, the Licences page
  constant and the commercial-licence summary.

Skipped when the repository root is not visible (the backend container mounts only backend/); CI's `cla` job and
the pre-commit hook run the script directly.
"""

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_cla.py"
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="repository checkout not available")

PRODUCT_SPDX = "AGPL-3.0-only"


def _load():
    """Imports scripts/check_cla.py as a module."""
    spec = importlib.util.spec_from_file_location("check_cla", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_cla"] = module
    spec.loader.exec_module(module)
    return module


cla = _load()
VERSION = cla.current_version((ROOT / "CLA.md").read_text(encoding="utf-8"))
BASE = {
    "maintainers": ["owner"],
    "automation": ["bot[bot]"],
    "signatories": [{"login": "Alice", "name": "Alice Example", "date": "2026-11-19", "cla_version": VERSION}],
}


def test_committed_file_is_valid():
    data = json.loads((ROOT / ".github" / "cla-signatories.json").read_text(encoding="utf-8"))
    assert cla.file_problems(data) == []
    assert cla.main([]) == 0


def test_version_is_read_from_the_agreement():
    assert cla.current_version("# X\n\n**Version 2.1**\n") == "2.1"
    with pytest.raises(ValueError):
        cla.current_version("# no version here")


def test_maintainer_automation_and_current_signatory_pass():
    assert cla.author_problems(BASE, BASE, VERSION, ["owner", "bot[bot]", "alice"]) == []


def test_unsigned_outdated_and_unlinked_authors_fail():
    stale = copy.deepcopy(BASE)
    stale["signatories"][0]["cla_version"] = "0.1"
    assert any("has not signed" in p for p in cla.author_problems(BASE, BASE, VERSION, ["stranger"]))
    assert any("signed version 0.1" in p for p in cla.author_problems(stale, stale, VERSION, ["alice"]))
    assert any("not linked" in p for p in cla.author_problems(BASE, BASE, VERSION, [""]))


def test_a_pull_request_cannot_exempt_itself():
    own = copy.deepcopy(BASE)
    own["maintainers"].append("stranger")
    assert cla.author_problems(own, BASE, VERSION, ["stranger"]) != []


def test_file_problems_are_reported():
    bad = copy.deepcopy(BASE)
    bad["signatories"] += [
        {"login": "alice", "name": "Again", "date": "2026-11-19", "cla_version": VERSION},
        {"login": "owner", "name": "Owner", "date": "2026-11-19", "cla_version": VERSION},
        {"login": "bob", "name": "", "date": "yesterday", "cla_version": "x"},
    ]
    text = "\n".join(cla.file_problems(bad))
    assert "more than once" in text and "needs no signature" in text and "no name" in text
    assert "no valid date" in text and "no valid cla_version" in text


def test_licence_is_stated_consistently():
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("                    GNU AFFERO GENERAL PUBLIC LICENSE")
    for manifest in ("frontend/package.json", "docs/website/package.json"):
        assert json.loads((ROOT / manifest).read_text(encoding="utf-8")).get("license") == PRODUCT_SPDX, manifest
    panel = (ROOT / "frontend" / "src" / "components" / "LicencesPanel.tsx").read_text(encoding="utf-8")
    assert re.search(rf'spdx: "{re.escape(PRODUCT_SPDX)}"', panel)
    assert "AGPL-3.0-only" in (ROOT / "COMMERCIAL-LICENSE.md").read_text(encoding="utf-8")
