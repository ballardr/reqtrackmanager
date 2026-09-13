"""Tests for Phase 21's standard-level import/export
(docs/compliance-module-plan.md Phase 21; docs/Compliance_Module_
Requirements.md §29): `GET .../standards/{id}/export`/`POST .../standards/
import` — a single `ComplianceStandard`, with every version's full
requirement/required-action tree, as its own portable JSON document,
distinct from the whole-organisation bundle `test_compliance_export_import.
py` already covers.

Reuses `test_compliance_standards_api.py`'s/`test_compliance_mapping_and_
version_impact.py`'s/`test_project_compliance_api.py`'s existing small API
helpers for setup, the same way this module's other test files already do.
"""

from __future__ import annotations

import io
import json

from app.modules.compliance.tests.test_compliance_mapping_and_version_impact import (
    _create_mapping,
    _create_relationship_type,
)
from app.modules.compliance.tests.test_compliance_standards_api import (
    _base,
    _create_action_type,
    _create_required_action,
    _create_requirement,
    _create_standard,
)
from app.modules.compliance.tests.test_project_compliance_api import _publish_version
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login


def _export(client, token, org_id, standard_id):
    resp = client.get(f"{_base(org_id)}/standards/{standard_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    return resp.json()


def _import(client, token, org_id, document, *, resolution=None):
    data = {} if resolution is None else {"resolution": resolution}
    resp = client.post(
        f"{_base(org_id)}/standards/import",
        files={"file": ("export.json", io.BytesIO(json.dumps(document).encode()), "application/json")},
        data=data,
        headers=auth_headers(token),
    )
    return resp


def _build_standard_with_tree(client, admin_token, org_id, *, reference="EXP-STD"):
    """A standard with one parent requirement, one child requirement (each
    with a required action of its own), in a single draft version — enough
    structure to prove the export/import round trip preserves hierarchy,
    required actions, and the action-type vocabulary subset."""
    standard = _create_standard(client, admin_token, org_id, reference=reference, name="Exportable Standard")
    # `create_standard` doesn't embed its own first version in the response
    # (Phase 6's `ComplianceStandardOut` is deliberately flat) — fetch it.
    versions = client.get(f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token)).json()
    version_id = versions[0]["id"]

    # Named after `reference` — action-type names are unique per
    # organisation, and some tests below build more than one standard (each
    # with its own required action) in the same org.
    action_type = _create_action_type(client, admin_token, org_id, name=f"Verification ({reference})")
    parent = _create_requirement(client, admin_token, org_id, standard["id"], version_id, name="Parent Requirement", reference="1")
    child = _create_requirement(
        client, admin_token, org_id, standard["id"], version_id, name="Child Requirement", reference="1.1",
        parent_requirement_id=parent["id"],
    )
    action = _create_required_action(
        client, admin_token, org_id, standard["id"], version_id, child["id"], action_type["id"], name="Perform verification test"
    )
    return standard, version_id, parent, child, action_type, action


def test_export_document_carries_full_tree_and_only_referenced_vocab(client, admin_token, org_id):
    standard, version_id, parent, child, action_type, action = _build_standard_with_tree(client, admin_token, org_id)
    # A second, unused action type must NOT leak into the export — "not the
    # whole org's vocabulary" per this phase's own spec.
    _create_action_type(client, admin_token, org_id, name="Unused Action Type")

    doc = _export(client, admin_token, org_id, standard["id"])
    assert doc["format"] == "reqtrackmanager.compliance_standard.v1"
    assert doc["standard"]["reference"] == standard["reference"]
    assert doc["standard"]["name"] == "Exportable Standard"
    assert [t["name"] for t in doc["compliance_action_types"]] == ["Verification (EXP-STD)"]

    assert len(doc["standard"]["versions"]) == 1
    version_doc = doc["standard"]["versions"][0]
    assert version_doc["status"] == "draft"
    requirements = version_doc["requirements"]
    assert len(requirements) == 2
    parent_doc = next(r for r in requirements if r["name"] == "Parent Requirement")
    child_doc = next(r for r in requirements if r["name"] == "Child Requirement")
    assert parent_doc["parent_ref"] is None
    assert child_doc["parent_ref"] == parent_doc["ref"]
    assert child_doc["required_actions"][0]["name"] == "Perform verification test"
    assert child_doc["required_actions"][0]["action_type_name"] == "Verification (EXP-STD)"


