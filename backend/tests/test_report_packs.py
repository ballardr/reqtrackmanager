"""Tests for report packs: the definition rules (`services.report_pack_definition`), storing and versioning
(`services.report_packs`), the organisation and project tiers with additive visibility, hide and restore
(`services.report_pack_scope`), and running a pack into a zip with a manifest (`services.report_pack_run`):
variables flowing to entries by name, entries that cannot run being listed, provenance rows, the counts preview and
the permission checks. Each test builds its own organisation.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.generated_report import GeneratedReport
from app.models.report_pack import ReportPackVersion
from app.services import report_layout_eval, report_run_jobs
from app.services.report_layout_tree import empty_tree
from app.services.report_pack_definition import (
    MAX_ENTRIES,
    PACK_SCHEMA_VERSION,
    clean_filename,
    definition_hash,
    validate_definition,
)
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login
from tests.link_world import REQ, World

CATEGORIES = {
    "name": "categories", "type": "enum", "multiple": True, "label": "Categories",
    "source": {"record_type": REQ, "field": "category"},
}


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Packs Org", decisions=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def definition(*entries: dict[str, Any], variables: list[dict] | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"schema_version": PACK_SCHEMA_VERSION, "entries": list(entries), **extra}
    if variables is not None:
        out["variables"] = variables
    return out


def layout_entry(name: str, fmt: str = "pdf", **extra: Any) -> dict[str, Any]:
    return {"kind": "layout", "name": name, "format": fmt, **extra}


D1 = {"kind": "report", "module_key": "decisions", "report": "d1", "format": "pdf"}


def errors_of(value: Any) -> list[tuple[str, str]]:
    return [(e.path, e.message) for e in validate_definition(value)]


# ---- the definition -------------------------------------------------------------------------------------------


def test_a_pack_with_layout_and_report_entries_and_variables_is_valid():
    value = definition(
        layout_entry("Overview", "pdf", filename="overview", variables={"categories": ["A"]}, tier="organization"),
        layout_entry("Rows", "xlsx"),
        {"kind": "report", "module_key": "decisions", "report": "d1", "format": "docx", "params": {"status": "approved"}},
        variables=[CATEGORIES],
    )
    assert errors_of(value) == []


def test_an_empty_pack_is_valid_as_a_draft():
    assert errors_of(definition()) == []


@pytest.mark.parametrize(
    ("value", "path"),
    [
        ("nope", ""),
        ({"entries": []}, "schema_version"),
        ({"schema_version": 2, "entries": []}, "schema_version"),
        (definition(extra=1) | {"extra": 1}, "extra"),
        (definition({"kind": "other"}), "entries[0].kind"),
        (definition(layout_entry("X", "json")), "entries[0].format"),
        (definition(layout_entry("X", "pdf", tier="ancestor")), "entries[0].tier"),
        (definition(layout_entry("X", "pdf", variables={"Bad Name": 1})), "entries[0].variables.Bad Name"),
        (definition(layout_entry("X", "pdf", variables={"a": {"nested": 1}})), "entries[0].variables.a"),
        (definition(layout_entry("X", "pdf", filename="")), "entries[0].filename"),
        (definition({"kind": "report", "module_key": "decisions", "report": "nope", "format": "pdf"}), "entries[0].report"),
        (definition({"kind": "report", "module_key": "decisions", "report": "d1", "format": "json"}), "entries[0].format"),
        (definition({"kind": "report", "module_key": "decisions", "report": "d1", "format": "pdf", "params": {"zzz": 1}}), "entries[0].params.zzz"),
        (definition({**D1, "params": {"overdue_days": 3}}), "entries[0].params.overdue_days"),
        (definition(variables=[{"name": "x", "type": "nope"}]), "variables[0].type"),
        (
            definition(variables=[{"name": "x", "type": "text", "source": {"record_type": "nothing", "field": "f"}}]),
            "variables[0].source.record_type",
        ),
    ],
)
def test_invalid_definitions_name_where_the_problem_is(value, path):
    assert path in {p for p, _ in errors_of(value)}


def test_too_many_entries_are_refused():
    assert ("entries", f"Must be a list of at most {MAX_ENTRIES} reports.") in errors_of(
        definition(*[layout_entry(f"L{i}") for i in range(MAX_ENTRIES + 1)])
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "etc-passwd"),
        ("/abs/path", "abs-path"),
        ("a\\b", "a-b"),
        ("..", "report"),
        (".hidden", "hidden"),
        ("Q3 summary.final", "Q3 summary.final"),
        ("ünï", "report"),
        ("x" * 200, "x" * 60),
    ],
)
def test_a_file_stem_can_never_be_a_path(raw, expected):
    cleaned = clean_filename(raw)
    assert cleaned == expected or (".." not in cleaned and "/" not in cleaned and "\\" not in cleaned)
    assert ".." not in cleaned and not cleaned.startswith(".")


def test_the_hash_ignores_key_order():
    a = definition(layout_entry("A"))
    b = {"entries": [{"format": "pdf", "name": "A", "kind": "layout"}], "schema_version": PACK_SCHEMA_VERSION}
    assert definition_hash(a) == definition_hash(b)


# ---- storing and versioning ---------------------------------------------------------------------------------


def org_url(world: World, suffix: str = "") -> str:
    return f"/api/v1/orgs/{world.org['id']}/report-packs{suffix}"


def project_url(project: dict, suffix: str = "") -> str:
    return f"/api/v1/projects/{project['id']}/report-packs{suffix}"


def new_pack(world: World, url: str, name: str, value: dict[str, Any] | None = None, *, token: str | None = None):
    return world.client.post(
        url, json={"name": name, "description": "d", "definition": value or definition(layout_entry("L"))},
        headers=auth_headers(token or world.token),
    )


def created(world: World, url: str, name: str, value: dict[str, Any] | None = None) -> dict:
    resp = new_pack(world, url, name, value)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_save_and_read_versions(world):
    pack = created(world, org_url(world), "Board pack")
    assert pack["current_version"] == 1 and pack["entries"] == 1 and pack["origin"] == "organization"

    changed = definition(layout_entry("L"), layout_entry("M", "docx"))
    saved = world.client.put(
        org_url(world, f"/{pack['id']}/definition"), json={"definition": changed, "base_version": 1, "comment": "add M"},
        headers=auth_headers(world.token),
    )
    assert saved.status_code == 200 and saved.json()["current_version"] == 2

    unchanged = world.client.put(
        org_url(world, f"/{pack['id']}/definition"), json={"definition": changed, "base_version": 2}, headers=auth_headers(world.token),
    )
    assert unchanged.json()["current_version"] == 2  # an identical save stores nothing

    stale = world.client.put(
        org_url(world, f"/{pack['id']}/definition"), json={"definition": definition(), "base_version": 1}, headers=auth_headers(world.token),
    )
    assert stale.status_code == 409 and stale.json()["detail"]["current_version"] == 2

    history = world.client.get(org_url(world, f"/{pack['id']}/versions"), headers=auth_headers(world.token)).json()
    assert [v["version"] for v in history] == [2, 1] and history[0]["comment"] == "add M"
    first = world.client.get(org_url(world, f"/{pack['id']}/versions/1"), headers=auth_headers(world.token)).json()
    assert len(first["definition"]["entries"]) == 1


def test_an_invalid_definition_is_refused_with_positions(world):
    resp = new_pack(world, org_url(world), "Bad", definition(layout_entry("X", "json")))
    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["path"] == "entries[0].format"


def test_names_are_unique_per_owner_ignoring_case(world):
    created(world, org_url(world), "Pack")
    assert new_pack(world, org_url(world), "pack").status_code == 409
    project = world.project("Alpha")
    assert new_pack(world, project_url(project), "pack").status_code == 201  # a different owner


def test_a_saved_version_cannot_be_updated(world, db):
    pack = created(world, org_url(world), "Frozen")
    version = db.scalar(select(ReportPackVersion).where(ReportPackVersion.pack_id == uuid.UUID(pack["id"])))
    version.comment = "changed"
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()


def test_rename_and_delete(world):
    pack = created(world, org_url(world), "Old")
    renamed = world.client.patch(org_url(world, f"/{pack['id']}"), json={"name": "New"}, headers=auth_headers(world.token))
    assert renamed.status_code == 200 and renamed.json()["name"] == "New"
    assert world.client.delete(org_url(world, f"/{pack['id']}"), headers=auth_headers(world.token)).status_code == 204
    assert world.client.get(org_url(world, f"/{pack['id']}"), headers=auth_headers(world.token)).status_code == 404


def test_only_a_manager_of_layouts_may_write_or_read_a_definition(world):
    project = world.project("Alpha")
    member_id = create_org_user(world.client, world.token, world.org["id"], "packmember@example.com")
    world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_id, "role": "member"}, headers=auth_headers(world.token),
    )
    token = login(world.client, "packmember@example.com", "Password123!")
    assert new_pack(world, project_url(project), "Mine", token=token).status_code == 403
    pack = created(world, project_url(project), "Theirs")
    assert world.client.get(project_url(project, f"/{pack['id']}"), headers=auth_headers(token)).status_code == 403
    listed = world.client.get(project_url(project), headers=auth_headers(token))
    assert listed.status_code == 200 and [p["name"] for p in listed.json()] == ["Theirs"]  # a member may see that it exists


# ---- tiers ------------------------------------------------------------------------------------------------------


def project_names(world: World, project: dict) -> dict[str, dict]:
    resp = world.client.get(project_url(project), headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return {row["name"]: row for row in resp.json()}


def test_a_project_sees_organisation_ancestor_and_own_packs_nearest_name_winning(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    created(world, org_url(world), "Org only")
    created(world, org_url(world), "Shared", definition(layout_entry("org")))
    created(world, project_url(parent), "Parent only")
    created(world, project_url(parent), "Shared", definition(layout_entry("parent")))
    created(world, project_url(child), "Own")

    seen = project_names(world, child)
    assert {n: r["origin"] for n, r in seen.items()} == {
        "Own": "project", "Parent only": "ancestor", "Shared": "ancestor", "Org only": "organization",
    }
    assert seen["Own"]["editable"] and not seen["Shared"]["editable"]


def test_hide_and_restore_an_inherited_pack(world):
    project = world.project("Alpha")
    pack = created(world, org_url(world), "Default pack")
    resp = world.client.put(project_url(project, f"/{pack['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    assert resp.status_code == 200 and resp.json()["hidden"] is True
    assert project_names(world, project)["Default pack"]["hidden"] is True

    run = world.client.post(project_url(project, f"/{pack['id']}/run"), json={}, headers=auth_headers(world.token))
    assert run.status_code == 404  # a hidden pack is not offered to runners

    restored = world.client.post(project_url(project, "/restore"), json={}, headers=auth_headers(world.token))
    assert restored.json()["restored"] == [pack["id"]]
    assert project_names(world, project)["Default pack"]["hidden"] is False


def test_a_project_cannot_hide_or_edit_its_own_or_an_inherited_pack_the_wrong_way(world):
    project = world.project("Alpha")
    own = created(world, project_url(project), "Own")
    inherited = created(world, org_url(world), "Inherited")
    hide_own = world.client.put(
        project_url(project, f"/{own['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token),
    )
    assert hide_own.status_code == 404
    edit = world.client.put(
        project_url(project, f"/{inherited['id']}/definition"), json={"definition": definition(), "base_version": 1},
        headers=auth_headers(world.token),
    )
    assert edit.status_code == 403


def test_deleting_an_organisation_pack_forgets_the_hides(world, db):
    project = world.project("Alpha")
    pack = created(world, org_url(world), "Default pack")
    world.client.put(project_url(project, f"/{pack['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    world.client.delete(org_url(world, f"/{pack['id']}"), headers=auth_headers(world.token))
    from app.models.definition_suppression import ProjectDefinitionSuppression

    left = db.scalars(select(ProjectDefinitionSuppression).where(ProjectDefinitionSuppression.org_definition_id == uuid.UUID(pack["id"]))).all()
    assert left == []


# ---- running ------------------------------------------------------------------------------------------------


def category(world: World, project: dict, name: str) -> str:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": name, "prefix": name[:4].upper(), "component_id": project["component_id"]}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def requirement(world: World, project: dict, name: str, category_id: str) -> None:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": name, "component_id": project["component_id"], "category_id": category_id}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text


def requirements_tree(family: str = "document", *variables: dict[str, Any]) -> dict[str, Any]:
    """Requirements in the chosen categories (all of them when the layout declares no variable)."""
    where = [{"field": "category", "op": "in", "value": {"var": "categories"}}] if variables else []
    source: dict[str, Any] = {"record_type": REQ, "sort": [{"field": "title"}]}
    if where:
        source["where"] = where
    if family == "document":
        nodes: list[dict[str, Any]] = [
            {"type": "heading", "text": "Requirements"},
            {"type": "each", "source": source, "children": [{"type": "text", "text": "{{record.title}} [{{record.category}}]"}]},
        ]
    else:
        nodes = [{
            "type": "sheet", "name": "Requirements", "source": source,
            "columns": [{"field": "title"}, {"field": "category"}],
        }]
    tree = {**empty_tree(family), "nodes": nodes}
    if variables:
        tree["variables"] = list(variables)
    return tree


def make_layout(world: World, name: str, tree: dict[str, Any], *, project: dict | None = None) -> dict:
    base = f"/api/v1/projects/{project['id']}" if project else f"/api/v1/orgs/{world.org['id']}"
    resp = world.client.post(
        f"{base}/report-layouts", json={"name": name, "description": "d", "family": tree["family"], "tree": tree},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def scene(world):
    """A project with requirements in Security, Usability and Billing, an organisation layout (documents, by category)
    and a table layout of the same requirements."""
    project = world.project("Alpha")
    ids = {name: category(world, project, name) for name in ("Security", "Usability", "Billing")}
    requirement(world, project, "Login must be strong", ids["Security"])
    requirement(world, project, "Audit trail", ids["Security"])
    requirement(world, project, "Large buttons", ids["Usability"])
    requirement(world, project, "Invoice numbering", ids["Billing"])
    make_layout(world, "Overview", requirements_tree("document", CATEGORIES))
    make_layout(world, "Rows", requirements_tree("table", CATEGORIES))
    return project


def run_pack(world: World, project: dict, pack: dict, body: dict[str, Any] | None = None, **kwargs: Any):
    return world.client.post(
        project_url(project, f"/{pack['id']}/run"), json=body or {}, headers=auth_headers(kwargs.get("token") or world.token),
    )


def open_zip(resp) -> zipfile.ZipFile:
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(resp.content))


def manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    return json.loads(archive.read("manifest.json"))


def test_a_module_report_entry_may_take_every_file_format_and_each_makes_its_file(world, scene):
    formats = ["pdf", "docx", "html", "odt", "csv", "xlsx", "ods"]
    pack = created(world, org_url(world), "Every format", definition(
        *[{**D1, "format": f, "filename": f"d1-{f}"} for f in formats],
    ))
    archive = open_zip(run_pack(world, scene, pack))
    assert archive.namelist() == ["manifest.json", *[f"{i + 1:02d}-d1-{f}.{f}" for i, f in enumerate(formats)]]
    assert archive.read("02-d1-docx.docx")[:2] == b"PK" and archive.read("01-d1-pdf.pdf")[:4] == b"%PDF"
    assert b"<" in archive.read("03-d1-html.html")[:200]
    assert all(e["status"] == "included" for e in manifest(archive)["entries"])


def test_a_pack_lists_the_record_types_its_entries_read(world, scene):
    mine = make_layout(world, "Mine", requirements_tree("document", CATEGORIES), project=scene)
    both = created(world, org_url(world), "Both", definition(layout_entry("Overview"), D1))
    only_report = created(world, org_url(world), "Decisions only", definition(D1))
    nothing = created(world, org_url(world), "Missing", definition(layout_entry("No such layout")))
    own = created(world, project_url(scene), "Own", definition(layout_entry(mine["name"])))

    org_list = {p["name"]: p for p in world.client.get(org_url(world), headers=auth_headers(world.token)).json()}
    assert both["record_types"] == sorted([REQ, "decision"]) == org_list["Both"]["record_types"]
    assert org_list["Decisions only"]["record_types"] == ["decision"]
    assert nothing["record_types"] == [] == org_list["Missing"]["record_types"]

    project_list = {p["name"]: p for p in world.client.get(project_url(scene), headers=auth_headers(world.token)).json()}
    assert project_list["Both"]["record_types"] == sorted([REQ, "decision"])
    assert project_list["Own"]["record_types"] == [REQ] == own["record_types"]
    assert only_report["id"] in {p["id"] for p in project_list.values()}

    # The single-pack reads and writes carry the types too, as the asking project reaches the layouts.
    detail = world.client.get(project_url(scene, f"/{both['id']}"), headers=auth_headers(world.token)).json()
    assert detail["record_types"] == sorted([REQ, "decision"])
    saved = world.client.put(
        project_url(scene, f"/{own['id']}/definition"),
        json={"definition": definition(D1), "base_version": 1}, headers=auth_headers(world.token),
    ).json()
    assert saved["record_types"] == ["decision"]

    # The organisation tier cannot reach a project's own layout, so the same name there reads nothing.
    on_org = created(world, org_url(world), "Org points at project layout", definition(layout_entry(mine["name"])))
    assert on_org["record_types"] == []


def test_a_pack_runs_into_a_zip_with_a_manifest_and_flat_numbered_files(world, scene):
    pack = created(world, org_url(world), "Handover", definition(
        layout_entry("Overview", "docx", filename="overview"), layout_entry("Rows", "xlsx", filename="../../rows"),
        {"kind": "report", "module_key": "decisions", "report": "d1", "format": "csv", "filename": "decisions"},
        variables=[CATEGORIES],
    ))
    archive = open_zip(run_pack(world, scene, pack, {"variables": {"categories": ["Security"]}}))
    assert archive.namelist() == ["manifest.json", "01-overview.docx", "02-rows.xlsx", "03-decisions.csv"], manifest(archive)["entries"]
    info = manifest(archive)
    assert info["pack"]["name"] == "Handover" and info["pack"]["version"] == 1
    assert info["scope"] == {"type": "project", "name": "Alpha"}
    assert info["variables"] == {"categories": ["Security"]}
    assert [e["status"] for e in info["entries"]] == ["included"] * 3
    assert info["entries"][0]["record_counts"][REQ] == 2  # only Security requirements
    assert info["entries"][0]["variables"] == {"categories": ["Security"]}
    assert info["not_available"] == 0


def test_the_pack_variable_reaches_an_entry_by_name_and_a_fixed_value_overrides_it(world, scene):
    pack = created(world, org_url(world), "Mixed", definition(
        layout_entry("Overview", "docx"),
        layout_entry("Rows", "xlsx", variables={"categories": ["Billing"]}),
        variables=[CATEGORIES],
    ))
    info = manifest(open_zip(run_pack(world, scene, pack, {"variables": {"categories": ["Usability", "Billing"]}})))
    assert [e["record_counts"][REQ] for e in info["entries"]] == [2, 1]
    assert info["entries"][1]["variables"] == {"categories": ["Billing"]}


def test_a_pack_variable_of_another_type_is_not_passed_and_the_layouts_default_applies(world, scene):
    make_layout(world, "Defaulted", requirements_tree("document", {**CATEGORIES, "default": ["Security"]}))
    pack = created(world, org_url(world), "Typed", definition(
        layout_entry("Defaulted", "docx"), variables=[{"name": "categories", "type": "text", "label": "Categories"}],
    ))
    info = manifest(open_zip(run_pack(world, scene, pack, {"variables": {"categories": "Billing"}})))
    assert info["entries"][0]["variables"] == {"categories": ["Security"]}


def test_an_entry_that_cannot_run_is_listed_not_dropped(world, scene):
    pack = created(world, org_url(world), "Partial", definition(
        layout_entry("Overview", "docx", variables={"categories": ["Security"]}),
        layout_entry("No such layout", "pdf"),
        layout_entry("Overview", "xlsx"),  # a document layout cannot be a spreadsheet
        layout_entry("Rows", "xlsx"),  # needs categories, and none is given or defaulted
    ))
    info = manifest(open_zip(run_pack(world, scene, pack)))
    statuses = [(e["status"], e["reason"]) for e in info["entries"]]
    assert statuses[0] == ("included", None)
    assert statuses[1][0] == "not_available" and "No report layout" in statuses[1][1]
    assert statuses[2][0] == "not_available" and "cannot be produced as xlsx" in statuses[2][1]
    assert statuses[3][0] == "not_available" and "categories" in statuses[3][1]
    assert info["not_available"] == 3
    assert open_zip(run_pack(world, scene, pack, {})).namelist() == ["manifest.json", "01-Overview.docx"]


def test_a_pack_with_nothing_runnable_is_an_error_and_records_nothing(world, scene, db):
    pack = created(world, org_url(world), "Empty-handed", definition(layout_entry("Nope", "pdf")))
    resp = run_pack(world, scene, pack)
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "nothing_to_run"
    leftover = db.scalars(select(GeneratedReport).where(GeneratedReport.params["pack_id"].astext == pack["id"])).all()
    assert leftover == []


def test_a_pack_with_no_entries_cannot_run(world, scene):
    pack = created(world, org_url(world), "Blank", definition())
    assert run_pack(world, scene, pack).status_code == 409


def test_a_bad_variable_value_is_a_422_before_anything_runs(world, scene):
    pack = created(world, org_url(world), "Strict", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES]))
    resp = run_pack(world, scene, pack, {"variables": {"categories": "not a list"}})
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "variable_values"
    undeclared = run_pack(world, scene, pack, {"variables": {"categories": ["Security"], "other": 1}})
    assert undeclared.status_code == 422


def test_each_included_entry_leaves_a_provenance_row_sharing_a_pack_run_id(world, scene, db):
    pack = created(world, org_url(world), "Traced", definition(
        layout_entry("Overview", "docx"), {"kind": "report", "module_key": "decisions", "report": "d1", "format": "csv"},
        variables=[CATEGORIES],
    ))
    assert run_pack(world, scene, pack, {"variables": {"categories": ["Security"]}}).status_code == 200
    rows = db.scalars(
        select(GeneratedReport).where(GeneratedReport.params["pack_id"].astext == pack["id"]).order_by(GeneratedReport.format)
    ).all()
    assert len(rows) == 2
    assert len({r.pack_run_id for r in rows}) == 1 and rows[0].pack_run_id is not None
    by_format = {r.format: r for r in rows}
    assert by_format["docx"].layout_name == "Overview" and by_format["docx"].report_key is None
    assert by_format["docx"].params["variables"] == {"categories": ["Security"]}
    assert by_format["csv"].report_key == "decisions.d1" and by_format["csv"].layout_version == 0
    assert {r.params["entry"] for r in rows} == {1, 2}
    assert all(r.params["pack_version"] == 1 for r in rows)


def test_the_preview_counts_each_entry_and_stores_nothing(world, scene, db):
    pack = created(world, org_url(world), "Preview", definition(
        layout_entry("Overview", "docx"), layout_entry("Gone", "pdf"), variables=[CATEGORIES],
    ))
    before = len(db.scalars(select(GeneratedReport).where(GeneratedReport.project_id == uuid.UUID(scene["id"]))).all())
    resp = world.client.post(
        project_url(scene, f"/{pack['id']}/preview"), json={"variables": {"categories": ["Security", "Billing"]}},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["entries"][0]["records"] == 3 and out["entries"][0]["status"] == "included"
    assert out["entries"][1]["status"] == "not_available" and out["not_available"] == 1
    assert out["total_records"] == 3
    db.expire_all()
    assert len(db.scalars(select(GeneratedReport).where(GeneratedReport.project_id == uuid.UUID(scene["id"]))).all()) == before


def test_the_run_form_lists_the_variables_with_their_options(world, scene):
    pack = created(world, org_url(world), "Form", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES]))
    form = world.client.get(project_url(scene, f"/{pack['id']}/form"), headers=auth_headers(world.token)).json()
    assert form["name"] == "Form" and form["entries"] == 1
    variable = form["variables"][0]
    assert variable["name"] == "categories" and variable["multiple"] is True
    assert {"Security", "Usability", "Billing"} <= set(variable["options"])


def test_a_project_pack_resolves_its_layouts_in_the_project_by_name_and_tier(world, scene):
    make_layout(world, "Overview", requirements_tree("document", CATEGORIES), project=scene)  # shadows the organisation's
    pack = created(world, project_url(scene), "Tiered", definition(
        layout_entry("Overview", "docx", tier="organization", variables={"categories": ["Billing"]}),
        layout_entry("Overview", "pdf", tier="project", variables={"categories": ["Billing"]}),
    ))
    info = manifest(open_zip(run_pack(world, scene, pack)))
    # The project's own "Overview" shadows the organisation one in this project, so the organisation tier is not reachable.
    assert [e["status"] for e in info["entries"]] == ["not_available", "included"]


def test_a_hidden_layout_is_not_available_to_a_pack(world, scene):
    layouts = world.client.get(f"/api/v1/projects/{scene['id']}/report-layouts", headers=auth_headers(world.token)).json()
    overview = next(item for item in layouts if item["name"] == "Overview")
    world.client.put(
        f"/api/v1/projects/{scene['id']}/report-layouts/{overview['id']}/visibility", json={"hidden": True},
        headers=auth_headers(world.token),
    )
    billing = {"categories": ["Billing"]}
    pack = created(world, org_url(world), "Hidden", definition(
        layout_entry("Overview", "docx", variables=billing), layout_entry("Rows", "xlsx", variables=billing),
    ))
    info = manifest(open_zip(run_pack(world, scene, pack)))
    assert [e["status"] for e in info["entries"]] == ["not_available", "included"]


def test_a_module_report_that_is_off_or_has_no_org_variant_is_listed_not_available(world, scene):
    pack = created(world, org_url(world), "Org", definition(
        {**D1, "format": "csv"}, layout_entry("Rows", "csv", variables={"categories": ["Billing"]}),
    ))
    resp = world.client.post(org_url(world, f"/{pack['id']}/run"), json={}, headers=auth_headers(world.token))
    archive = open_zip(resp)
    info = manifest(archive)
    assert info["scope"]["type"] == "organization"
    assert info["entries"][0]["status"] == "not_available" and "organisation-wide" in info["entries"][0]["reason"]
    assert info["entries"][1]["status"] == "included"
    assert info["entries"][1]["record_counts"][REQ] == 1


def test_a_run_never_includes_more_than_the_caller_can_read(world, scene):
    """A member with no role on the project cannot run its pack at all; the pack adds no access."""
    pack = created(world, org_url(world), "Guarded", definition(layout_entry("Rows", "csv", variables={"categories": ["Billing"]})))
    outsider = create_org_user(world.client, world.token, world.org["id"], "outsider@example.com")
    assert outsider
    token = login(world.client, "outsider@example.com", "Password123!")
    assert run_pack(world, scene, pack, token=token).status_code in (403, 404)


def test_the_manifest_holds_no_record_content(world, scene):
    pack = created(world, org_url(world), "Clean", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES]))
    raw = open_zip(run_pack(world, scene, pack, {"variables": {"categories": ["Security"]}})).read("manifest.json").decode()
    assert "Login must be strong" not in raw and "Audit trail" not in raw


def test_a_module_report_whose_module_is_off_is_not_available(client, admin_token):
    world = World(client, admin_token, "Off Org")  # the decisions module is not enabled
    project = world.project("Alpha")
    pack = created(world, org_url(world), "Needs decisions", definition(
        {"kind": "report", "module_key": "decisions", "report": "d1", "format": "csv"}, layout_entry("Rows", "csv"),
    ))
    make_layout(world, "Rows", requirements_tree("table"))
    info = manifest(open_zip(run_pack(world, project, pack)))
    assert info["entries"][0]["status"] == "not_available" and "not enabled" in info["entries"][0]["reason"]
    assert info["entries"][1]["status"] == "included"


# ---- saved variable sets and overrides ---------------------------------------------------------------------------


def sets_url(base: str, pack: dict, suffix: str = "") -> str:
    return f"{base}/{pack['id']}/sets{suffix}"


def save_set(world: World, url: str, name: str, values: dict[str, Any], *, token: str | None = None):
    return world.client.post(url, json={"name": name, "values": values}, headers=auth_headers(token or world.token))


def pack_with_variable(world: World, name: str = "Per team", *, url: str | None = None, **entry_kwargs: Any) -> dict:
    return created(world, url or org_url(world), name, definition(layout_entry("Overview", "docx", **entry_kwargs), variables=[CATEGORIES]))


def run_counts(world: World, project: dict, pack: dict, body: dict[str, Any]) -> dict[str, Any]:
    return manifest(open_zip(run_pack(world, project, pack, body)))


def test_a_set_is_checked_against_the_packs_variables(world):
    pack = pack_with_variable(world)
    url = sets_url(org_url(world), pack)
    assert save_set(world, url, "Team Alpha", {"categories": ["Security", "Billing"]}).status_code == 201
    undeclared = save_set(world, url, "Bad", {"nope": 1})
    assert undeclared.status_code == 422 and undeclared.json()["detail"]["problems"][0]["name"] == "nope"
    wrong = save_set(world, url, "Bad too", {"categories": "Security"})
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "variable_values"
    assert save_set(world, url, "team alpha", {}).status_code == 409  # names are unique, ignoring case
    listed = world.client.get(url, headers=auth_headers(world.token)).json()
    assert [(s["name"], s["origin"], s["editable"]) for s in listed] == [("Team Alpha", "pack", True)]


def test_rename_change_and_delete_a_set(world):
    pack = pack_with_variable(world)
    url = sets_url(org_url(world), pack)
    created_set = save_set(world, url, "One", {"categories": ["Security"]}).json()
    patched = world.client.patch(
        sets_url(org_url(world), pack, f"/{created_set['id']}"), json={"name": "Two", "values": {"categories": ["Billing"]}},
        headers=auth_headers(world.token),
    )
    assert patched.status_code == 200 and patched.json()["name"] == "Two" and patched.json()["base"] == {"categories": ["Billing"]}
    gone = world.client.delete(sets_url(org_url(world), pack, f"/{created_set['id']}"), headers=auth_headers(world.token))
    assert gone.status_code == 204
    assert world.client.get(url, headers=auth_headers(world.token)).json() == []


def test_a_run_starts_from_a_set_and_what_is_typed_wins(world, scene):
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Team Alpha", {"categories": ["Security"]}).json()
    info = run_counts(world, scene, pack, {"variable_set_id": chosen["id"]})
    assert info["variable_set"] == "Team Alpha" and info["variables"] == {"categories": ["Security"]}
    assert info["entries"][0]["record_counts"][REQ] == 2
    typed = run_counts(world, scene, pack, {"variable_set_id": chosen["id"], "variables": {"categories": ["Billing"]}})
    assert typed["entries"][0]["record_counts"][REQ] == 1


def test_an_unknown_set_is_a_404(world, scene):
    pack = pack_with_variable(world)
    assert run_pack(world, scene, pack, {"variable_set_id": str(uuid.uuid4())}).status_code == 404
    other = pack_with_variable(world, "Other")
    foreign = save_set(world, sets_url(org_url(world), other), "Theirs", {"categories": ["Billing"]}).json()
    assert run_pack(world, scene, pack, {"variable_set_id": foreign["id"]}).status_code == 404  # another pack's set


def test_a_project_overrides_an_organisation_set_per_variable_and_can_reset_it(world, scene):
    two = {"name": "level", "type": "text", "label": "Level", "default": "base"}
    pack = created(world, org_url(world), "Two vars", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES, two]))
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"], "level": "gold"}).json()
    put = world.client.put(
        sets_url(project_url(scene), pack, f"/{chosen['id']}/override"), json={"values": {"categories": ["Billing"]}},
        headers=auth_headers(world.token),
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["override"] == {"categories": ["Billing"]} and body["overridden_by"] == scene["id"]
    assert body["effective"] == {"categories": ["Billing"], "level": "gold"}  # level falls back to the set's value
    assert body["base"] == {"categories": ["Security"], "level": "gold"} and body["overridable"] and not body["editable"]

    info = run_counts(world, scene, pack, {"variable_set_id": chosen["id"]})
    assert info["variables"] == {"categories": ["Billing"], "level": "gold"}
    assert info["entries"][0]["record_counts"][REQ] == 1

    reset = world.client.delete(sets_url(project_url(scene), pack, f"/{chosen['id']}/override"), headers=auth_headers(world.token))
    assert reset.json()["override"] is None and reset.json()["effective"]["categories"] == ["Security"]
    assert run_counts(world, scene, pack, {"variable_set_id": chosen["id"]})["entries"][0]["record_counts"][REQ] == 2


def test_the_nearest_ancestors_override_wins(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()

    def override(project: dict, values: dict[str, Any]) -> None:
        resp = world.client.put(
            sets_url(project_url(project), pack, f"/{chosen['id']}/override"), json={"values": values}, headers=auth_headers(world.token),
        )
        assert resp.status_code == 200, resp.text

    def effective(project: dict) -> Any:
        listed = world.client.get(sets_url(project_url(project), pack), headers=auth_headers(world.token)).json()
        return listed[0]["effective"]["categories"], listed[0]["overridden_by"]

    assert effective(child) == (["Security"], None)
    override(parent, {"categories": ["Usability"]})
    assert effective(child) == (["Usability"], parent["id"])  # a child inherits its parent's override
    override(child, {"categories": ["Billing"]})
    assert effective(child) == (["Billing"], child["id"])  # the nearest one wins
    assert effective(parent) == (["Usability"], parent["id"])  # and the parent is unaffected by the child


def test_an_empty_override_removes_it(world, scene):
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    url = sets_url(project_url(scene), pack, f"/{chosen['id']}/override")
    world.client.put(url, json={"values": {"categories": ["Billing"]}}, headers=auth_headers(world.token))
    cleared = world.client.put(url, json={"values": {}}, headers=auth_headers(world.token))
    assert cleared.json()["override"] is None


def test_an_override_is_checked_and_only_an_inherited_packs_own_set_can_be_overridden(world, scene):
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    url = sets_url(project_url(scene), pack, f"/{chosen['id']}/override")
    assert world.client.put(url, json={"values": {"categories": 5}}, headers=auth_headers(world.token)).status_code == 422

    own = created(world, project_url(scene), "Own pack", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES]))
    own_set = save_set(world, sets_url(project_url(scene), own), "Mine", {"categories": ["Billing"]})
    assert own_set.status_code == 201 and own_set.json()["origin"] == "pack" and own_set.json()["editable"]
    override_own = world.client.put(
        sets_url(project_url(scene), own, f"/{own_set.json()['id']}/override"), json={"values": {}}, headers=auth_headers(world.token),
    )
    assert override_own.status_code == 403


def test_a_project_adds_its_own_set_beside_the_organisations_and_cannot_edit_the_organisations(world, scene):
    pack = pack_with_variable(world)
    inherited = save_set(world, sets_url(org_url(world), pack), "Org default", {"categories": ["Security"]}).json()
    added = save_set(world, sets_url(project_url(scene), pack), "Our team", {"categories": ["Billing"]})
    assert added.status_code == 201 and added.json()["origin"] == "project" and added.json()["editable"]
    assert save_set(world, sets_url(project_url(scene), pack), "org default", {}).status_code == 409  # one name, one set

    listed = world.client.get(sets_url(project_url(scene), pack), headers=auth_headers(world.token)).json()
    assert {s["name"]: s["origin"] for s in listed} == {"Org default": "pack", "Our team": "project"}
    edit = world.client.patch(
        sets_url(project_url(scene), pack, f"/{inherited['id']}"), json={"name": "x"}, headers=auth_headers(world.token),
    )
    assert edit.status_code == 403
    drop = world.client.delete(sets_url(project_url(scene), pack, f"/{inherited['id']}"), headers=auth_headers(world.token))
    assert drop.status_code == 403
    assert run_counts(world, scene, pack, {"variable_set_id": added.json()["id"]})["entries"][0]["record_counts"][REQ] == 1

    sibling = world.project("Sibling")
    others = world.client.get(sets_url(project_url(sibling), pack), headers=auth_headers(world.token)).json()
    assert [s["name"] for s in others] == ["Org default"]  # another project does not see it
    assert run_pack(world, sibling, pack, {"variable_set_id": added.json()["id"]}).status_code == 404


def test_a_project_added_set_cannot_be_used_in_an_organisation_run(world, scene):
    pack = pack_with_variable(world)
    added = save_set(world, sets_url(project_url(scene), pack), "Our team", {"categories": ["Billing"]}).json()
    resp = world.client.post(org_url(world, f"/{pack['id']}/run"), json={"variable_set_id": added["id"]}, headers=auth_headers(world.token))
    assert resp.status_code == 404


def test_an_organisation_run_gives_each_project_its_own_effective_values(world, scene):
    second = world.project("Beta")
    ids = {name: category(world, second, name) for name in ("Security", "Billing")}
    requirement(world, second, "Beta security", ids["Security"])
    requirement(world, second, "Beta billing one", ids["Billing"])
    requirement(world, second, "Beta billing two", ids["Billing"])
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    world.client.put(
        sets_url(project_url(second), pack, f"/{chosen['id']}/override"), json={"values": {"categories": ["Billing"]}},
        headers=auth_headers(world.token),
    )
    resp = world.client.post(org_url(world, f"/{pack['id']}/run"), json={"variable_set_id": chosen["id"]}, headers=auth_headers(world.token))
    info = manifest(open_zip(resp))
    entry = info["entries"][0]
    assert info["variable_set"] == "Alpha"
    assert entry["variables_by_project"] == {"Alpha": {"categories": ["Security"]}, "Beta": {"categories": ["Billing"]}}
    assert entry["record_counts"][REQ] == 2 + 2  # Alpha's two Security requirements and Beta's two Billing ones
    preview = world.client.post(org_url(world, f"/{pack['id']}/preview"), json={"variable_set_id": chosen["id"]}, headers=auth_headers(world.token))
    assert preview.json()["entries"][0]["records"] == 4 and preview.json()["variable_set"] == "Alpha"


def test_the_run_form_lists_the_sets_with_the_values_this_project_would_use(world, scene):
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    world.client.put(
        sets_url(project_url(scene), pack, f"/{chosen['id']}/override"), json={"values": {"categories": ["Usability"]}},
        headers=auth_headers(world.token),
    )
    form = world.client.get(project_url(scene, f"/{pack['id']}/form"), headers=auth_headers(world.token)).json()
    assert [(s["name"], s["values"]) for s in form["sets"]] == [("Alpha", {"categories": ["Usability"]})]


def test_a_stored_value_that_is_no_longer_an_option_is_flagged_not_dropped(world, scene):
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Old", {"categories": ["Retired category"]})
    assert chosen.status_code == 201  # options advise; they do not refuse
    form = world.client.get(project_url(scene, f"/{pack['id']}/form"), headers=auth_headers(world.token)).json()
    assert form["sets"][0]["warnings"] and "Categories" in form["sets"][0]["warnings"][0]
    assert "Retired category" not in json.dumps(form["sets"][0]["warnings"])  # names the variable, never the value
    info = run_counts(world, scene, pack, {"variable_set_id": chosen.json()["id"]})
    assert info["variables"] == {"categories": ["Retired category"]} and info["warnings"]


def test_a_new_pack_version_that_drops_a_variable_ignores_the_stored_value_with_a_remark(world, scene):
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    world.client.put(
        org_url(world, f"/{pack['id']}/definition"), headers=auth_headers(world.token), json={
            "definition": definition(layout_entry("Rows", "csv", variables={"categories": ["Billing"]})), "base_version": 1,
        },
    )
    info = run_counts(world, scene, pack, {"variable_set_id": chosen["id"]})
    assert any("no longer declares" in w for w in info["warnings"])
    assert info["entries"][0]["status"] == "included"


def test_deleting_a_set_or_its_pack_removes_the_overrides(world, scene, db):
    from app.models.report_pack import ReportPackSetOverride

    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    world.client.put(
        sets_url(project_url(scene), pack, f"/{chosen['id']}/override"), json={"values": {"categories": ["Billing"]}},
        headers=auth_headers(world.token),
    )
    assert db.scalars(select(ReportPackSetOverride).where(ReportPackSetOverride.set_id == uuid.UUID(chosen["id"]))).all()
    world.client.delete(org_url(world, f"/{pack['id']}"), headers=auth_headers(world.token))
    db.expire_all()
    assert db.scalars(select(ReportPackSetOverride).where(ReportPackSetOverride.set_id == uuid.UUID(chosen["id"]))).all() == []


def test_only_a_manager_may_change_sets_but_a_runner_sees_them_on_the_form(world, scene):
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    member_id = create_org_user(world.client, world.token, world.org["id"], "setmember@example.com")
    world.client.post(
        f"/api/v1/projects/{scene['id']}/roles", json={"user_id": member_id, "role": "member"}, headers=auth_headers(world.token),
    )
    token = login(world.client, "setmember@example.com", "Password123!")
    assert save_set(world, sets_url(project_url(scene), pack), "Mine", {}, token=token).status_code == 403
    override = world.client.put(
        sets_url(project_url(scene), pack, f"/{chosen['id']}/override"), json={"values": {}}, headers=auth_headers(token),
    )
    assert override.status_code == 403
    form = world.client.get(project_url(scene, f"/{pack['id']}/form"), headers=auth_headers(token))
    assert form.status_code == 200 and [s["name"] for s in form.json()["sets"]] == ["Alpha"]


def test_set_changes_are_audited_without_values(world, scene, db):
    from app.models.audit import AuditEvent

    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Secret-ish category"]}).json()
    world.client.put(
        sets_url(project_url(scene), pack, f"/{chosen['id']}/override"), json={"values": {"categories": ["Billing"]}},
        headers=auth_headers(world.token),
    )
    events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "report_pack_set", AuditEvent.entity_id == chosen["id"])).all()
    assert {e.action for e in events} == {"created", "override_saved"}
    assert "Secret-ish category" not in json.dumps([e.detail for e in events]) and "Billing" not in json.dumps([e.detail for e in events])


# ---- bundles ----------------------------------------------------------------------------------------------------


def export_project(world: World, project: dict) -> bytes:
    resp = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.content


def import_project(world: World, bundle: bytes, name: str = "Imported") -> dict:
    resp = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def rewrite(bundle: bytes, member: str, edit) -> bytes:
    """The zip with `member` (a JSON file) passed through `edit`."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == member:
                parsed = json.loads(data)
                edit(parsed)
                data = json.dumps(parsed).encode()
            dst.writestr(item, data)
    return out.getvalue()


