"""Tests for the Compliance Module's Phase 11 Cross-Standard Mapping +
Version Impact (docs/compliance-module-plan.md Phase 11; docs/Compliance_
Module_Requirements.md §19, §27): the org-scoped, extensible mapping-
relationship-type vocabulary, the `ComplianceRequirementMapping` CRUD
surface (visibility from both requirements, navigation, cross-org
isolation, audit logging), the added/removed/modified/replaced/re-mapped
version-diff endpoint (built from real cloned + then independently edited
requirement trees, not fabricated JSON), and the explicit, user-triggered
project version-migration action (carrying forward unmodified assessments,
downgrading an approved carried-forward row to `requires_reassessment`, a
modified/added requirement landing at defaults, and the old assignment
staying archived-not-deleted with its own historical assessments
completely untouched).

Reuses `test_compliance_standards_api.py`'s and `test_project_compliance_
api.py`'s helpers for setup, the same way `test_compliance_evidence_api.py`/
`test_compliance_approval_workflow.py` already do.
"""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.compliance.tests.test_compliance_standards_api import (
    _base,
    _create_requirement,
    _create_standard,
    _create_version,
)
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_project_role,
    _assign_standard_to_project,
    _grant_compliance_officer,
    _project_base,
    _publish_version,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_org_user, create_project, login

# --- Small helpers -----------------------------------------------------------------


