"""
Pins scripts/check_detail_card_order.py: a record detail page keeps the default card order, with comments last
(docs/ux-style-guide.md, "Pattern: detail page card order").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_detail_card_order.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_detail_card_order", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")

PAGE = (
    "<DetailLayout>\n  <RecordHeader title=\"x\" />\n{body}</DetailLayout>\n"
)


def test_every_detail_page_keeps_the_card_order():
    """The baseline is empty."""
    assert checker.violations() == []


def test_a_wrapper_beside_the_header_is_reported():
    """A `div.stack` at the header's indent hides its cards from the sort; one inside a card does not."""
    wrapped = PAGE.format(body='  <div className="stack">\n    <DetailCard />\n  </div>\n')
    assert [problem for _, problem in checker.violations_in(wrapped)] == [
        "a wrapper beside the RecordHeader hides its cards from the card order"
    ]
    inside = PAGE.format(body='  <DetailCard>\n    <div className="stack">x</div>\n  </DetailCard>\n')
    assert checker.violations_in(inside) == []


def test_a_comment_card_must_be_the_discussion_rank():
    """A card holding a CommentThread without `rank="discussion"` is reported; with it, it is not."""
    plain = PAGE.format(body='  <DetailCard heading="Discussion">\n    <CommentThread />\n  </DetailCard>\n')
    assert [problem for _, problem in checker.violations_in(plain)] == ['a card with comments needs rank="discussion"']
    ranked = PAGE.format(body='  <DetailCard heading="Discussion" rank="discussion">\n    <CommentThread />\n  </DetailCard>\n')
    assert checker.violations_in(ranked) == []


def test_an_unknown_rank_is_reported():
    """A rank that does not exist would sort as the default silently."""
    page = PAGE.format(body='  <DetailCard rank="last" />\n')
    assert [problem for _, problem in checker.violations_in(page)] == ['unknown rank "last"']


def test_a_page_that_is_arranged_by_the_person_is_skipped():
    """`orderCards={false}` opts the page out."""
    page = "<DetailLayout orderCards={false}>\n  <RecordHeader />\n  <DetailCard>\n    <CommentThread />\n  </DetailCard>\n</DetailLayout>\n"
    assert checker.violations_in(page) == []