def project_pack_names(world: World, project: dict) -> dict[str, dict]:
    return project_names(world, project)


def test_a_project_bundle_round_trips_packs_sets_hides_added_sets_and_overrides(world):
    source = world.project("Source")
    h = auth_headers(world.token)
    inherited = pack_with_variable(world, "Org pack")
    org_set = save_set(world, sets_url(org_url(world), inherited), "Alpha", {"categories": ["Security"]}).json()
    hidden = created(world, org_url(world), "Hidden here")
    world.client.put(project_url(source, f"/{hidden['id']}/visibility"), json={"hidden": True}, headers=h)
    world.client.put(
        sets_url(project_url(source), inherited, f"/{org_set['id']}/override"), json={"values": {"categories": ["Billing"]}}, headers=h,
    )
    save_set(world, sets_url(project_url(source), inherited), "Ours", {"categories": ["Usability"]})
    own = created(world, project_url(source), "Own pack", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES]))
    world.client.put(
        project_url(source, f"/{own['id']}/definition"), headers=h,
        json={"definition": definition(layout_entry("Overview", "docx"), layout_entry("Rows", "csv"), variables=[CATEGORIES]),
              "base_version": 1, "comment": "add rows"},
    )
    save_set(world, sets_url(project_url(source), own), "Own set", {"categories": ["Billing"]})

    result = import_project(world, export_project(world, source))

    assert result["warnings"] == []
    copy = result["project"]
    seen = project_names(world, copy)
    assert seen["Own pack"]["current_version"] == 2 and seen["Own pack"]["origin"] == "project" and seen["Own pack"]["id"] != own["id"]
    assert seen["Hidden here"]["hidden"] is True and seen["Org pack"]["hidden"] is False
    versions = world.client.get(project_url(copy, f"/{seen['Own pack']['id']}/versions"), headers=h).json()
    assert [(v["version"], v["comment"]) for v in versions] == [(2, "add rows"), (1, "")]
    own_sets = world.client.get(sets_url(project_url(copy), seen["Own pack"]), headers=h).json()
    assert [(s["name"], s["base"]) for s in own_sets] == [("Own set", {"categories": ["Billing"]})]
    inherited_sets = {s["name"]: s for s in world.client.get(sets_url(project_url(copy), seen["Org pack"]), headers=h).json()}
    assert inherited_sets["Alpha"]["override"] == {"categories": ["Billing"]}
    assert inherited_sets["Alpha"]["base"] == {"categories": ["Security"]}  # the organisation's set is unchanged
    assert inherited_sets["Ours"]["origin"] == "project" and inherited_sets["Ours"]["base"] == {"categories": ["Usability"]}