def _create_relationship_type(client, token, org_id, *, name="Equivalent", implies_equivalence=False):
    resp = client.post(
        f"{_base(org_id)}/mapping-relationship-types",
        json={"name": name, "implies_equivalence": implies_equivalence},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_mapping(client, token, org_id, *, from_id, to_id, relationship_type_id, **extra):
    payload = {
        "from_requirement_id": from_id, "to_requirement_id": to_id,
        "relationship_type_id": relationship_type_id, **extra,
    }
    resp = client.post(f"{_base(org_id)}/requirement-mappings", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _requirements_by_reference(client, token, org_id, standard_id, version_id):
    resp = client.get(f"{_base(org_id)}/standards/{standard_id}/versions/{version_id}/requirements", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {r["reference"]: r for r in resp.json()}


def _diff(client, token, org_id, standard_id, version_id, other_version_id):
    resp = client.get(
        f"{_base(org_id)}/standards/{standard_id}/versions/{version_id}/diff/{other_version_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Mapping relationship-type vocabulary (§19: configurable/extensible) --------


def test_create_list_rename_relationship_type(client, admin_token, org_id):
    created = _create_relationship_type(client, admin_token, org_id, name="Satisfies")
    assert created["name"] == "Satisfies"
    assert created["sort_order"] == 0
    assert created["implies_equivalence"] is False  # defaults off

    listed = client.get(f"{_base(org_id)}/mapping-relationship-types", headers=auth_headers(admin_token))
    assert listed.status_code == 200
    assert [t["name"] for t in listed.json()] == ["Satisfies"]

    renamed = client.patch(
        f"{_base(org_id)}/mapping-relationship-types/{created['id']}",
        json={"name": "Derived From", "implies_equivalence": False},
        headers=auth_headers(admin_token),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Derived From"


def test_relationship_type_implies_equivalence_create_and_toggle(client, admin_token, org_id):
    """§27's migration-carry-forward gate (`models.py`'s own Phase 11
    notes on `ComplianceMappingRelationshipTypeDefinition.implies_
    equivalence`) is an org-level, Compliance-Manager-only decision made on
    the relationship-type vocabulary itself, independent of any specific
    mapping."""
    created = _create_relationship_type(client, admin_token, org_id, name="Equivalent", implies_equivalence=True)
    assert created["implies_equivalence"] is True

    toggled_off = client.patch(
        f"{_base(org_id)}/mapping-relationship-types/{created['id']}",
        json={"name": "Equivalent", "implies_equivalence": False},
        headers=auth_headers(admin_token),
    )
    assert toggled_off.status_code == 200, toggled_off.text
    assert toggled_off.json()["implies_equivalence"] is False

    toggled_on = client.patch(
        f"{_base(org_id)}/mapping-relationship-types/{created['id']}",
        json={"name": "Equivalent", "implies_equivalence": True},
        headers=auth_headers(admin_token),
    )
    assert toggled_on.status_code == 200, toggled_on.text
    assert toggled_on.json()["implies_equivalence"] is True


def test_relationship_type_duplicate_name_rejected(client, admin_token, org_id):
    _create_relationship_type(client, admin_token, org_id, name="Overlaps")
    dup = client.post(
        f"{_base(org_id)}/mapping-relationship-types", json={"name": "Overlaps"}, headers=auth_headers(admin_token)
    )
    assert dup.status_code == 400


def test_relationship_type_delete_requires_reassignment_when_in_use(client, admin_token, org_id):
    standard, version, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    equivalent = _create_relationship_type(client, admin_token, org_id, name="Equivalent")
    related = _create_relationship_type(client, admin_token, org_id, name="Related To")
    _create_mapping(client, admin_token, org_id, from_id=parent["id"], to_id=child["id"], relationship_type_id=equivalent["id"])

    blocked = client.delete(f"{_base(org_id)}/mapping-relationship-types/{equivalent['id']}", headers=auth_headers(admin_token))
    assert blocked.status_code == 409, blocked.text

    reassigned = client.delete(
        f"{_base(org_id)}/mapping-relationship-types/{equivalent['id']}?reassign_to_id={related['id']}",
        headers=auth_headers(admin_token),
    )
    assert reassigned.status_code == 204, reassigned.text


def test_relationship_type_manager_only_plain_member_forbidden(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "rel-type-member@example.com", role="member")
    member_token = login(client, "rel-type-member@example.com", "Password123!")
    forbidden = client.post(
        f"{_base(org_id)}/mapping-relationship-types", json={"name": "Conflicts With"}, headers=auth_headers(member_token)
    )
    assert forbidden.status_code == 403
    # Any member may still list (view-gated, not manage-gated).
    listing = client.get(f"{_base(org_id)}/mapping-relationship-types", headers=auth_headers(member_token))
    assert listing.status_code == 200


# --- Requirement mapping CRUD (§19) -------------------------------------------------


def test_create_mapping_visible_from_both_requirements_and_navigable(client, admin_token, org_id):
    standard, version, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    relationship_type = _create_relationship_type(client, admin_token, org_id, name="Related To")

    mapping = _create_mapping(
        client, admin_token, org_id, from_id=parent["id"], to_id=child["id"],
        relationship_type_id=relationship_type["id"], notes="Same section, closely related.",
    )
    assert mapping["from_requirement_id"] == parent["id"]
    assert mapping["to_requirement_id"] == child["id"]
    assert mapping["is_archived"] is False

    # Visible/navigable from the "from" side.
    from_side = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{parent['id']}/mappings",
        headers=auth_headers(admin_token),
    )
    assert from_side.status_code == 200
    assert [m["id"] for m in from_side.json()] == [mapping["id"]]

    # And from the "to" side — §19's "must be visible from both requirements".
    to_side = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{child['id']}/mappings",
        headers=auth_headers(admin_token),
    )
    assert to_side.status_code == 200
    assert [m["id"] for m in to_side.json()] == [mapping["id"]]

    # Also navigable via the flatter, org-scoped listing filtered by either id.
    flat_from = client.get(f"{_base(org_id)}/requirement-mappings?requirement_id={parent['id']}", headers=auth_headers(admin_token))
    flat_to = client.get(f"{_base(org_id)}/requirement-mappings?requirement_id={child['id']}", headers=auth_headers(admin_token))
    assert [m["id"] for m in flat_from.json()] == [mapping["id"]]
    assert [m["id"] for m in flat_to.json()] == [mapping["id"]]

    fetched = client.get(f"{_base(org_id)}/requirement-mappings/{mapping['id']}", headers=auth_headers(admin_token))
    assert fetched.status_code == 200
    assert fetched.json()["notes"] == "Same section, closely related."


def test_mapping_self_link_rejected(client, admin_token, org_id):
    _standard, _version, parent, _child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    relationship_type = _create_relationship_type(client, admin_token, org_id)
    resp = client.post(
        f"{_base(org_id)}/requirement-mappings",
        json={"from_requirement_id": parent["id"], "to_requirement_id": parent["id"], "relationship_type_id": relationship_type["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_mapping_duplicate_exact_relationship_rejected(client, admin_token, org_id):
    _standard, _version, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    relationship_type = _create_relationship_type(client, admin_token, org_id)
    _create_mapping(client, admin_token, org_id, from_id=parent["id"], to_id=child["id"], relationship_type_id=relationship_type["id"])
    dup = client.post(
        f"{_base(org_id)}/requirement-mappings",
        json={"from_requirement_id": parent["id"], "to_requirement_id": child["id"], "relationship_type_id": relationship_type["id"]},
        headers=auth_headers(admin_token),
    )
    assert dup.status_code == 400

    # But a *different* relationship type between the same pair is allowed —
    # nothing in §19 limits a pair to a single relationship.
    other_type = _create_relationship_type(client, admin_token, org_id, name="Overlaps")
    second = client.post(
        f"{_base(org_id)}/requirement-mappings",
        json={"from_requirement_id": parent["id"], "to_requirement_id": child["id"], "relationship_type_id": other_type["id"]},
        headers=auth_headers(admin_token),
    )
    assert second.status_code == 201, second.text


def test_mapping_cross_org_requirement_is_404_not_403(client, admin_token, org_id):
    _standard, _version, parent, _child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    relationship_type = _create_relationship_type(client, admin_token, org_id)

    other_org = client.post(
        "/api/v1/orgs", json={"name": "Other Compliance Org"}, headers=auth_headers(admin_token)
    ).json()
    other_standard, other_version, other_parent, _oc, _opa, _oca = _setup_published_standard_with_tree(
        client, admin_token, other_org["id"]
    )

    resp = client.post(
        f"{_base(org_id)}/requirement-mappings",
        json={
            "from_requirement_id": parent["id"], "to_requirement_id": other_parent["id"],
            "relationship_type_id": relationship_type["id"],
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_archive_unarchive_mapping_and_audit_logged(client, admin_token, org_id):
    standard, _version, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    relationship_type = _create_relationship_type(client, admin_token, org_id)
    mapping = _create_mapping(client, admin_token, org_id, from_id=parent["id"], to_id=child["id"], relationship_type_id=relationship_type["id"])

    archived = client.post(f"{_base(org_id)}/requirement-mappings/{mapping['id']}/archive", headers=auth_headers(admin_token))
    assert archived.status_code == 200, archived.text
    assert archived.json()["is_archived"] is True

    # Archived mappings are excluded from the default listing...
    default_listing = client.get(f"{_base(org_id)}/requirement-mappings?requirement_id={parent['id']}", headers=auth_headers(admin_token))
    assert default_listing.json() == []
    # ...but still visible with include_archived=true.
    with_archived = client.get(
        f"{_base(org_id)}/requirement-mappings?requirement_id={parent['id']}&include_archived=true", headers=auth_headers(admin_token)
    )
    assert [m["id"] for m in with_archived.json()] == [mapping["id"]]

    unarchived = client.post(f"{_base(org_id)}/requirement-mappings/{mapping['id']}/unarchive", headers=auth_headers(admin_token))
    assert unarchived.status_code == 200
    assert unarchived.json()["is_archived"] is False

    db = SessionLocal()
    try:
        events = {
            (e.entity_type, e.action)
            for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_id == str(mapping["id"]))).all()
        }
    finally:
        db.close()
    assert ("compliance_requirement_mapping", "created") in events
    assert ("compliance_requirement_mapping", "archived") in events
    assert ("compliance_requirement_mapping", "unarchived") in events


def test_mapping_manager_only_plain_member_forbidden_but_can_view(client, admin_token, org_id):
    _standard, _version, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    relationship_type = _create_relationship_type(client, admin_token, org_id)

    create_org_user(client, admin_token, org_id, "mapping-member@example.com", role="member")
    member_token = login(client, "mapping-member@example.com", "Password123!")

    forbidden = client.post(
        f"{_base(org_id)}/requirement-mappings",
        json={"from_requirement_id": parent["id"], "to_requirement_id": child["id"], "relationship_type_id": relationship_type["id"]},
        headers=auth_headers(member_token),
    )
    assert forbidden.status_code == 403

    mapping = _create_mapping(client, admin_token, org_id, from_id=parent["id"], to_id=child["id"], relationship_type_id=relationship_type["id"])
    can_view = client.get(f"{_base(org_id)}/requirement-mappings/{mapping['id']}", headers=auth_headers(member_token))
    assert can_view.status_code == 200


# --- Version diff (§27) -------------------------------------------------------------


def _build_two_flat_requirements_standard(client, admin_token, org_id, *, reference="DIFF-STD"):
    """Standard -> published v1 with two independent, top-level
    requirements ("A"/"B", no parent/child nesting) — kept deliberately
    flat so deleting one clone in v2 can't cascade into deleting another
    (unlike `_setup_published_standard_with_tree`'s parent/child shape),
    keeping each diff test's requirement counts exact and easy to assert
    on. Returns (standard, version1, req_a, req_b)."""
    standard = _create_standard(client, admin_token, org_id, reference=reference, name=f"{reference} Standard")
    version1 = _create_version(client, admin_token, org_id, standard["id"], version_label="1.0")
    req_a = _create_requirement(client, admin_token, org_id, standard["id"], version1["id"], name="Requirement A", reference="A")
    req_b = _create_requirement(client, admin_token, org_id, standard["id"], version1["id"], name="Requirement B", reference="B")
    _publish_version(client, admin_token, org_id, standard["id"], version1["id"])
    return standard, version1, req_a, req_b


def test_diff_identifies_added_removed_modified(client, admin_token, org_id):
    standard, version1, req_a, req_b = _build_two_flat_requirements_standard(client, admin_token, org_id)

    version2 = _create_version(
        client, admin_token, org_id, standard["id"], version_label="2.0", clone_from_version_id=version1["id"]
    )
    clones = _requirements_by_reference(client, admin_token, org_id, standard["id"], version2["id"])
    clone_a, clone_b = clones["A"], clones["B"]

    # "modified": edit clone B's name in the still-draft v2.
    updated = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version2['id']}/requirements/{clone_b['id']}",
        json={"reference": "B", "name": "Requirement B (revised)", "description": "", "reasoning": ""},
        headers=auth_headers(admin_token),
    )
    assert updated.status_code == 200, updated.text

    # "removed": delete clone A outright — nothing in v2 traces lineage
    # back to req_a any more.
    deleted = client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version2['id']}/requirements/{clone_a['id']}",
        headers=auth_headers(admin_token),
    )
    assert deleted.status_code == 204

    # "added": a brand-new requirement authored directly in v2, never cloned.
    req_c = _create_requirement(client, admin_token, org_id, standard["id"], version2["id"], name="Requirement C", reference="C")

    _publish_version(client, admin_token, org_id, standard["id"], version2["id"])

    diff = _diff(client, admin_token, org_id, standard["id"], version1["id"], version2["id"])
    assert diff["old_version_id"] == version1["id"]
    assert diff["new_version_id"] == version2["id"]

    assert [r["requirement"]["id"] for r in diff["added"]] == [req_c["id"]]
    assert [r["requirement"]["id"] for r in diff["removed"]] == [req_a["id"]]
    assert len(diff["modified"]) == 1
    modified = diff["modified"][0]
    assert modified["old_requirement"]["id"] == req_b["id"]
    assert modified["new_requirement"]["id"] == clone_b["id"]
    assert modified["changed_fields"] == ["name"]
    assert diff["replaced"] == []
    assert diff["re_mapped"] == []

    # Order-independence: swapping which version_id appears first in the
    # URL must not change which side is reported as old/new.
    reversed_diff = _diff(client, admin_token, org_id, standard["id"], version2["id"], version1["id"])
    assert reversed_diff == diff


def test_diff_rejects_same_version_and_cross_standard_version(client, admin_token, org_id):
    standard, version1, _a, _b = _build_two_flat_requirements_standard(client, admin_token, org_id, reference="DIFF-SELF")
    same = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version1['id']}/diff/{version1['id']}",
        headers=auth_headers(admin_token),
    )
    assert same.status_code == 400

    other_standard, other_version1, _oa, _ob = _build_two_flat_requirements_standard(client, admin_token, org_id, reference="DIFF-OTHER")
    cross = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version1['id']}/diff/{other_version1['id']}",
        headers=auth_headers(admin_token),
    )
    assert cross.status_code == 404