def test_export_and_import_round_trip_version_summary_and_clarification(client, admin_token, org_id):
    """Phase 24: a version's `summary` and a requirement's clarification
    fields (`clarification_count`/`last_clarified_at`/
    `last_clarification_note`/the clarifying user) are first-class exported
    fields, not silently dropped like the "evidence history missing from
    export" gap Phase 15 found and fixed."""
    standard, version_id, parent, child, action_type, action = _build_standard_with_tree(
        client, admin_token, org_id, reference="CLARIFY-EXP-STD"
    )
    _publish_version(client, admin_token, org_id, standard["id"], version_id)
    summary_resp = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version_id}",
        json={"summary": "This version's current standing."}, headers=auth_headers(admin_token),
    )
    assert summary_resp.status_code == 200, summary_resp.text
    clarify_resp = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version_id}/requirements/{child['id']}/clarify",
        json={"name": "Child Requirement", "reference": "1.1", "clarification_note": "Fixed a typo."},
        headers=auth_headers(admin_token),
    )
    assert clarify_resp.status_code == 200, clarify_resp.text

    doc = _export(client, admin_token, org_id, standard["id"])
    version_doc = doc["standard"]["versions"][0]
    assert version_doc["summary"] == "This version's current standing."
    child_doc = next(r for r in version_doc["requirements"] if r["name"] == "Child Requirement")
    assert child_doc["clarification_count"] == 1
    assert child_doc["last_clarification_note"] == "Fixed a typo."
    assert child_doc["last_clarified_at"] is not None
    assert child_doc["last_clarified_by_email"] is not None

    target_org, target_token = create_org_admin_in(client, admin_token, "Clarification Import Target")
    import_resp = _import(client, target_token, target_org["id"], doc)
    assert import_resp.status_code == 201, import_resp.text
    result = import_resp.json()

    new_versions = client.get(
        f"{_base(target_org['id'])}/standards/{result['standard']['id']}/versions", headers=auth_headers(target_token)
    ).json()
    assert new_versions[0]["summary"] == "This version's current standing."
    new_requirements = client.get(
        f"{_base(target_org['id'])}/standards/{result['standard']['id']}/versions/{new_versions[0]['id']}/requirements",
        headers=auth_headers(target_token),
    ).json()
    new_child = next(r for r in new_requirements if r["name"] == "Child Requirement")
    assert new_child["clarification_count"] == 1
    assert new_child["last_clarification_note"] == "Fixed a typo."
    assert new_child["last_clarified_at"] is not None
    assert new_child["last_clarified_by"] is not None


def test_import_across_orgs_lands_draft_regardless_of_source_status(client, admin_token, org_id):
    """§4/§31: an imported standard must be reviewed and re-published
    locally before it governs any project — even a *published* source
    version is re-created as `DRAFT`."""
    standard, version_id, parent, child, action_type, action = _build_standard_with_tree(client, admin_token, org_id, reference="PUB-STD")
    _publish_version(client, admin_token, org_id, standard["id"], version_id)
    doc = _export(client, admin_token, org_id, standard["id"])
    assert doc["standard"]["versions"][0]["status"] == "published"

    target_org, target_token = create_org_admin_in(client, admin_token, "Standard Import Target")
    resp = _import(client, target_token, target_org["id"], doc)
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert result["skipped"] is False
    assert result["standard"]["reference"] == "PUB-STD"

    versions = client.get(
        f"{_base(target_org['id'])}/standards/{result['standard']['id']}/versions", headers=auth_headers(target_token)
    ).json()
    assert len(versions) == 1
    assert versions[0]["status"] == "draft"
    assert versions[0]["published_at"] is None
    assert versions[0]["published_by"] is None

    requirements = client.get(
        f"{_base(target_org['id'])}/standards/{result['standard']['id']}/versions/{versions[0]['id']}/requirements",
        headers=auth_headers(target_token),
    ).json()
    assert len(requirements) == 2
    imported_child = next(r for r in requirements if r["name"] == "Child Requirement")
    imported_parent = next(r for r in requirements if r["name"] == "Parent Requirement")
    assert imported_child["parent_requirement_id"] == imported_parent["id"]

    actions = client.get(
        f"{_base(target_org['id'])}/standards/{result['standard']['id']}/versions/{versions[0]['id']}/"
        f"requirements/{imported_child['id']}/required-actions",
        headers=auth_headers(target_token),
    ).json()
    assert actions[0]["name"] == "Perform verification test"


def test_import_reference_collision_requires_resolution_then_skip_or_copy(client, admin_token, org_id):
    standard, *_ = _build_standard_with_tree(client, admin_token, org_id, reference="COLLIDE-STD")
    doc = _export(client, admin_token, org_id, standard["id"])

    # No resolution given, and the same org already has this reference -> 409.
    resp = _import(client, admin_token, org_id, doc)
    assert resp.status_code == 409, resp.text

    # "skip" -> nothing created.
    resp = _import(client, admin_token, org_id, doc, resolution="skip")
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert result["skipped"] is True
    assert result["standard"] is None
    standards_after_skip = client.get(f"{_base(org_id)}/standards", headers=auth_headers(admin_token)).json()
    assert sum(1 for s in standards_after_skip if s["reference"].startswith("COLLIDE-STD")) == 1

    # "import_as_copy" -> a second standard, reference suffixed.
    resp = _import(client, admin_token, org_id, doc, resolution="import_as_copy")
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert result["skipped"] is False
    assert result["standard"]["reference"] == "COLLIDE-STD (imported)"