def test_a_bundle_definition_is_validated_again_and_a_bad_set_is_skipped(world):
    source = world.project("Source")
    own = created(world, project_url(source), "Own pack", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES]))
    save_set(world, sets_url(project_url(source), own), "Good", {"categories": ["Billing"]})
    save_set(world, sets_url(project_url(source), own), "Bad", {"categories": ["Billing"]})
    created(world, project_url(source), "Broken", definition(layout_entry("X")))

    def corrupt(data: dict) -> None:
        for pack in data["report_packs"]:
            if pack["name"] == "Broken":
                pack["versions"][0]["definition"]["entries"] = [{"kind": "nope"}]
            for item in pack.get("sets", []):
                if item["name"] == "Bad":
                    item["values"] = {"undeclared": 1}

    result = import_project(world, rewrite(export_project(world, source), "project.json", corrupt))

    assert any('"Broken"' in w and "skipped" in w for w in result["warnings"])
    assert any('"Bad"' in w and "skipped" in w for w in result["warnings"])
    seen = project_names(world, result["project"])
    assert set(seen) == {"Own pack"}
    sets = world.client.get(sets_url(project_url(result["project"]), seen["Own pack"]), headers=auth_headers(world.token)).json()
    assert [s["name"] for s in sets] == ["Good"]