def test_diff_identifies_replaced_via_explicit_mapping(client, admin_token, org_id):
    standard, version1, req_a, _req_b = _build_two_flat_requirements_standard(client, admin_token, org_id, reference="DIFF-REPLACE")
    version2 = _create_version(
        client, admin_token, org_id, standard["id"], version_label="2.0", clone_from_version_id=version1["id"]
    )
    clones = _requirements_by_reference(client, admin_token, org_id, standard["id"], version2["id"])

    # Delete clone A outright (so req_a has no lineage-matched successor)
    # and author a brand-new requirement to replace it, explicitly linked
    # back to req_a — the "same-standard, cross-version" mapping use this
    # module's own docs describe as the "replaced" marker.
    client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version2['id']}/requirements/{clones['A']['id']}",
        headers=auth_headers(admin_token),
    )
    successor = _create_requirement(client, admin_token, org_id, standard["id"], version2["id"], name="Requirement A2", reference="A2")
    # "Derived From" is deliberately *not* marked `implies_equivalence` —
    # this pair must still show up as `replaced`, but not be eligible for
    # migration carry-forward (see `test_migrate_*` below).
    relationship_type = _create_relationship_type(client, admin_token, org_id, name="Derived From")
    mapping = _create_mapping(
        client, admin_token, org_id, from_id=successor["id"], to_id=req_a["id"], relationship_type_id=relationship_type["id"],
    )

    _publish_version(client, admin_token, org_id, standard["id"], version2["id"])

    diff = _diff(client, admin_token, org_id, standard["id"], version1["id"], version2["id"])
    assert diff["added"] == []  # the successor is "replaced", not "added"
    assert [r["requirement"]["id"] for r in diff["removed"]] == []  # req_a is "replaced", not "removed"
    assert len(diff["replaced"]) == 1
    replaced = diff["replaced"][0]
    assert replaced["old_requirement"]["id"] == req_a["id"]
    assert replaced["new_requirement"]["id"] == successor["id"]
    assert replaced["mapping_id"] == mapping["id"]
    assert replaced["relationship_type_id"] == relationship_type["id"]
    assert replaced["implies_equivalence"] is False


