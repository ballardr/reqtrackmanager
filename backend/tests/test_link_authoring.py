"""Tests for generic link authoring and link rules (docs/plans/platform-enhancements-
2026-10-plan.md Phase 5b): link-type artefact restrictions, artefact-type link rules,
module link-type seeds, the generic `link-types` / `links` endpoints, and deleting a
link type that is in use.

Each test builds its own organisation (`tests.link_world.World`), so none depends on
state left by another test or run.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.change_request import ChangeRequestVersion
from app.models.enums import ArtefactType
from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.decisions.models import Decision
from app.modules.decisions.service import create_supersession
from app.modules.registry import get_all_link_type_seeds, get_all_registered_artefact_types
from app.services import relationships
from app.services.link_types import LinkRuleError, ensure_org_link_type, validate_link_allowed
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import ACTION, REQ, World

DEC = "decision"
PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Authoring Org", decisions=True, context_strategy=True)


def _types_url(world: World) -> str:
    return f"/api/v1/orgs/{world.org['id']}/link-types"


def _create_type(world: World, forward: str, reverse: str | None = None, **extra) -> dict:
    resp = world.client.post(
        _types_url(world),
        json={"forward_name": f"{forward} {uuid.uuid4().hex[:4]}", "reverse_name": reverse or forward, **extra},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_rule(world: World, artefact_type: str, link_type_ids: list[str]):
    return world.client.put(
        f"/api/v1/orgs/{world.org['id']}/artefact-link-rules/{artefact_type}",
        json={"link_type_ids": link_type_ids}, headers=auth_headers(world.token),
    )


def _options(world: World, project: dict, artefact: tuple[str, uuid.UUID], **params) -> list[dict]:
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/link-types", params=params,
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _audit(entity_type: str, entity_id=None, action: str | None = None) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        query = select(AuditEvent).where(AuditEvent.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(AuditEvent.entity_id == str(entity_id))
        if action is not None:
            query = query.where(AuditEvent.action == action)
        return list(db.scalars(query).all())
    finally:
        db.close()


def _scene(world: World):
    """A project with a requirement, a pain point and a decision."""
    project = world.project()
    return project, (REQ, world.requirement(project)), (PAIN, world.pain_point(project)), (DEC, world.decision(project))


# --- seeds ----------------------------------------------------------------------------------


def test_seed_registry_merges_shared_names_and_flags_supersedes():
    seeds = get_all_link_type_seeds()
    assert set(seeds["Supports"].allowed_source_types) == {DEC, "guiding_principle"}
    assert seeds["Supports"].allowed_target_types == ("strategy",)
    assert seeds["Supersedes"].dedicated_endpoint is True
    assert {DEC, "strategy"} <= set(seeds["Supersedes"].allowed_source_types)
    # A core default stays unrestricted and keeps its flow.
    assert seeds["Implements"].allowed_source_types is None
    assert seeds["Implements"].flow.value == "forward_is_upstream"
    # The Decision seeds of the plan carry their restrictions.
    assert seeds["Addresses"].allowed_source_types == (DEC,) and seeds["Addresses"].allowed_target_types == (PAIN,)


def test_ensure_org_link_type_creates_from_seed_and_never_overwrites_an_edit(world):
    db = SessionLocal()
    try:
        created = ensure_org_link_type(db, uuid.UUID(world.org["id"]), "Addresses")
        assert (created.reverse_name, created.allowed_source_types, created.allowed_target_types) == (
            "Is addressed by", [DEC], [PAIN]
        )
        created.reverse_name = "Edited reverse"
        created.allowed_target_types = None
        db.commit()
        again = ensure_org_link_type(db, uuid.UUID(world.org["id"]), "Addresses")
        assert again.id == created.id
        assert again.reverse_name == "Edited reverse" and again.allowed_target_types is None
        # A name no seed knows is created from the caller's phrases, unrestricted.
        custom = ensure_org_link_type(db, uuid.UUID(world.org["id"]), "Brand new", "Brand new reverse")
        assert (custom.reverse_name, custom.allowed_source_types, custom.dedicated_endpoint) == ("Brand new reverse", None, False)
        db.commit()
    finally:
        db.close()


def test_org_list_creates_seeds_only_for_enabled_modules(client, admin_token):
    plain = World(client, admin_token, "No Modules Org")
    names = set(plain.link_types_by_name())
    assert "Addresses" not in names and "Drives" not in names and "Related to" in names

    both = World(client, admin_token, "Modules Org", decisions=True, context_strategy=True)
    seeded = both.link_types_by_name()
    assert seeded["Addresses"]["allowed_target_types"] == [PAIN]
    assert seeded["Supersedes"]["dedicated_endpoint"] is True
    # An admin's edit survives later lists.
    client.patch(
        f"{_types_url(both)}/{seeded['Addresses']['id']}",
        json={"forward_name": "Addresses", "reverse_name": "Renamed", "allowed_target_types": None},
        headers=auth_headers(both.token),
    )
    assert both.link_types_by_name()["Addresses"]["reverse_name"] == "Renamed"
    assert both.link_types_by_name()["Addresses"]["allowed_target_types"] is None


# --- link-type restrictions (admin API) -------------------------------------------------------


def test_link_type_restrictions_can_be_set_cleared_and_kept(world):
    created = _create_type(world, "Narrow", allowed_source_types=[DEC, DEC], allowed_target_types=[PAIN])
    assert created["allowed_source_types"] == [DEC]  # de-duplicated
    url = f"{_types_url(world)}/{created['id']}"

    kept = world.client.patch(
        url, json={"forward_name": created["forward_name"], "reverse_name": "x"}, headers=auth_headers(world.token)
    )
    assert kept.status_code == 200 and kept.json()["allowed_target_types"] == [PAIN]

    cleared = world.client.patch(
        url, json={"forward_name": created["forward_name"], "reverse_name": "x", "allowed_source_types": []},
        headers=auth_headers(world.token),
    )
    assert cleared.json()["allowed_source_types"] is None and cleared.json()["allowed_target_types"] == [PAIN]


def test_link_type_restriction_rejects_unknown_artefact_type(world):
    resp = world.client.post(
        _types_url(world),
        json={"forward_name": "Bad", "reverse_name": "Bad", "allowed_source_types": ["not_a_type"]},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 422 and "not_a_type" in resp.json()["detail"]
    existing = _create_type(world, "Fine")
    resp = world.client.patch(
        f"{_types_url(world)}/{existing['id']}",
        json={"forward_name": existing["forward_name"], "reverse_name": "x", "allowed_target_types": ["nope"]},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 422


def test_stored_restriction_naming_an_uninstalled_type_is_tolerated_on_read(world):
    stale = _create_type(world, "Stale")
    db = SessionLocal()
    try:
        row = db.get(RequirementLinkTypeDefinition, uuid.UUID(stale["id"]))
        row.allowed_source_types = ["module_that_was_uninstalled"]
        db.commit()
        db.refresh(row)
        with pytest.raises(LinkRuleError):  # matches nothing, never crashes
            validate_link_allowed(db, link_type=row, source_type=REQ, target_type=REQ)
    finally:
        db.close()
    listed = world.client.get(_types_url(world), headers=auth_headers(world.token))
    assert listed.status_code == 200


def test_artefact_types_endpoint_lists_core_and_enabled_module_types_with_labels(client, admin_token, world):
    resp = client.get(f"/api/v1/orgs/{world.org['id']}/artefact-types", headers=auth_headers(world.token))
    by_type = {row["type"]: row["label"] for row in resp.json()}
    assert by_type[REQ] == "Requirement" and by_type[DEC] == "Decision" and by_type[PAIN] == "Pain point"
    plain = World(client, admin_token, "Plain Types Org")
    plain_types = {row["type"] for row in client.get(
        f"/api/v1/orgs/{plain.org['id']}/artefact-types", headers=auth_headers(plain.token)).json()}
    assert DEC not in plain_types and REQ in plain_types


# --- artefact-type rules (admin API) ----------------------------------------------------------


def test_artefact_rule_lifecycle_and_validation(world, client, admin_token):
    types = world.link_types_by_name()
    related, derives = types["Related to"]["id"], types["Derives from"]["id"]

    listed = client.get(f"/api/v1/orgs/{world.org['id']}/artefact-link-rules", headers=auth_headers(world.token)).json()
    assert {row["artefact_type"]: row["link_type_ids"] for row in listed}[REQ] is None

    assert _set_rule(world, REQ, [related, derives]).status_code == 200
    replaced = _set_rule(world, REQ, [derives])
    assert replaced.json()["link_type_ids"] == [derives]
    listed = client.get(f"/api/v1/orgs/{world.org['id']}/artefact-link-rules", headers=auth_headers(world.token)).json()
    assert {row["artefact_type"]: row["link_type_ids"] for row in listed}[REQ] == [derives]

    assert _set_rule(world, REQ, []).status_code == 422  # a rule is never empty
    assert _set_rule(world, "not_a_type", [derives]).status_code == 422
    other = World(client, admin_token, "Other Rules Org")
    foreign = other.link_types_by_name()["Related to"]["id"]
    assert _set_rule(world, REQ, [foreign]).status_code == 422  # another organisation's type

    cleared = client.delete(
        f"/api/v1/orgs/{world.org['id']}/artefact-link-rules/{REQ}", headers=auth_headers(world.token)
    )
    assert cleared.status_code == 204
    listed = client.get(f"/api/v1/orgs/{world.org['id']}/artefact-link-rules", headers=auth_headers(world.token)).json()
    assert {row["artefact_type"]: row["link_type_ids"] for row in listed}[REQ] is None
    assert [e.action for e in _audit("artefact_type_link_rule")] .count("updated") == 2


def test_artefact_rules_are_org_admin_only_and_org_scoped(world, client):
    member_id = create_org_user(client, world.token, world.org["id"], f"m-{uuid.uuid4().hex[:6]}@example.com")
    assert member_id
    email = client.get(f"/api/v1/orgs/{world.org['id']}/users", headers=auth_headers(world.token)).json()
    member_email = next(u["email"] for u in email if u["user_id"] == member_id)
    member = login(client, member_email, "Password123!")
    url = f"/api/v1/orgs/{world.org['id']}/artefact-link-rules"
    assert client.get(url, headers=auth_headers(member)).status_code == 403
    related = world.link_types_by_name()["Related to"]["id"]
    assert client.put(f"{url}/{REQ}", json={"link_type_ids": [related]}, headers=auth_headers(member)).status_code == 403
    assert client.delete(f"{url}/{REQ}", headers=auth_headers(member)).status_code == 403


# --- generic authoring: success paths ---------------------------------------------------------


def test_link_a_pain_point_to_a_decision_and_on_to_a_requirement_from_every_page(world, client):
    project, req, pain, dec = _scene(world)
    types = world.link_types_by_name()  # also seeds Addresses
    addresses, implements = types["Addresses"]["id"], types["Implements"]["id"]

    # Decision --Addresses--> Pain Point, authored from the Pain Point's page (incoming).
    created = world.generic_link(project, pain, addresses, dec, direction="incoming")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["phrase"] == "Is addressed by" and body["direction"] == "incoming"
    assert body["other"]["type"] == DEC and body["other"]["type_label"] == "Decision"

    # Decision --Implements--> Requirement, authored from the Requirement's page (incoming).
    assert world.generic_link(project, req, implements, dec, direction="incoming").status_code == 201

    db = SessionLocal()
    try:
        rows = {(r.source_type, r.target_type): r for r in db.scalars(select(ArtefactLink)).all()
                if r.source_id == dec[1]}
        assert rows[(DEC, PAIN)].target_id == pain[1] and rows[(DEC, REQ)].target_id == req[1]
    finally:
        db.close()

    # The chain is visible as a graph from the pain point.
    graph = client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{PAIN}/{pain[1]}/link-graph", params={"depth": 2},
        headers=auth_headers(world.token),
    ).json()
    assert {n["id"] for n in graph["nodes"]} == {str(pain[1]), str(dec[1]), str(req[1])}


def test_two_artefact_types_nobody_hard_coded_can_be_linked_with_related_to(world):
    project, req, pain, dec = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    action = (ACTION, world.action(project))
    for page, other in ((action, pain), (dec, action), (pain, req)):
        resp = world.generic_link(project, page, related, other)
        assert resp.status_code == 201, (page[0], other[0], resp.text)


def test_generic_create_and_delete_are_audited(world):
    project, req, _pain, dec = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    link_id = world.generic_link(project, req, related, dec).json()["id"]
    created = _audit("artefact_link", link_id, "created")
    assert len(created) == 1 and created[0].detail["via"] == "generic" and created[0].project_id is not None

    resp = world.client.delete(
        f"/api/v1/projects/{project['id']}/artefacts/{DEC}/{dec[1]}/links/{link_id}", headers=auth_headers(world.token)
    )
    assert resp.status_code == 204
    assert len(_audit("artefact_link", link_id, "deleted")) == 1
    db = SessionLocal()
    try:
        assert db.get(ArtefactLink, uuid.UUID(link_id)) is None
    finally:
        db.close()


# --- generic authoring: rules ----------------------------------------------------------------


def test_link_type_restriction_is_enforced_by_the_generic_endpoint(world):
    project, req, pain, dec = _scene(world)
    narrow = _create_type(world, "Dec to pain", allowed_source_types=[DEC], allowed_target_types=[PAIN])["id"]
    assert world.generic_link(project, dec, narrow, pain).status_code == 201
    wrong_source = world.generic_link(project, req, narrow, pain)
    assert wrong_source.status_code == 400 and "cannot start from a requirement" in wrong_source.json()["detail"]
    wrong_target = world.generic_link(project, dec, narrow, req)
    assert wrong_target.status_code == 400 and "cannot point at a requirement" in wrong_target.json()["detail"]


@pytest.mark.parametrize("vetoing_side", ["source", "target"])
def test_either_ends_artefact_rule_can_veto_independently(world, vetoing_side):
    project, req, _pain, dec = _scene(world)
    types = world.link_types_by_name()
    related, derives = types["Related to"]["id"], types["Derives from"]["id"]
    vetoer = req if vetoing_side == "source" else dec
    other = dec if vetoing_side == "source" else req
    assert _set_rule(world, vetoer[0], [derives]).status_code == 200

    rejected = world.generic_link(project, req, related, dec)
    assert rejected.status_code == 400
    assert "limited to specific link types" in rejected.json()["detail"]
    # The other end's own rule is unaffected: a type both permit still works.
    assert world.generic_link(project, req, derives, dec).status_code == 201
    assert other  # silence unused warning for clarity


def test_the_three_rules_must_all_pass_and_options_reflect_them(world):
    project, req, pain, dec = _scene(world)
    types = world.link_types_by_name()
    related, addresses = types["Related to"]["id"], types["Addresses"]["id"]
    # Pain point may only use Related to; so Addresses (dec -> pain) is vetoed by the pain point's rule.
    assert _set_rule(world, PAIN, [related]).status_code == 200
    assert world.generic_link(project, dec, addresses, pain).status_code == 400
    phrases = {o["link_type_id"] for o in _options(world, project, pain)}
    assert phrases == {related}
    assert addresses not in {o["link_type_id"] for o in _options(world, project, dec, other_type=PAIN)}


def test_legacy_requirement_endpoint_goes_through_the_same_check(world, client):
    project = world.project()
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    narrow = _create_type(world, "Dec only", allowed_source_types=[DEC])["id"]
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a}/links",
        json={"target_requirement_id": str(b), "link_type_id": narrow}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 400 and "cannot start from a requirement" in resp.json()["detail"]


def test_supersession_is_exempt_from_rules_and_never_offered_generically(world):
    project, _req, _pain, dec_a = _scene(world)
    dec_b = (DEC, world.decision(project, "DEC-2"))
    types = world.link_types_by_name()
    supersedes = types["Supersedes"]["id"]
    # A rule that excludes Supersedes does not stop the dedicated supersession action.
    assert _set_rule(world, DEC, [types["Related to"]["id"]]).status_code == 200
    db = SessionLocal()
    try:
        new, old = db.get(Decision, dec_b[1]), db.get(Decision, dec_a[1])
        link = create_supersession(db, new_decision=new, old_decision=old, actor_id=world.user_id)
        db.commit()
        assert link.link_type_id == uuid.UUID(supersedes)
    finally:
        db.close()
    # ... and it is neither offered nor creatable (nor deletable) through the generic endpoints.
    assert supersedes not in {o["link_type_id"] for o in _options(world, project, dec_a)}
    refused = world.generic_link(project, dec_a, supersedes, dec_b)
    assert refused.status_code == 400 and "own action" in refused.json()["detail"]
    db = SessionLocal()
    try:
        stored = db.scalar(select(ArtefactLink).where(ArtefactLink.link_type_id == uuid.UUID(supersedes)))
    finally:
        db.close()
    gone = world.client.delete(
        f"/api/v1/projects/{project['id']}/artefacts/{DEC}/{dec_b[1]}/links/{stored.id}", headers=auth_headers(world.token)
    )
    assert gone.status_code == 400


# --- generic authoring: options ---------------------------------------------------------------


def test_options_phrase_orientation_and_reachable_types(world):
    project, req, pain, dec = _scene(world)
    world.link_types_by_name()
    from_dec = {o["forward_name"]: o for o in _options(world, project, dec)}
    assert from_dec["Addresses"]["direction"] == "outgoing" and from_dec["Addresses"]["phrase"] == "Addresses"
    assert [t["type"] for t in from_dec["Addresses"]["other_types"]] == [PAIN]
    assert [t["label"] for t in from_dec["Addresses"]["other_types"]] == ["Pain point"]

    from_pain = {o["forward_name"]: o for o in _options(world, project, pain)}
    assert from_pain["Addresses"]["direction"] == "incoming" and from_pain["Addresses"]["phrase"] == "Is addressed by"
    assert [t["type"] for t in from_pain["Addresses"]["other_types"]] == [DEC]
    # A pain point cannot start an "Addresses" link, so no outgoing option exists for it.
    assert all(o["direction"] == "incoming" for o in _options(world, project, pain) if o["forward_name"] == "Addresses")

    narrowed = _options(world, project, dec, other_type=REQ)
    assert "Addresses" not in {o["forward_name"] for o in narrowed}
    assert "Implements" in {o["forward_name"] for o in narrowed}


def test_symmetric_unrestricted_type_is_offered_once(world):
    project, req, *_ = _scene(world)
    related = [o for o in _options(world, project, req) if o["forward_name"] == "Related to"]
    assert len(related) == 1 and related[0]["direction"] == "outgoing"


def test_options_exclude_modules_disabled_for_the_project(client, admin_token):
    plain = World(client, admin_token, "Options Plain Org")
    project = plain.project()
    req = (REQ, plain.requirement(project))
    reach = {t["type"] for o in _options(plain, project, req) if o["forward_name"] == "Related to" for t in o["other_types"]}
    assert {REQ, ACTION} <= reach and not ({DEC, PAIN} & reach)  # opt-in modules stay out


# --- generic authoring: authorisation and validation ------------------------------------------


def test_member_without_manage_cannot_link_but_can_see_options(world, client):
    project, req, _pain, dec = _scene(world)
    email = f"viewer-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(client, world.token, world.org["id"], email)
    client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
                headers=auth_headers(world.token))
    member = login(client, email, "Password123!")
    related = world.link_types_by_name()["Related to"]["id"]
    resp = world.generic_link(project, req, related, dec, token=member)
    assert resp.status_code == 403
    assert client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{REQ}/{req[1]}/link-types", headers=auth_headers(member)
    ).status_code == 200


def test_non_member_is_refused(world, client, admin_token):
    project, req, _pain, dec = _scene(world)
    outsider = World(client, admin_token, "Outsider Org")
    related = world.link_types_by_name()["Related to"]["id"]
    assert world.generic_link(project, req, related, dec, token=outsider.token).status_code == 403


def test_invalid_requests_are_rejected(world, client, admin_token):
    project, req, pain, dec = _scene(world)
    types = world.link_types_by_name()
    related = types["Related to"]["id"]

    assert world.generic_link(project, req, related, req).status_code == 400  # self-link
    assert world.generic_link(project, req, related, (DEC, uuid.uuid4())).status_code == 404  # no such record
    assert world.generic_link(project, req, related, ("not_a_type", dec[1])).status_code == 404
    assert world.generic_link(project, (REQ, uuid.uuid4()), related, dec).status_code == 404
    assert world.generic_link(project, req, uuid.uuid4(), dec).status_code == 400  # unknown link type

    other_org = World(client, admin_token, "Foreign Types Org")
    foreign_type = other_org.link_types_by_name()["Related to"]["id"]
    assert world.generic_link(project, req, foreign_type, dec).status_code == 400

    other_project = world.project("Other")
    stranger = (REQ, world.requirement(other_project, "Elsewhere"))
    assert world.generic_link(project, req, related, stranger).status_code == 404  # another project's record


def test_duplicates_and_symmetric_mirrors_conflict(world):
    project, req, _pain, dec = _scene(world)
    types = world.link_types_by_name()
    related = types["Related to"]["id"]
    assert world.generic_link(project, req, related, dec).status_code == 201
    assert world.generic_link(project, req, related, dec).status_code == 409
    assert world.generic_link(project, dec, related, req).status_code == 409  # mirror of a symmetric type
    implements = types["Implements"]["id"]  # asymmetric: the reverse orientation is a different link
    assert world.generic_link(project, req, implements, dec).status_code == 201
    assert world.generic_link(project, dec, implements, req).status_code == 201


def test_other_end_in_a_disabled_module_is_not_found(client, admin_token):
    plain = World(client, admin_token, "Disabled Module Org")
    project = plain.project()
    req = (REQ, plain.requirement(project))
    related = plain.link_types_by_name()["Related to"]["id"]
    assert plain.generic_link(project, req, related, (DEC, uuid.uuid4())).status_code == 404


def test_delete_requires_the_link_to_touch_the_page_artefact(world):
    project, req, pain, dec = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    link_id = world.generic_link(project, req, related, dec).json()["id"]
    wrong = world.client.delete(
        f"/api/v1/projects/{project['id']}/artefacts/{PAIN}/{pain[1]}/links/{link_id}", headers=auth_headers(world.token)
    )
    assert wrong.status_code == 404


def test_approved_requirement_needs_a_change_request_when_the_project_requires_it(world, client):
    project, req, _pain, dec = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    approve = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req[1]}/approve", headers=auth_headers(world.token)
    )
    assert approve.status_code == 200, approve.text
    # Ungated by default, even though the requirement is approved.
    link_id = world.generic_link(project, req, related, dec).json()["id"]
    client.patch(
        f"/api/v1/projects/{project['id']}", json={"require_change_request_for_approved_links": True},
        headers=auth_headers(world.token),
    )
    blocked_add = world.generic_link(project, dec, world.link_types_by_name()["Affects"]["id"], req)
    assert blocked_add.status_code == 409 and "change request" in blocked_add.json()["detail"]
    blocked_delete = client.delete(
        f"/api/v1/projects/{project['id']}/artefacts/{DEC}/{dec[1]}/links/{link_id}", headers=auth_headers(world.token)
    )
    assert blocked_delete.status_code == 409


# --- deleting a link type that is in use ------------------------------------------------------


def _chain(world: World):
    """Two requirements linked A --Depends on--> B, and a third C; returns ids and the type map."""
    project = world.project()
    a, b, c = (world.requirement(project, n) for n in "ABC")
    return project, a, b, c, world.link_types_by_name()


def _legacy_link(world: World, project: dict, source, target, type_id) -> str:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements/{source}/links",
        json={"target_requirement_id": str(target), "link_type_id": type_id}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _usage(world: World, type_id: str) -> dict:
    resp = world.client.get(f"{_types_url(world)}/{type_id}/usage", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _delete_type(world: World, type_id: str, **params):
    return world.client.delete(f"{_types_url(world)}/{type_id}", params=params, headers=auth_headers(world.token))


def test_usage_reports_counts_and_assesses_every_candidate(world):
    project, a, b, c, types = _chain(world)
    depends = types["Depends on"]["id"]
    _legacy_link(world, project, a, b, depends)
    _legacy_link(world, project, b, c, depends)
    narrow = _create_type(world, "Dec only", allowed_source_types=[DEC], flow="forward_is_downstream")
    usage = _usage(world, depends)
    assert (usage["link_count"], usage["project_count"], usage["pending_change_requests"]) == (2, 1, 0)
    assert usage["is_dedicated"] is False and usage["is_last"] is False
    by_id = {cand["id"]: cand for cand in usage["candidates"]}
    assert by_id[types["Related to"]["id"]]["compatible"] is True
    assert by_id[types["Related to"]["id"]]["flow_differs"] is True  # Depends on is upstream, Related to is none
    blocked = by_id[narrow["id"]]
    assert blocked["compatible"] is False and "cannot start from a requirement" in blocked["reason"]
    assert depends not in by_id


def test_unused_link_type_deletes_outright_with_the_legacy_204(world):
    unused = _create_type(world, "Unused")
    assert _delete_type(world, unused["id"]).status_code == 204
    assert unused["id"] not in {row["id"] for row in world.client.get(_types_url(world), headers=auth_headers(world.token)).json()}


def test_in_use_without_a_choice_is_still_a_409_with_the_count(world):
    project, a, b, _c, types = _chain(world)
    _legacy_link(world, project, a, b, types["Depends on"]["id"])
    resp = _delete_type(world, types["Depends on"]["id"])
    assert resp.status_code == 409 and "1 link" in resp.json()["detail"]


def test_move_converts_merges_duplicates_and_reports_counts(world):
    project, a, b, c, types = _chain(world)
    depends, related = types["Depends on"]["id"], types["Related to"]["id"]
    keep = _legacy_link(world, project, a, b, depends)
    dup = _legacy_link(world, project, a, c, depends)
    _legacy_link(world, project, a, c, related)  # the move would duplicate A -> C
    resp = _delete_type(world, depends, mode="reassign", reassign_to_id=related)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"moved": 1, "merged": 1, "removed": 0, "copies_created": 0, "copies_renamed": []}
    db = SessionLocal()
    try:
        assert db.get(ArtefactLink, uuid.UUID(keep)).link_type_id == uuid.UUID(related)
        assert db.get(ArtefactLink, uuid.UUID(dup)) is None
        assert db.get(RequirementLinkTypeDefinition, uuid.UUID(depends)) is None
    finally:
        db.close()
    assert len(_audit("artefact_link", keep, "link_type_changed")) == 1
    merged = _audit("artefact_link", dup, "deleted")
    assert len(merged) == 1 and merged[0].detail["reason"] == "merged_into_existing"
    assert len(_audit("requirement_link_type_definition", depends, "deleted")) == 1


def test_move_to_an_incompatible_candidate_is_refused_with_the_reason(world):
    project, a, b, _c, types = _chain(world)
    depends = types["Depends on"]["id"]
    _legacy_link(world, project, a, b, depends)
    narrow = _create_type(world, "Dec only", allowed_source_types=[DEC])["id"]
    resp = _delete_type(world, depends, mode="reassign", reassign_to_id=narrow)
    assert resp.status_code == 409 and "cannot start from a requirement" in resp.json()["detail"]
    assert _delete_type(world, depends, mode="reassign").status_code == 400
    assert _delete_type(world, depends, mode="reassign", reassign_to_id=depends).status_code == 400
    assert _usage(world, depends)["link_count"] == 1  # nothing changed


def test_remove_links_mode_deletes_links_with_one_audit_event_each(world):
    project, a, b, c, types = _chain(world)
    depends = types["Depends on"]["id"]
    first, second = _legacy_link(world, project, a, b, depends), _legacy_link(world, project, b, c, depends)
    resp = _delete_type(world, depends, mode="remove_links")
    assert resp.status_code == 200 and resp.json() == {"moved": 0, "merged": 0, "removed": 2, "copies_created": 0, "copies_renamed": []}
    db = SessionLocal()
    try:
        assert db.get(ArtefactLink, uuid.UUID(first)) is None and db.get(ArtefactLink, uuid.UUID(second)) is None
    finally:
        db.close()
    for link_id in (first, second):
        events = _audit("artefact_link", link_id, "deleted")
        assert len(events) == 1 and events[0].detail["reason"] == "link_type_deleted"


def test_last_link_type_cannot_be_deleted_in_any_mode(world, client):
    rows = list(world.link_types_by_name().values())
    for row in rows[1:]:
        assert _delete_type(world, row["id"]).status_code == 204
    assert _delete_type(world, rows[0]["id"], mode="remove_links").status_code == 409


def test_pending_change_request_blocks_removal_and_is_repointed_by_a_move(world, client):
    project, a, b, _c, types = _chain(world)
    client.post(f"/api/v1/projects/{project['id']}/requirements/{a}/approve", headers=auth_headers(world.token))
    client.patch(
        f"/api/v1/projects/{project['id']}", json={"require_change_request_for_approved_links": True},
        headers=auth_headers(world.token),
    )
    proposed = types["Equivalent to"]["id"]
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_link", "requirement_id": str(a), "proposed_link_target_requirement_id": str(b),
            "proposed_link_type_id": proposed, "reason": "gap",
        },
        headers=auth_headers(world.token),
    )
    assert cr.status_code == 201, cr.text
    assert _usage(world, proposed)["pending_change_requests"] == 1
    blocked = _delete_type(world, proposed, mode="remove_links")
    assert blocked.status_code == 409 and "pending change request" in blocked.json()["detail"]

    target = types["Mitigates"]["id"]
    assert _delete_type(world, proposed, mode="reassign", reassign_to_id=target).status_code == 200
    db = SessionLocal()
    try:
        version = db.scalar(select(ChangeRequestVersion).where(ChangeRequestVersion.change_request_id == uuid.UUID(cr.json()["id"])))
        assert version.proposed_link_type_id == uuid.UUID(target)
    finally:
        db.close()


def test_artefact_rules_follow_a_move_and_block_emptying_on_removal(world):
    project, a, b, _c, types = _chain(world)
    depends, related = types["Depends on"]["id"], types["Related to"]["id"]
    _legacy_link(world, project, a, b, depends)
    assert _set_rule(world, REQ, [depends]).status_code == 200
    usage = _usage(world, depends)
    assert [t["type"] for t in usage["rule_artefact_types"]] == [REQ]
    assert [t["type"] for t in usage["emptied_rule_artefact_types"]] == [REQ]

    emptied = _delete_type(world, depends, mode="remove_links")
    assert emptied.status_code == 409 and "Requirement" in emptied.json()["detail"]
    assert _usage(world, depends)["link_count"] == 1  # nothing deleted

    assert _delete_type(world, depends, mode="reassign", reassign_to_id=related).status_code == 200
    rules = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/artefact-link-rules", headers=auth_headers(world.token)
    ).json()
    assert {r["artefact_type"]: r["link_type_ids"] for r in rules}[REQ] == [related]


def test_unused_type_is_removed_from_rules_and_a_sole_entry_blocks_the_delete(world):
    types = world.link_types_by_name()
    unused = _create_type(world, "Unused in rule")
    related = types["Related to"]["id"]
    assert _set_rule(world, DEC, [unused["id"], related]).status_code == 200
    assert _delete_type(world, unused["id"]).status_code == 204
    rules = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/artefact-link-rules", headers=auth_headers(world.token)
    ).json()
    assert {r["artefact_type"]: r["link_type_ids"] for r in rules}[DEC] == [related]

    sole = _create_type(world, "Sole entry")
    assert _set_rule(world, DEC, [sole["id"]]).status_code == 200
    assert _delete_type(world, sole["id"]).status_code == 409


def test_deleting_is_org_admin_only_and_scoped_to_the_org(world, client, admin_token):
    other = World(client, admin_token, "Other Delete Org")
    foreign = other.link_types_by_name()["Related to"]["id"]
    assert _delete_type(world, foreign).status_code == 404
    assert client.get(f"{_types_url(world)}/{foreign}/usage", headers=auth_headers(world.token)).status_code == 404


# --- coverage guard ---------------------------------------------------------------------------


def test_every_pair_of_registered_artefact_types_is_linkable_by_an_unrestricted_type(world):
    related = world.link_types_by_name()["Related to"]["id"]
    db = SessionLocal()
    try:
        link_type = db.get(RequirementLinkTypeDefinition, uuid.UUID(related))
        types = sorted(get_all_registered_artefact_types())
        assert {REQ, ACTION, DEC, PAIN} <= set(types)
        for source in types:
            for target in types:
                validate_link_allowed(db, link_type=link_type, source_type=source, target_type=target)
    finally:
        db.close()


def test_a_restricted_type_accepts_only_matching_pairs(world):
    narrow = _create_type(world, "Narrow", allowed_source_types=[DEC, REQ], allowed_target_types=[PAIN])
    db = SessionLocal()
    try:
        link_type = db.get(RequirementLinkTypeDefinition, uuid.UUID(narrow["id"]))
        for source in (DEC, REQ):
            validate_link_allowed(db, link_type=link_type, source_type=source, target_type=PAIN)
        for source, target in ((PAIN, PAIN), (DEC, REQ), (ACTION, PAIN)):
            with pytest.raises(LinkRuleError):
                validate_link_allowed(db, link_type=link_type, source_type=source, target_type=target)
    finally:
        db.close()


def test_a_newly_registered_artefact_type_is_linkable_with_no_other_edit(world, monkeypatch):
    from app.modules import registry

    monkeypatch.setattr(
        registry, "get_all_registered_artefact_types",
        lambda: {*get_all_registered_artefact_types(), "future_module_type"},
    )
    related = world.link_types_by_name()["Related to"]["id"]
    db = SessionLocal()
    try:
        link = relationships.create_link(
            db, source_type="future_module_type", source_id=uuid.uuid4(), target_type=ArtefactType.REQUIREMENT.value,
            target_id=uuid.uuid4(), link_type_id=uuid.UUID(related), created_by=world.user_id,
        )
        assert link.id is not None
        db.rollback()
    finally:
        db.close()