def test_a_hide_an_added_set_and_an_override_with_no_matching_inherited_pack_are_reported(world):
    source = world.project("Source")
    h = auth_headers(world.token)
    inherited = pack_with_variable(world, "Org pack")
    org_set = save_set(world, sets_url(org_url(world), inherited), "Alpha", {"categories": ["Security"]}).json()
    world.client.put(project_url(source, f"/{inherited['id']}/visibility"), json={"hidden": True}, headers=h)
    save_set(world, sets_url(project_url(source), inherited), "Ours", {})
    world.client.put(
        sets_url(project_url(source), inherited, f"/{org_set['id']}/override"), json={"values": {"categories": ["Billing"]}}, headers=h,
    )
    bundle = export_project(world, source)
    world.client.delete(org_url(world, f"/{inherited['id']}"), headers=h)

    warnings = import_project(world, bundle)["warnings"]

    assert any('Hidden report pack "Org pack"' in w for w in warnings)
    assert any('"Ours"' in w and "inherits no report pack" in w for w in warnings)
    assert any('"Alpha"' in w and "inherits no such" in w for w in warnings)


def test_an_organisation_bundle_carries_packs_sets_and_project_overrides(client, admin_token, world):
    source = world.project("Source")
    h = auth_headers(world.token)
    pack = pack_with_variable(world, "Org pack")
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    world.client.put(
        sets_url(project_url(source), pack, f"/{chosen['id']}/override"), json={"values": {"categories": ["Billing"]}}, headers=h,
    )
    created(world, project_url(source), "Own pack")
    bundle = client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=h).content

    resp = client.post(
        "/api/v1/orgs/import", data={"name": f"Copy {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    new_org_id = resp.json()["organization"]["id"]

    listed = client.get(f"/api/v1/orgs/{new_org_id}/report-packs", headers=h).json()
    assert [row["name"] for row in listed] == ["Org pack"]
    org_sets = client.get(f"/api/v1/orgs/{new_org_id}/report-packs/{listed[0]['id']}/sets", headers=h).json()
    assert [(s["name"], s["base"]) for s in org_sets] == [("Alpha", {"categories": ["Security"]})]
    projects = client.get(f"/api/v1/projects?organization_id={new_org_id}", headers=h).json()
    copy = next(p for p in projects if p["name"] == "Source")
    seen = {row["name"]: row for row in client.get(f"/api/v1/projects/{copy['id']}/report-packs", headers=h).json()}
    assert seen["Own pack"]["origin"] == "project" and seen["Org pack"]["origin"] == "organization"
    mine = client.get(f"/api/v1/projects/{copy['id']}/report-packs/{seen['Org pack']['id']}/sets", headers=h).json()
    assert mine[0]["override"] == {"categories": ["Billing"]} and mine[0]["effective"] == {"categories": ["Billing"]}


def test_merging_never_overwrites_an_existing_pack(client, admin_token, world):
    h = auth_headers(world.token)
    created(world, org_url(world), "Shared name")
    created(world, org_url(world), "New one")
    bundle = client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=h).content

    target, target_token = create_org_admin_in(client, admin_token, "Merge Target")
    target_url = f"/api/v1/orgs/{target['id']}/report-packs"
    kept = client.post(
        target_url, json={"name": "Shared name", "definition": definition(layout_entry("keep me"))}, headers=auth_headers(target_token),
    ).json()
    opened = client.put(
        f"/api/v1/orgs/{target['id']}/advanced-settings", json={"external_user_policy": "anyone"}, headers=auth_headers(target_token),
    )
    assert opened.status_code == 200, opened.text

    merged = client.post(
        f"/api/v1/orgs/{target['id']}/import/merge", files={"file": ("bundle.zip", bundle, "application/zip")},
        data={"resolutions": "{}"}, headers=auth_headers(target_token),
    )
    assert merged.status_code == 200, merged.text

    rows = client.get(target_url, headers=auth_headers(target_token)).json()
    assert sorted(r["name"] for r in rows) == ["New one", "Shared name", "Shared name (imported)"]
    kept_now = client.get(f"{target_url}/{kept['id']}", headers=auth_headers(target_token)).json()
    assert kept_now["current"]["definition"] == definition(layout_entry("keep me")) and kept_now["current_version"] == 1


# ---- background runs --------------------------------------------------------------------------------------------


def queue_pack(world: World, project: dict | None, pack: dict, body: dict[str, Any] | None = None, token: str | None = None):
    url = (project_url(project) if project else org_url(world)) + f"/{pack['id']}/runs"
    return world.client.post(url, json=body or {}, headers=auth_headers(token or world.token))


def drain() -> int:
    """Produces every queued job (the leader's loop does this in a running stack)."""
    count = 0
    while report_run_jobs.run_next():
        count += 1
    return count


def test_a_pack_over_the_synchronous_bounds_asks_for_a_background_run(world, scene, monkeypatch):
    pack = created(world, org_url(world), "Big", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES]))
    monkeypatch.setattr(report_layout_eval, "MAX_OUTPUT", 2)
    body = {"variables": {"categories": ["Security", "Usability", "Billing"]}}
    resp = run_pack(world, scene, pack, body)
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "async_required"
    preview = world.client.post(project_url(scene, f"/{pack['id']}/preview"), json=body, headers=auth_headers(world.token))
    assert preview.status_code == 413  # a preview has nothing to queue