def test_diff_replaced_surfaces_implies_equivalence_true(client, admin_token, org_id):
    """Same shape as `test_diff_identifies_replaced_via_explicit_mapping`,
    but the mapping's own relationship type *is* marked `implies_
    equivalence` — the diff must surface that flag on the `replaced` entry
    itself (denormalised, per `schemas.ReplacedRequirementOut`'s own
    docstring) so a caller can decide what to confirm at migration time
    without a second lookup against the relationship-types list."""
    standard, version1, req_a, _req_b = _build_two_flat_requirements_standard(client, admin_token, org_id, reference="DIFF-REPLACE-EQ")
    version2 = _create_version(
        client, admin_token, org_id, standard["id"], version_label="2.0", clone_from_version_id=version1["id"]
    )
    clones = _requirements_by_reference(client, admin_token, org_id, standard["id"], version2["id"])
    client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version2['id']}/requirements/{clones['A']['id']}",
        headers=auth_headers(admin_token),
    )
    successor = _create_requirement(client, admin_token, org_id, standard["id"], version2["id"], name="Requirement A2", reference="A2")
    relationship_type = _create_relationship_type(client, admin_token, org_id, name="Equivalent", implies_equivalence=True)
    _create_mapping(
        client, admin_token, org_id, from_id=successor["id"], to_id=req_a["id"], relationship_type_id=relationship_type["id"],
    )
    _publish_version(client, admin_token, org_id, standard["id"], version2["id"])

    diff = _diff(client, admin_token, org_id, standard["id"], version1["id"], version2["id"])
    assert len(diff["replaced"]) == 1
    assert diff["replaced"][0]["implies_equivalence"] is True


