"""Tests for the "ReqTrackManager (this product)" demo fixture.

The fixture is generated from the repository's documents by `scripts/extract_repo_demo.py`. These tests keep it
current (an edited or removed source entry fails), and check that what the seed will send the API is valid: names
within column lengths, unique prefixes, known decision and risk types, and a body for every record.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import extract_repo_demo as extractor  # noqa: E402

from app.modules.decisions.service import DEFAULT_DECISION_TYPES  # noqa: E402
from app.modules.risk_management.service import DEFAULT_RISK_TYPES  # noqa: E402

DECISIONS = extractor.REPO_ROOT / "docs" / "decisions.md"
needs_documents = pytest.mark.skipif(not DECISIONS.exists(), reason="docs/ is not available (backend-only image)")


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(extractor.FIXTURE_PATH.read_text(encoding="utf-8"))


@needs_documents
def test_the_fixture_matches_the_documents_it_is_generated_from(fixture):
    problems = extractor.find_drift(fixture, extractor.build_fixture(), extractor.parse_decisions())
    assert problems == [], "regenerate with: python backend/scripts/extract_repo_demo.py --write"


@needs_documents
def test_a_new_log_entry_is_not_drift_but_an_edited_one_is(fixture):
    all_decisions = extractor.parse_decisions()
    fresh = extractor.build_fixture()
    extra = {"title": "A later entry", "statement": "x", "rationale": "", "type": "Engineering", "section": "s", "decided_by": ""}
    assert extractor.find_drift(fixture, fresh, [*all_decisions, extra]) == []
    edited = [dict(entry, statement=entry["statement"] + " changed") if n == 0 else entry for n, entry in enumerate(all_decisions)]
    assert any("edited or removed" in problem for problem in extractor.find_drift(fixture, fresh, edited))


def test_a_decision_is_an_attributed_entry_or_one_from_the_original_design_sections(fixture):
    decisions = fixture["decisions"]
    assert 300 <= len(decisions) <= extractor.DECISION_LIMIT
    assert {d["decided_by"] for d in decisions} == {"User", "Agent", ""}
    assert all(d["decided_by"] or d["section"] in extractor.FOUNDATIONAL_SECTIONS for d in decisions)


def test_decision_titles_are_unique_and_free_of_attribution_notes_and_review_references(fixture):
    titles = [d["title"] for d in fixture["decisions"]]
    assert len(titles) == len(set(titles))
    assert not [t for t in titles if "Decided by" in t or "*" in t or "`" in t or re.search(r"\b[NQ]\d+\b", t)]


def test_decision_text_reads_as_prose(fixture):
    for decision in fixture["decisions"]:
        text = decision["statement"] + decision["rationale"]
        assert "\n" not in text
        assert decision["statement"][0].isalnum() or decision["statement"][0] in "`*\"(", decision["title"]


@needs_documents
def test_the_curation_file_names_only_entries_that_still_exist(fixture):
    curation = json.loads(extractor.CURATION_PATH.read_text(encoding="utf-8"))
    original = extractor.CURATION
    extractor.CURATION = {"titles": {}, "exclude": {}}
    try:
        keys = {entry["key"] for entry in extractor.parse_decisions()}
    finally:
        extractor.CURATION = original
    assert set(curation["exclude"]) <= keys and set(curation["titles"]) <= keys
    assert not {d["key"] for d in fixture["decisions"]} & set(curation["exclude"])


def test_every_decision_is_valid_for_the_create_endpoint(fixture):
    for decision in fixture["decisions"]:
        assert decision["type"] in DEFAULT_DECISION_TYPES
        assert 0 < len(decision["title"]) <= 300
        assert decision["statement"].strip()


def test_components_and_categories_have_unique_prefixes_and_every_requirement_has_a_place(fixture):
    component_prefixes = [c["prefix"] for c in fixture["components"]]
    assert len(component_prefixes) == len(set(component_prefixes))
    places = set()
    for component in fixture["components"]:
        category_prefixes = [c["prefix"] for c in component["categories"]]
        assert len(category_prefixes) == len(set(category_prefixes)), component["name"]
        places |= {(component["name"], c["name"]) for c in component["categories"]}
    for requirement in fixture["requirements"]:
        assert (requirement["component"], requirement["category"]) in places
        assert requirement["reasoning"].strip(), requirement["source_id"]
        assert 0 < len(requirement["name"]) <= 500
        assert requirement["target"] in {stage["name"] for stage in fixture["stages"]}


def test_the_standard_has_a_status_for_every_criterion_and_every_policy_is_known(fixture):
    policies = {policy["file"] for policy in fixture["policies"]}
    criteria = [c for group in fixture["standard"]["groups"] for c in group["criteria"]]
    assert len(criteria) >= 30
    assert {c["status"] for c in criteria} <= {"compliant", "in_progress", "non_compliant", "not_started"}
    assert all(set(c["policies"]) <= policies for c in criteria)
    assert len({c["reference"] for c in criteria}) == len(criteria)


def test_open_gaps_become_risks_and_resolved_gaps_do_not(fixture):
    assert fixture["gaps"], "the policies list open known gaps"
    assert all(gap["type"] in DEFAULT_RISK_TYPES and 0 < len(gap["title"]) <= 300 for gap in fixture["gaps"])
    assert not any(gap["statement"].startswith("~~") for gap in fixture["gaps"])
    # Encryption policy gap 1 is struck through in the policy, so its text must not appear.
    assert not any("OIDC client secrets are stored in plaintext" in gap["title"] for gap in fixture["gaps"])


def test_the_architecture_principles_are_extracted(fixture):
    assert len(fixture["principles"]) == 4
    assert all(p["name"] and p["statement"] for p in fixture["principles"])