def test_a_queued_pack_is_produced_in_the_background_stored_and_downloadable(world, scene, db):
    pack = created(world, org_url(world), "Handover", definition(
        layout_entry("Overview", "docx"), {**D1, "format": "csv"}, variables=[CATEGORIES],
    ))
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    queued = queue_pack(world, scene, pack, {"variable_set_id": chosen["id"]})
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["id"]
    assert queued.json()["status"] == "queued" and queued.json()["format"] == "zip" and queued.json()["layout_name"] == "Handover"

    assert drain() >= 1
    done = world.client.get(f"/api/v1/report-runs/{run_id}", headers=auth_headers(world.token)).json()
    assert done["status"] == "ready" and done["output_filename"].endswith(".zip")
    download = world.client.get(f"/api/v1/report-runs/{run_id}/download", headers=auth_headers(world.token))
    assert download.status_code == 200 and download.headers["content-type"] == "application/zip"
    info = manifest(zipfile.ZipFile(io.BytesIO(download.content)))
    assert info["variable_set"] == "Alpha" and info["entries"][0]["record_counts"][REQ] == 2

    db.expire_all()
    rows = db.scalars(select(GeneratedReport).where(GeneratedReport.pack_run_id == db.get(GeneratedReport, uuid.UUID(run_id)).pack_run_id)).all()
    assert sorted(r.format for r in rows) == ["csv", "docx", "zip"]  # the job row and one row per included entry
    notice = world.client.get("/api/v1/notifications", headers=auth_headers(world.token)).json()
    assert any("Handover" in json.dumps(n) for n in (notice if isinstance(notice, list) else notice.get("items", [])))