def test_diff_identifies_re_mapped_requirement(client, admin_token, org_id):
    standard, version1, req_a, req_b = _build_two_flat_requirements_standard(client, admin_token, org_id, reference="DIFF-REMAP")
    # An external standard whose requirement req_a is cross-mapped to.
    ext_standard, ext_version1, req_ext, _req_ext_b = _build_two_flat_requirements_standard(
        client, admin_token, org_id, reference="DIFF-REMAP-EXT"
    )
    relationship_type = _create_relationship_type(client, admin_token, org_id, name="Related To")
    _create_mapping(client, admin_token, org_id, from_id=req_a["id"], to_id=req_ext["id"], relationship_type_id=relationship_type["id"])

    # Clone forward with req_a's content completely unchanged — its mapping
    # is not carried over (mappings are never auto-cloned).
    version2 = _create_version(
        client, admin_token, org_id, standard["id"], version_label="2.0", clone_from_version_id=version1["id"]
    )
    clones = _requirements_by_reference(client, admin_token, org_id, standard["id"], version2["id"])
    _publish_version(client, admin_token, org_id, standard["id"], version2["id"])

    diff = _diff(client, admin_token, org_id, standard["id"], version1["id"], version2["id"])
    assert diff["added"] == []
    assert diff["removed"] == []
    assert diff["modified"] == []
    assert len(diff["re_mapped"]) == 1
    re_mapped = diff["re_mapped"][0]
    assert re_mapped["old_requirement"]["id"] == req_a["id"]
    assert re_mapped["new_requirement"]["id"] == clones["A"]["id"]
    assert re_mapped["old_mapping_target_requirement_ids"] == [req_ext["id"]]
    assert re_mapped["new_mapping_target_requirement_ids"] == []
    # req_b (never mapped to anything) must not show up as re-mapped.
    assert all(r["old_requirement"]["id"] != req_b["id"] for r in diff["re_mapped"])


# --- Version migration (§27) --------------------------------------------------------


def _migrate(client, token, project_id, project_compliance_id, new_standard_version_id, *, confirmed_replacement_requirement_ids=None):
    payload = {"new_standard_version_id": new_standard_version_id}
    if confirmed_replacement_requirement_ids is not None:
        payload["confirmed_replacement_requirement_ids"] = confirmed_replacement_requirement_ids
    return client.post(
        f"{_project_base(project_id)}/project-compliance/{project_compliance_id}/migrate-version",
        json=payload,
        headers=auth_headers(token),
    )


def _setup_migration_scenario(client, admin_token, org_id, *, project_name="Migration Project"):
    """Standard -> published v1 (parent + child requirements) -> assigned
    to a project -> parent approved, child assessed-but-not-approved ->
    v2 cloned from v1, child's clone content edited (modified), a brand
    new requirement authored directly in v2 (added), parent's clone left
    untouched (unchanged) -> v2 published.

    Returns (project, assignment1, standard, version1, version2, parent,
    child, parent_pcr_id, child_pcr_id)."""
    standard, version1, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name=project_name)
    assignment1 = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version1["id"])

    pcrs = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements", headers=auth_headers(admin_token)
    ).json()
    parent_pcr_id = next(p["id"] for p in pcrs if p["requirement_id"] == parent["id"])
    child_pcr_id = next(p["id"] for p in pcrs if p["requirement_id"] == child["id"])

    # Parent: assess -> submit -> approve.
    client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements/{parent_pcr_id}/assessment",
        json={"compliance_status": "compliant", "justification": "", "notes": "Parent looks good."},
        headers=auth_headers(admin_token),
    )
    client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements/{parent_pcr_id}/submit-for-approval",
        headers=auth_headers(admin_token),
    )
    approved = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements/{parent_pcr_id}/approve",
        json={"decision_note": "Signed off."}, headers=auth_headers(admin_token),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_state"] == "approved"

    # Child: assessed only, never submitted for approval.
    assessed = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements/{child_pcr_id}/assessment",
        json={"compliance_status": "in_progress", "justification": "", "notes": "Still checking child."},
        headers=auth_headers(admin_token),
    )
    assert assessed.status_code == 200, assessed.text
    assert assessed.json()["approval_state"] == "assessed"

    version2 = _create_version(
        client, admin_token, org_id, standard["id"], version_label="2.0-next", clone_from_version_id=version1["id"]
    )
    clones = _requirements_by_reference(client, admin_token, org_id, standard["id"], version2["id"])
    client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version2['id']}/requirements/{clones['4.1']['id']}",
        json={"reference": "4.1", "name": "Temperature (revised)", "description": "", "reasoning": ""},
        headers=auth_headers(admin_token),
    )
    new_requirement = _create_requirement(
        client, admin_token, org_id, standard["id"], version2["id"], name="Brand new requirement", reference="9"
    )
    _publish_version(client, admin_token, org_id, standard["id"], version2["id"])

    return {
        "project": project, "assignment1": assignment1, "standard": standard,
        "version1": version1, "version2": version2, "parent": parent, "child": child,
        "parent_pcr_id": parent_pcr_id, "child_pcr_id": child_pcr_id, "new_requirement": new_requirement,
        # The v2 *clones* of parent/child — a migration's `requirement_impacts`
        # are keyed by the *new*-version requirement id, not the old one, so
        # tests asserting on them need these, not `parent`/`child` themselves.
        "parent_clone": clones["4"], "child_clone": clones["4.1"],
    }