def test_import_rejects_invalid_resolution_value(client, admin_token, org_id):
    standard, *_ = _build_standard_with_tree(client, admin_token, org_id, reference="BAD-RES-STD")
    doc = _export(client, admin_token, org_id, standard["id"])
    resp = _import(client, admin_token, org_id, doc, resolution="overwrite")
    assert resp.status_code == 400, resp.text


def test_import_drops_unresolvable_cross_standard_mapping_with_warning(client, admin_token, org_id):
    """A requirement mapping whose *other* side belongs to a different
    standard is included in the export, but dropped with a warning on
    import when the target organisation has no matching standard — never
    silently fabricated, never resolved against the wrong thing."""
    standard_a, version_a, parent_a, child_a, _at, _act = _build_standard_with_tree(client, admin_token, org_id, reference="MAP-A")
    standard_b, version_b, parent_b, child_b, _bt, _bct = _build_standard_with_tree(client, admin_token, org_id, reference="MAP-B")
    rel_type = _create_relationship_type(client, admin_token, org_id, name="Equivalent")
    _create_mapping(client, admin_token, org_id, from_id=child_a["id"], to_id=child_b["id"], relationship_type_id=rel_type["id"])

    doc = _export(client, admin_token, org_id, standard_a["id"])
    assert len(doc["requirement_mappings"]) == 1
    mapping_doc = doc["requirement_mappings"][0]
    assert mapping_doc["to"]["ref"] is None
    assert mapping_doc["to"]["external"]["standard_reference"] == "MAP-B"

    target_org, target_token = create_org_admin_in(client, admin_token, "Mapping Drop Target")
    resp = _import(client, target_token, target_org["id"], doc)
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert any("mapping" in w.lower() for w in result["warnings"])
    mappings = client.get(f"{_base(target_org['id'])}/requirement-mappings", headers=auth_headers(target_token)).json()
    assert mappings == []


def test_import_resolves_cross_standard_mapping_against_matching_target_standard(client, admin_token, org_id):
    """The reverse of the drop case above: when the target organisation
    already has a standard/version/requirement matching the external side's
    `(reference, version_label, requirement_key)`, the mapping IS created."""
    standard_a, version_a, parent_a, child_a, _at, _act = _build_standard_with_tree(client, admin_token, org_id, reference="RESOLVE-A")
    standard_b, version_b, parent_b, child_b, _bt, _bct = _build_standard_with_tree(client, admin_token, org_id, reference="RESOLVE-B")
    rel_type = _create_relationship_type(client, admin_token, org_id, name="Related To")
    _create_mapping(client, admin_token, org_id, from_id=child_a["id"], to_id=child_b["id"], relationship_type_id=rel_type["id"])
    doc = _export(client, admin_token, org_id, standard_a["id"])

    target_org, target_token = create_org_admin_in(client, admin_token, "Mapping Resolve Target")
    # Re-create standard B in the target org with the identical reference/
    # version_label/requirement (reference, name) key the export's
    # "external" side names, so the mapping's other side can resolve there.
    target_b, target_version_b, _tp, target_child_b, _tat, _tact = _build_standard_with_tree(
        client, target_token, target_org["id"], reference="RESOLVE-B"
    )

    resp = _import(client, target_token, target_org["id"], doc)
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert result["warnings"] == []
    mappings = client.get(f"{_base(target_org['id'])}/requirement-mappings", headers=auth_headers(target_token)).json()
    assert len(mappings) == 1
    assert mappings[0]["to_requirement_id"] == target_child_b["id"]


def test_export_and_import_are_manage_gated(client, admin_token, org_id):
    standard, *_ = _build_standard_with_tree(client, admin_token, org_id, reference="RBAC-STD")
    doc = _export(client, admin_token, org_id, standard["id"])

    create_org_user(client, admin_token, org_id, "plain-member-io@example.com", role="member")
    member_token = login(client, "plain-member-io@example.com", "Password123!")

    resp = client.get(f"{_base(org_id)}/standards/{standard['id']}/export", headers=auth_headers(member_token))
    assert resp.status_code == 403, resp.text

    resp = _import(client, member_token, org_id, doc, resolution="import_as_copy")
    assert resp.status_code == 403, resp.text