def test_a_bad_value_or_set_is_refused_when_queueing_not_in_the_job(world, scene):
    pack = created(world, org_url(world), "Strict", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES]))
    bad = queue_pack(world, scene, pack, {"variables": {"categories": "nope"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "variable_values"
    assert queue_pack(world, scene, pack, {"variable_set_id": str(uuid.uuid4())}).status_code == 404


def test_the_job_runs_as_the_requester_and_fails_when_they_lost_access(world, scene, db):
    member_id = create_org_user(world.client, world.token, world.org["id"], "packjob@example.com")
    world.client.post(
        f"/api/v1/projects/{scene['id']}/roles", json={"user_id": member_id, "role": "member"}, headers=auth_headers(world.token),
    )
    token = login(world.client, "packjob@example.com", "Password123!")
    pack = created(world, org_url(world), "Mine", definition(layout_entry("Rows", "csv", variables={"categories": ["Billing"]})))
    queued = queue_pack(world, scene, pack, token=token)
    assert queued.status_code == 202, queued.text
    from app.models.user import User

    db.get(User, uuid.UUID(member_id)).is_archived = True
    db.commit()
    drain()
    db.expire_all()
    row = db.get(GeneratedReport, uuid.UUID(queued.json()["id"]))
    assert row.status == "failed" and row.error == report_run_jobs.FAILURE_ACCESS and row.output_key is None


def test_a_pack_job_with_nothing_runnable_fails_with_a_fixed_sentence(world, scene):
    pack = created(world, org_url(world), "Nothing", definition(layout_entry("Does not exist", "pdf")))
    queued = queue_pack(world, scene, pack)
    assert queued.status_code == 202
    drain()
    row = world.client.get(f"/api/v1/report-runs/{queued.json()['id']}", headers=auth_headers(world.token)).json()
    assert row["status"] == "failed" and "None of the reports" in row["error"]


def test_an_expired_pack_run_is_generated_again_with_its_set_and_values(world, scene, db):
    pack = created(world, org_url(world), "Handover again", definition(layout_entry("Overview", "docx"), variables=[CATEGORIES]))
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    run_id = queue_pack(world, scene, pack, {"variable_set_id": chosen["id"]}).json()["id"]
    drain()
    world.client.delete(f"/api/v1/report-runs/{run_id}", headers=auth_headers(world.token))

    resp = world.client.post(f"/api/v1/report-runs/{run_id}/again", headers=auth_headers(world.token))

    assert resp.status_code == 202, resp.text
    fresh = resp.json()["run"]
    assert fresh["id"] != run_id and fresh["format"] == "zip" and fresh["layout_name"] == "Handover again"
    assert drain() >= 1
    done = world.client.get(f"/api/v1/report-runs/{fresh['id']}/download", headers=auth_headers(world.token))
    assert done.status_code == 200 and manifest(zipfile.ZipFile(io.BytesIO(done.content)))["variable_set"] == "Alpha"


def test_a_hidden_pack_cannot_be_queued_and_only_the_requester_downloads(world, scene):
    pack = created(world, org_url(world), "Default pack", definition(layout_entry("Rows", "csv", variables={"categories": ["Billing"]})))
    queued = queue_pack(world, scene, pack)
    drain()
    other = create_org_user(world.client, world.token, world.org["id"], "packother@example.com")
    world.client.post(f"/api/v1/projects/{scene['id']}/roles", json={"user_id": other, "role": "member"}, headers=auth_headers(world.token))
    token = login(world.client, "packother@example.com", "Password123!")
    assert world.client.get(f"/api/v1/report-runs/{queued.json()['id']}/download", headers=auth_headers(token)).status_code == 404
    world.client.put(project_url(scene, f"/{pack['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    assert queue_pack(world, scene, pack).status_code == 404


def test_an_organisation_pack_can_be_queued_for_the_whole_organisation(world, scene):
    pack = created(world, org_url(world), "Org run", definition(layout_entry("Rows", "csv", variables={"categories": ["Billing"]})))
    queued = queue_pack(world, None, pack)
    assert queued.status_code == 202 and queued.json()["scope"] == "organization"
    drain()
    run_id = queued.json()["id"]
    got = world.client.get(f"/api/v1/report-runs/{run_id}/download", headers=auth_headers(world.token))
    assert got.status_code == 200
    assert manifest(zipfile.ZipFile(io.BytesIO(got.content)))["scope"]["type"] == "organization"


def test_deleting_the_organisation_removes_its_packs_sets_overrides_and_runs(client, admin_token, db):
    from sqlalchemy import text

    world = World(client, admin_token, "Doomed Org", decisions=True)
    project = world.project("Alpha")
    pack = pack_with_variable(world)
    chosen = save_set(world, sets_url(org_url(world), pack), "Alpha", {"categories": ["Security"]}).json()
    world.client.put(
        sets_url(project_url(project), pack, f"/{chosen['id']}/override"), json={"values": {"categories": ["Billing"]}},
        headers=auth_headers(world.token),
    )
    assert queue_pack(world, project, pack, {"variable_set_id": chosen["id"]}).status_code == 202
    drain()

    resp = client.request(
        "DELETE", f"/api/v1/orgs/{world.org['id']}", json={"confirm_name": world.org["name"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code in (200, 204), resp.text
    db.expire_all()
    for table, column, value in (
        ("report_packs", "id", pack["id"]), ("report_pack_versions", "pack_id", pack["id"]),
        ("report_pack_variable_sets", "pack_id", pack["id"]), ("report_pack_set_overrides", "set_id", chosen["id"]),
        ("generated_reports", "organization_id", world.org["id"]),
    ):
        count = db.execute(text(f"SELECT count(*) FROM {table} WHERE {column} = :v"), {"v": value}).scalar()
        assert count == 0, table