def test_migrate_carries_forward_unmodified_and_downgrades_approved(client, admin_token, org_id):
    ctx = _setup_migration_scenario(client, admin_token, org_id)
    project, assignment1 = ctx["project"], ctx["assignment1"]

    result = _migrate(client, admin_token, project["id"], assignment1["id"], ctx["version2"]["id"])
    assert result.status_code == 201, result.text
    body = result.json()

    assert body["new_project_compliance"]["standard_version_id"] == ctx["version2"]["id"]
    assert body["previous_project_compliance_id"] == assignment1["id"]
    assert body["previous_standard_version_id"] == ctx["version1"]["id"]
    assert body["total_requirements"] == 3  # parent (unchanged) + child (modified) + new_requirement (added)
    assert body["carried_forward_count"] == 1
    assert body["added_count"] == 1
    assert body["modified_count"] == 1
    assert body["requires_reassessment_count"] == 3  # downgraded parent + modified child + added requirement

    # `requirement_impacts` are keyed by the *new*-version requirement id
    # (the parent/child *clones* in v2), not the old version's own
    # requirement id — the new-version requirement is what the migrated
    # assignment actually has a row for.
    impacts_by_requirement = {i["requirement_id"]: i for i in body["requirement_impacts"]}
    parent_impact = impacts_by_requirement[ctx["parent_clone"]["id"]]
    assert parent_impact["change"] == "unchanged"
    assert parent_impact["carried_forward"] is True
    assert parent_impact["requires_reassessment"] is True  # was approved -> downgraded

    child_impact = impacts_by_requirement[ctx["child_clone"]["id"]]
    assert child_impact["change"] == "modified"
    assert child_impact["carried_forward"] is False
    assert child_impact["requires_reassessment"] is True

    new_req_impact = impacts_by_requirement[ctx["new_requirement"]["id"]]
    assert new_req_impact["change"] == "added"
    assert new_req_impact["carried_forward"] is False
    assert new_req_impact["requires_reassessment"] is True

    new_project_compliance_id = body["new_project_compliance"]["id"]
    new_pcrs = client.get(
        f"{_project_base(project['id'])}/project-compliance/{new_project_compliance_id}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    new_parent_pcr = next(p for p in new_pcrs if p["requirement_id"] == ctx["parent_clone"]["id"])
    new_child_pcr = next(p for p in new_pcrs if p["requirement_id"] == ctx["child_clone"]["id"])

    # Carried forward: same content, but approval downgraded, not silently
    # re-approved.
    assert new_parent_pcr["compliance_status"] == "compliant"
    assert new_parent_pcr["notes"] == "Parent looks good."
    assert new_parent_pcr["approval_state"] == "requires_reassessment"
    assert new_parent_pcr["assessed_by"] is not None
    # A fresh sign-off decision is required — the old decision isn't
    # silently carried over onto the new row.
    assert new_parent_pcr["approval_decided_at"] is None
    assert new_parent_pcr["decision_note"] == ""

    # Modified requirement left at defaults, not carried forward.
    assert new_child_pcr["compliance_status"] == "not_started"
    assert new_child_pcr["approval_state"] == "not_assessed"
    assert new_child_pcr["notes"] == ""


def test_migrate_does_not_change_old_assignment_or_its_assessments(client, admin_token, org_id):
    """The load-bearing "must not silently change historical compliance
    assessments" guarantee (§27) — the old `ProjectCompliance` row is
    archived (not deleted), and every one of its own `ProjectCompliance
    Requirement` rows is byte-for-byte unchanged after migration."""
    ctx = _setup_migration_scenario(client, admin_token, org_id)
    project, assignment1 = ctx["project"], ctx["assignment1"]

    before = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()

    migrated = _migrate(client, admin_token, project["id"], assignment1["id"], ctx["version2"]["id"])
    assert migrated.status_code == 201, migrated.text

    old_assignment = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}", headers=auth_headers(admin_token)
    ).json()
    assert old_assignment["is_archived"] is True
    assert old_assignment["archived_at"] is not None
    assert old_assignment["standard_version_id"] == ctx["version1"]["id"], (
        "the old assignment must remain pinned to its original version forever (§27)"
    )

    after = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    assert after == before, "the old assignment's own assessment rows must be completely untouched by migration"


def test_migrate_requires_newer_published_version_of_same_standard(client, admin_token, org_id):
    ctx = _setup_migration_scenario(client, admin_token, org_id)
    project, assignment1 = ctx["project"], ctx["assignment1"]

    # Same version: not "newer".
    same = _migrate(client, admin_token, project["id"], assignment1["id"], ctx["version1"]["id"])
    assert same.status_code == 400

    # A draft version: not published.
    draft_v2 = _create_version(client, admin_token, org_id, ctx["standard"]["id"], version_label="draft-3.0")
    draft = _migrate(client, admin_token, project["id"], assignment1["id"], draft_v2["id"])
    assert draft.status_code == 409

    # A different standard's version entirely.
    _other_standard, other_v1, _a, _b = _build_two_flat_requirements_standard(
        client, admin_token, org_id, reference="MIGRATE-CROSS-STD"
    )
    cross_standard = _migrate(client, admin_token, project["id"], assignment1["id"], other_v1["id"])
    assert cross_standard.status_code == 400


def test_migrate_rejects_when_already_assigned_to_target_version_and_when_archived(client, admin_token, org_id):
    ctx = _setup_migration_scenario(client, admin_token, org_id)
    project, assignment1 = ctx["project"], ctx["assignment1"]

    # Pre-existing direct assignment to v2 blocks migrating onto it too.
    _assign_standard_to_project(client, admin_token, org_id, project["id"], ctx["standard"]["id"], ctx["version2"]["id"])
    blocked = _migrate(client, admin_token, project["id"], assignment1["id"], ctx["version2"]["id"])
    assert blocked.status_code == 400

    archive_resp = client.post(
        f"{_base(org_id)}/projects/{project['id']}/project-compliance/{assignment1['id']}/archive",
        headers=auth_headers(admin_token),
    )
    assert archive_resp.status_code == 200, archive_resp.text
    archived_source = _migrate(client, admin_token, project["id"], assignment1["id"], ctx["version2"]["id"])
    assert archived_source.status_code == 409


def test_migrate_rbac_officer_and_pm_allowed_plain_member_forbidden(client, admin_token, org_id):
    ctx = _setup_migration_scenario(client, admin_token, org_id, project_name="RBAC Migration Project")
    project, assignment1 = ctx["project"], ctx["assignment1"]

    plain_id = create_org_user(client, admin_token, org_id, "migrate-plain@example.com", role="member")
    officer_id = create_org_user(client, admin_token, org_id, "migrate-officer@example.com", role="member")
    _assign_project_role(client, admin_token, project["id"], plain_id, "stakeholder")
    _assign_project_role(client, admin_token, project["id"], officer_id, "stakeholder")
    _grant_compliance_officer(client, admin_token, project["id"], officer_id)

    plain_token = login(client, "migrate-plain@example.com", "Password123!")
    forbidden = _migrate(client, plain_token, project["id"], assignment1["id"], ctx["version2"]["id"])
    assert forbidden.status_code == 403

    officer_token = login(client, "migrate-officer@example.com", "Password123!")
    allowed = _migrate(client, officer_token, project["id"], assignment1["id"], ctx["version2"]["id"])
    assert allowed.status_code == 201, allowed.text


def test_migrate_cross_project_isolation(client, admin_token, org_id):
    ctx = _setup_migration_scenario(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id, name="Unrelated Project")
    wrong_project_migration = _migrate(client, admin_token, other_project["id"], ctx["assignment1"]["id"], ctx["version2"]["id"])
    assert wrong_project_migration.status_code == 404


def test_migrate_logs_audit_events(client, admin_token, org_id):
    ctx = _setup_migration_scenario(client, admin_token, org_id)
    project, assignment1 = ctx["project"], ctx["assignment1"]
    result = _migrate(client, admin_token, project["id"], assignment1["id"], ctx["version2"]["id"])
    assert result.status_code == 201, result.text
    new_id = result.json()["new_project_compliance"]["id"]

    db = SessionLocal()
    try:
        old_events = {
            e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_id == str(assignment1["id"]))).all()
        }
        new_events = {
            e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_id == str(new_id))).all()
        }
    finally:
        db.close()
    assert "archived" in old_events
    assert "migrated" in new_events


# --- Confirmed carry-forward across a `replaced` mapping (§27 follow-up) -----------
#
# Direct feedback on the original Phase 11 implementation: always treating a
# `replaced` requirement like `added` (nothing ever carried forward) was too
# blunt when a Compliance Manager has already judged two requirements
# genuinely equivalent (e.g. an old "IPX6 water ingress" requirement
# explicitly linked to a new "IP67 water ingress" requirement). This section
# covers the two-gate mechanism added in response: `ComplianceMappingRelationshipTypeDefinition.
# implies_equivalence` (org-level) and `ProjectComplianceMigrationRequest.
# confirmed_replacement_requirement_ids` (per-migration, per-requirement).


def _setup_migration_scenario_with_replacement(client, admin_token, org_id, *, implies_equivalence, project_name="Replacement Migration Project"):
    """Standard -> published v1 (parent + child) -> assigned to a project ->
    parent assessed/submitted/approved -> v2 cloned from v1, parent's clone
    deleted outright and replaced by a brand-new, explicitly mapped
    successor requirement (child's clone left unchanged) -> v2 published.

    Returns a dict with the project/assignment/versions plus the successor
    requirement and the relationship type/mapping linking it back to the
    (now-deleted) parent."""
    standard, version1, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name=project_name)
    assignment1 = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version1["id"])

    pcrs = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements", headers=auth_headers(admin_token)
    ).json()
    parent_pcr_id = next(p["id"] for p in pcrs if p["requirement_id"] == parent["id"])

    client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements/{parent_pcr_id}/assessment",
        json={"compliance_status": "compliant", "justification": "", "notes": "IPX6 certificate on file."},
        headers=auth_headers(admin_token),
    )
    client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements/{parent_pcr_id}/submit-for-approval",
        headers=auth_headers(admin_token),
    )
    approved = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment1['id']}/requirements/{parent_pcr_id}/approve",
        json={"decision_note": "Signed off against IPX6."}, headers=auth_headers(admin_token),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_state"] == "approved"

    version2 = _create_version(
        client, admin_token, org_id, standard["id"], version_label="2.0-replacement", clone_from_version_id=version1["id"]
    )
    clones = _requirements_by_reference(client, admin_token, org_id, standard["id"], version2["id"])
    client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version2['id']}/requirements/{clones['4']['id']}",
        headers=auth_headers(admin_token),
    )
    successor = _create_requirement(
        client, admin_token, org_id, standard["id"], version2["id"],
        name="Equipment shall meet IP67 water ingress requirements", reference="4-ip67",
    )
    relationship_type = _create_relationship_type(
        client, admin_token, org_id, name="Equivalent", implies_equivalence=implies_equivalence,
    )
    mapping = _create_mapping(
        client, admin_token, org_id, from_id=successor["id"], to_id=parent["id"], relationship_type_id=relationship_type["id"],
    )
    _publish_version(client, admin_token, org_id, standard["id"], version2["id"])

    return {
        "project": project, "assignment1": assignment1, "standard": standard,
        "version1": version1, "version2": version2, "parent": parent, "parent_pcr_id": parent_pcr_id,
        "successor": successor, "relationship_type": relationship_type, "mapping": mapping,
        "child_clone": clones["4.1"],
    }


def _requirement_impact(result_body, requirement_id):
    return next(i for i in result_body["requirement_impacts"] if i["requirement_id"] == requirement_id)


def test_migrate_replaced_defaults_when_not_confirmed(client, admin_token, org_id):
    """Baseline (unchanged from before this addendum): doing nothing about
    a `replaced` pair leaves it at materialised defaults, exactly like
    `added` — the officer must explicitly opt in for anything else."""
    ctx = _setup_migration_scenario_with_replacement(client, admin_token, org_id, implies_equivalence=True)
    result = _migrate(client, admin_token, ctx["project"]["id"], ctx["assignment1"]["id"], ctx["version2"]["id"])
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["replaced_count"] == 1

    impact = _requirement_impact(body, ctx["successor"]["id"])
    assert impact["change"] == "replaced"
    assert impact["carried_forward"] is False
    assert impact["requires_reassessment"] is True

    new_pcrs = client.get(
        f"{_project_base(ctx['project']['id'])}/project-compliance/{body['new_project_compliance']['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    new_pcr = next(p for p in new_pcrs if p["requirement_id"] == ctx["successor"]["id"])
    assert new_pcr["compliance_status"] == "not_started"
    assert new_pcr["approval_state"] == "not_assessed"
    assert new_pcr["notes"] == ""


def test_migrate_confirmed_replacement_carries_forward_when_type_allows(client, admin_token, org_id):
    ctx = _setup_migration_scenario_with_replacement(client, admin_token, org_id, implies_equivalence=True)
    result = _migrate(
        client, admin_token, ctx["project"]["id"], ctx["assignment1"]["id"], ctx["version2"]["id"],
        confirmed_replacement_requirement_ids=[ctx["successor"]["id"]],
    )
    assert result.status_code == 201, result.text
    body = result.json()

    impact = _requirement_impact(body, ctx["successor"]["id"])
    assert impact["change"] == "replaced"
    assert impact["carried_forward"] is True
    # Always True for a confirmed `replaced` carry-forward, even though the
    # copied approval_state *was* downgraded here — see `service.py::
    # migrate_project_compliance`'s own docstring for why this differs from
    # `unchanged`, where it's conditional.
    assert impact["requires_reassessment"] is True

    new_pcrs = client.get(
        f"{_project_base(ctx['project']['id'])}/project-compliance/{body['new_project_compliance']['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    new_pcr = next(p for p in new_pcrs if p["requirement_id"] == ctx["successor"]["id"])
    # Carried forward: same content as the old, approved parent assessment...
    assert new_pcr["compliance_status"] == "compliant"
    assert new_pcr["notes"] == "IPX6 certificate on file."
    assert new_pcr["assessed_by"] is not None
    # ...but the approval itself is never silently carried over as Approved.
    assert new_pcr["approval_state"] == "requires_reassessment"
    assert new_pcr["approval_decided_at"] is None
    assert new_pcr["decision_note"] == ""

    # The old assignment's own approved assessment is completely untouched.
    old_pcrs = client.get(
        f"{_project_base(ctx['project']['id'])}/project-compliance/{ctx['assignment1']['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    old_pcr = next(p for p in old_pcrs if p["id"] == ctx["parent_pcr_id"])
    assert old_pcr["approval_state"] == "approved"
    assert old_pcr["compliance_status"] == "compliant"


def test_migrate_confirmed_replacement_rejected_when_type_not_equivalence(client, admin_token, org_id):
    ctx = _setup_migration_scenario_with_replacement(client, admin_token, org_id, implies_equivalence=False)
    result = _migrate(
        client, admin_token, ctx["project"]["id"], ctx["assignment1"]["id"], ctx["version2"]["id"],
        confirmed_replacement_requirement_ids=[ctx["successor"]["id"]],
    )
    assert result.status_code == 400, result.text
    assert "implies_equivalence" in result.text


def test_migrate_confirmed_replacement_rejected_when_id_not_in_replaced_set(client, admin_token, org_id):
    """A stale or fabricated confirmation is rejected outright (400), never
    silently ignored — this module's usual "never silent" convention."""
    ctx = _setup_migration_scenario(client, admin_token, org_id)
    result = _migrate(
        client, admin_token, ctx["project"]["id"], ctx["assignment1"]["id"], ctx["version2"]["id"],
        # `new_requirement` is genuinely "added" in this scenario, not
        # "replaced" — never part of any replaced set to confirm.
        confirmed_replacement_requirement_ids=[ctx["new_requirement"]["id"]],
    )
    assert result.status_code == 400, result.text
