"""External references on every surface: the list filter, the shared export and import column, search, report
fields, the page read, the look-up by outside key, the project bundle and the statements a list, export and bundle
need. The references themselves (the table, systems, authority) are pinned in `test_external_references.py`.

Each test builds its own organisation, so none depends on another's state.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.modules.context_strategy.models import PainPoint
from app.modules.registry import RecordCellError, RecordImportContext
from app.services.external_reference_surfaces import (
    ReferenceFilter,
    _split_cell,
    apply_imported_references,
    reference_cell,
    reference_column,
)
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import REQ, World

PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Surface Org", context_strategy=True, decisions=True)


def _base(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}"


def _refs_url(project: dict, record: tuple[str, uuid.UUID]) -> str:
    return f"{_base(project)}/artefacts/{record[0]}/{record[1]}/external-references"


def _systems(world: World, project: dict) -> dict[str, str]:
    rows = world.client.get(f"{_base(project)}/external-systems", headers=auth_headers(world.token)).json()
    return {r["name"]: r["id"] for r in rows}


def _ref(
    world: World, project: dict, record: tuple[str, uuid.UUID], system: str, key: str, **extra: object,
) -> dict:
    resp = world.client.post(
        _refs_url(project, record), json={"system_id": _systems(world, project)[system], "key": key, **extra},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["references"][-1]


def _member_token(world: World, project: dict, role: str = "member") -> str:
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"{_base(project)}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


# --- the cell text ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("entries", [
    [("Jira", "PROJ-1")], [("Jira", "A;B"), ("DOORS", "back\\slash")], [("Jira", "x"), ("Jira", "y")], [],
])
def test_a_cell_survives_a_round_trip_through_its_text(entries):
    assert _split_cell(reference_cell(entries)) == [f"{name}:{key}" for name, key in entries]


def test_a_semicolon_in_a_key_is_escaped_not_split():
    assert _split_cell("Jira:A\\;B; GitHub:7") == ["Jira:A;B", "GitHub:7"]
    assert _split_cell("  ;; ") == []


# --- the list filter ---------------------------------------------------------------------------------------------


def _listed(world: World, url: str, **params: object) -> set[str]:
    resp = world.client.get(url, params=params, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return {row["id"] for row in resp.json()}


def test_a_list_filters_by_system_and_by_key_and_combines_with_tags(world):
    project = world.project()
    a, b, c = (world.pain_point(project, t) for t in ("A", "B", "C"))
    _ref(world, project, (PAIN, a), "Jira", "PROJ-100")
    _ref(world, project, (PAIN, b), "Jira", "OPS-7")
    _ref(world, project, (PAIN, b), "GitHub", "repo#9")
    world.client.put(f"{_base(project)}/artefacts/{PAIN}/{a}/tags", json={"tags": ["x"]}, headers=auth_headers(world.token))
    url = f"{_base(project)}/modules/context_strategy/pain-points"

    assert _listed(world, url) == {str(a), str(b), str(c)}
    assert _listed(world, url, external_system=["Jira"]) == {str(a), str(b)}
    assert _listed(world, url, external_system=["jira", "GITHUB"]) == {str(a), str(b)}, "names match ignoring case"
    assert _listed(world, url, external_system=["GitHub"]) == {str(b)}
    assert _listed(world, url, external_key="proj") == {str(a)}, "a key matches by fragment, ignoring case"
    assert _listed(world, url, external_system=["Jira"], external_key="ops") == {str(b)}
    assert _listed(world, url, external_system=["GitHub"], external_key="proj") == set()
    assert _listed(world, url, external_system=["No such system"]) == set()
    assert _listed(world, url, external_key="%") == set(), "LIKE wildcards in the text are literal"
    assert _listed(world, url, external_system=["Jira"], tag=["x"]) == {str(a)}


def test_the_requirement_list_filters_by_reference(world):
    project = world.project()
    one, two = world.requirement(project, "One"), world.requirement(project, "Two")
    _ref(world, project, (REQ, one), "Jira", "DOC-1")
    url = f"{_base(project)}/requirements"
    assert _listed(world, url, external_system=["Jira"]) == {str(one)}
    assert _listed(world, url, external_key="doc-1") == {str(one)}
    assert _listed(world, url) == {str(one), str(two)}


def test_a_project_system_with_its_own_name_is_found_by_that_name(world):
    project = world.project()
    local = world.client.post(f"{_base(project)}/external-systems", json={"name": "Customer register"}, headers=auth_headers(world.token))
    assert local.status_code == 201, local.text
    record = world.pain_point(project)
    _ref(world, project, (PAIN, record), "Customer register", "C-1")
    url = f"{_base(project)}/modules/context_strategy/pain-points"
    assert _listed(world, url, external_system=["customer register"]) == {str(record)}


def test_a_reference_in_another_organisation_never_matches(world, client, admin_token):
    project = world.project()
    record = world.pain_point(project)
    other = World(client, admin_token, "Other Surface Org", context_strategy=True)
    other_project = other.project()
    foreign = other.pain_point(other_project)
    _ref(other, other_project, (PAIN, foreign), "Jira", "SAME-1")
    _ref(world, project, (PAIN, record), "Jira", "SAME-1")
    assert _listed(world, f"{_base(project)}/modules/context_strategy/pain-points", external_key="same-1") == {str(record)}


def test_the_filter_object_reads_blank_input_as_inactive():
    assert not ReferenceFilter.of([" ", ""], "  ").active
    assert ReferenceFilter.of(["Jira", "jira"], None).systems == ("Jira", "jira")
    assert ReferenceFilter.of([], "k").applied_keys == ["external_key"]


# --- export and import --------------------------------------------------------------------------------------------


def _export_rows(world: World, project: dict, record_type: str = PAIN, **params: object) -> list[dict]:
    resp = world.client.get(
        f"{_base(project)}/records/{record_type}/export", params=params, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import(world: World, project: dict, rows: list[dict], *, apply: bool = True, record_type: str = PAIN):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return world.client.post(
        f"{_base(project)}/records/{record_type}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", out.getvalue().encode("utf-8"), "text/csv")}, headers=auth_headers(world.token),
    )


def _keys(world: World, project: dict, record: tuple[str, uuid.UUID]) -> list[tuple[str, str]]:
    body = world.client.get(_refs_url(project, record), headers=auth_headers(world.token)).json()
    return [(r["system_name"], r["key"]) for r in body["references"]]


def test_the_export_has_a_shared_references_column_and_it_follows_the_page_filter(world):
    project = world.project()
    a, b = world.pain_point(project, "A"), world.pain_point(project, "B")
    _ref(world, project, (PAIN, a), "Jira", "P-1")
    _ref(world, project, (PAIN, a), "GitHub", "x;y")
    rows = {r["title"]: r for r in _export_rows(world, project)}
    assert rows["A"]["external_refs"] == "Jira:P-1; GitHub:x\\;y" and rows["B"]["external_refs"] == ""
    assert [r["title"] for r in _export_rows(world, project, external_system=["GitHub"])] == ["A"]
    assert [r["title"] for r in _export_rows(world, project, external_key="p-1")] == ["A"]
    assert b


def test_a_requirement_export_has_the_column_too(world):
    project = world.project()
    requirement = world.requirement(project)
    _ref(world, project, (REQ, requirement), "Jira", "DOC-4")
    [row] = _export_rows(world, project, REQ)
    assert row["external_refs"] == "Jira:DOC-4"


def test_import_changes_references_keeps_what_is_unchanged_and_reports_the_change(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    kept = _ref(world, project, record, "Jira", "KEEP-1", url="https://t.example/1", note="n", role="origin")
    _ref(world, project, record, "GitHub", "gone#1")
    [row] = _export_rows(world, project)
    row["external_refs"] = "Jira:KEEP-1; ServiceNow:INC-2"
    preview = _import(world, project, [row], apply=False).json()
    assert preview["rows"][0]["action"] == "update"
    assert [c["column"] for c in preview["rows"][0]["changes"]] == ["external_refs"]
    assert _keys(world, project, record) == [("Jira", "KEEP-1"), ("GitHub", "gone#1")], "a preview changes nothing"

    assert _import(world, project, [row]).json()["rows"][0]["action"] == "update"
    assert _keys(world, project, record) == [("Jira", "KEEP-1"), ("ServiceNow", "INC-2")]
    body = world.client.get(_refs_url(project, record), headers=auth_headers(world.token)).json()["references"]
    still = next(r for r in body if r["id"] == kept["id"])
    assert (still["url"], still["note"], still["role"]) == ("https://t.example/1", "n", "origin"), "a kept reference is untouched"
    assert _import(world, project, [row]).json()["rows"][0]["action"] == "unchanged"
    row["external_refs"] = ""
    _import(world, project, [row])
    assert _keys(world, project, record) == []


def test_import_creates_a_record_with_its_references(world):
    project = world.project()
    world.pain_point(project)
    [row] = _export_rows(world, project)
    row.update({"code": "", "title": "Imported", "external_refs": "Jira:NEW-1"})
    body = _import(world, project, [row]).json()
    assert body["rows"][0]["action"] == "create", body
    created = next(r for r in _export_rows(world, project) if r["title"] == "Imported")
    assert created["external_refs"] == "Jira:NEW-1"


@pytest.mark.parametrize("cell", ["Nope:1", "Jira", "Jira:", ":1", "Jira:ok; Zendesk"])
def test_import_refuses_a_bad_cell_and_leaves_the_record_alone(world, cell):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    [row] = _export_rows(world, project)
    row["external_refs"] = cell
    body = _import(world, project, [row]).json()
    assert body["rows"][0]["action"] == "error"
    assert _keys(world, project, record) == []


def test_a_system_name_with_a_colon_is_read_by_its_longest_name(world):
    project = world.project()
    world.client.post(f"{_base(project)}/external-systems", json={"name": "Lab: Tracker"}, headers=auth_headers(world.token))
    record = (PAIN, world.pain_point(project))
    _ref(world, project, record, "Lab: Tracker", "T-1")
    [row] = _export_rows(world, project)
    assert row["external_refs"] == "Lab: Tracker:T-1"
    row["external_refs"] = "Lab: Tracker:T-1; Jira:J-2"
    assert _import(world, project, [row]).json()["rows"][0]["action"] == "update"
    assert _keys(world, project, record) == [("Lab: Tracker", "T-1"), ("Jira", "J-2")]


def test_the_import_column_refuses_a_change_from_someone_who_may_not_tag(world):
    project = world.project()
    record = world.pain_point(project)
    with SessionLocal() as db:
        owner = db.get(Project, uuid.UUID(project["id"]))
        assert owner is not None
        organization = db.get(Organization, owner.organization_id)
        assert organization is not None
        built = reference_column(db, organization, owner, PAIN, may_edit=False, id_of=lambda r: r.id)
        assert built is not None and built[0].parse is not None
        ctx = RecordImportContext(db=db, project=owner, user=SimpleNamespace(id=uuid.uuid4()), organization=organization)
        wanted = built[0].parse(ctx, "Jira:X-1")
        assert len(wanted) == 1 and built[0].parse(ctx, "") == []
        with pytest.raises(RecordCellError, match="permission"):
            apply_imported_references(ctx, PAIN, db.get(PainPoint, record), wanted, built[1])
        db.rollback()


# --- search --------------------------------------------------------------------------------------------------------


def _search(world: World, text: str, fields: list[str]) -> list[dict]:
    resp = world.client.post("/api/v1/search", json={"q": text, "fields": fields, "scope": "all"}, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()["hits"]


def test_search_finds_records_by_outside_key_or_system_when_asked(world):
    project = world.project()
    hit, other = world.pain_point(project, "Hit"), world.pain_point(project, "Other")
    _ref(world, project, (PAIN, hit), "Jira", "WIDGET-4242", note="secret note")
    assert _search(world, "widget-4242", ["title"]) == [], "references are searched only when the field is chosen"
    hits = _search(world, "widget-4242", ["title", "external_refs"])
    assert [h["id"] for h in hits] == [str(hit)] and other
    assert hits[0]["snippet"]["field_key"] == "external_refs" and "Jira:WIDGET-4242" in hits[0]["snippet"]["text"]
    assert str(hit) in {h["id"] for h in _search(world, "jira", ["external_refs"])}
    assert _search(world, "secret note", ["external_refs"]) == [], "a note is not searched"


def test_the_search_field_picker_lists_the_references_field(world):
    resp = world.client.get("/api/v1/search/fields", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    assert "external_refs" in [f["key"] for f in resp.json()]


# --- reports -------------------------------------------------------------------------------------------------------


def test_reports_offer_an_external_references_field_for_every_type(world):
    from app.services.report_fields import field_catalogue, field_domain, load_records

    project = world.project()
    one, bare = world.pain_point(project, "One"), world.pain_point(project, "Bare")
    _ref(world, project, (PAIN, one), "Jira", "R-1")
    _ref(world, project, (PAIN, one), "GitHub", "R-2")
    requirement = world.requirement(project)
    _ref(world, project, (REQ, requirement), "Jira", "R-3")
    with SessionLocal() as db:
        for artefact_type in (PAIN, REQ, "compliance_requirement"):
            assert "external_refs" in [f.key for f in field_catalogue(artefact_type)], artefact_type
        assert field_domain(db, PAIN, "external_refs", [uuid.UUID(project["id"])]) is None
        records = load_records(db, PAIN, [one, bare], ["external_refs"])
        assert records[one].values["external_refs"] == "Jira:R-1; GitHub:R-2"
        assert not records[bare].values.get("external_refs")
        assert load_records(db, REQ, [requirement], ["external_refs"])[requirement].values["external_refs"] == "Jira:R-3"


# --- the page read -------------------------------------------------------------------------------------------------


def test_a_page_read_returns_the_references_of_visible_records_only(world):
    project, other = world.project("A"), world.project("B")
    with_refs, bare, foreign = world.pain_point(project, "With"), world.pain_point(project, "Bare"), world.pain_point(other, "Foreign")
    _ref(world, project, (PAIN, with_refs), "Jira", "PG-1")
    _ref(world, other, (PAIN, foreign), "Jira", "PG-2")
    url = f"{_base(project)}/external-references/{PAIN}"
    resp = world.client.get(
        url, params={"id": [str(with_refs), str(bare), str(foreign), str(uuid.uuid4())]}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["references"]
    assert list(body) == [str(with_refs)] and body[str(with_refs)][0]["key"] == "PG-1"
    assert world.client.get(f"{_base(project)}/external-references/nonsense", headers=auth_headers(world.token)).status_code == 404
    assert world.client.get(url, headers=auth_headers(world.token)).json() == {"references": {}}
    outsider = _member_token(world, other)
    assert world.client.get(url, params={"id": [str(with_refs)]}, headers=auth_headers(outsider)).status_code in (403, 404)


# --- the look-up by outside key ------------------------------------------------------------------------------------


def test_a_key_finds_the_records_that_carry_it_across_types(world):
    jira = "Jira"
    project = world.project()
    requirement, pain = world.requirement(project, "Needs it"), world.pain_point(project, "Also needs it")
    unrelated = world.pain_point(project, "Unrelated")
    _ref(world, project, (REQ, requirement), jira, "FIND-1")
    _ref(world, project, (PAIN, pain), "GitHub", "find-1")
    _ref(world, project, (PAIN, unrelated), jira, "FIND-10")
    url = f"{_base(project)}/records/by-external-reference"

    def found(**params: object) -> set[str]:
        resp = world.client.get(url, params=params, headers=auth_headers(world.token))
        assert resp.status_code == 200, resp.text
        return {r["id"] for r in resp.json()["records"]}

    assert found(key="FIND-1") == {str(requirement), str(pain)}, "exact key, any system, ignoring case"
    assert found(key="FIND-1", system="jira") == {str(requirement)}
    assert found(key="FIND-1", artefact_type=PAIN) == {str(pain)}
    assert found(key="FIND-1", system="nope") == set()
    body = world.client.get(url, params={"key": "FIND-1", "system": jira}, headers=auth_headers(world.token)).json()
    [record] = body["records"]
    assert record["artefact_type"] == REQ and record["reference"]["key"] == "FIND-1" and body["truncated"] is False
    assert world.client.get(url, params={"key": "  "}, headers=auth_headers(world.token)).status_code == 422
    assert world.client.get(url, params={"key": "x", "artefact_type": "nonsense"}, headers=auth_headers(world.token)).status_code == 404


def test_a_record_the_caller_cannot_open_is_omitted_from_the_look_up(world):
    project, hidden_project = world.project("Open"), world.project("Closed")
    visible, hidden = world.pain_point(project, "Visible"), world.pain_point(hidden_project, "Hidden")
    _ref(world, project, (PAIN, visible), "Jira", "SEE-1")
    _ref(world, hidden_project, (PAIN, hidden), "Jira", "SEE-1")
    member = _member_token(world, project)
    resp = world.client.get(
        f"{_base(project)}/records/by-external-reference", params={"key": "SEE-1"}, headers=auth_headers(member),
    )
    assert resp.status_code == 200, resp.text
    assert [r["id"] for r in resp.json()["records"]] == [str(visible)]


# --- project bundle -------------------------------------------------------------------------------------------------


def _round_trip(world: World, project: dict, name: str) -> dict:
    exported = world.client.get(f"{_base(project)}/export", headers=auth_headers(world.token))
    assert exported.status_code == 200, exported.text
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": name},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(world.token),
    )
    assert imported.status_code == 201, imported.text
    return imported.json()["project"]


def _only_id(world: World, project: dict, path: str) -> str:
    rows = world.client.get(f"{_base(project)}/{path}", headers=auth_headers(world.token)).json()
    assert len(rows) == 1, rows
    return rows[0]["id"]


def test_a_bundle_carries_references_for_core_and_module_types(world):
    project = world.project("Source")
    own = world.client.post(f"{_base(project)}/external-systems", json={"name": "Customer register"}, headers=auth_headers(world.token))
    assert own.status_code == 201, own.text
    requirement, pain, decision = world.requirement(project), world.pain_point(project), world.decision(project)
    cr = uuid.UUID(world.client.post(
        f"{_base(project)}/change-requests", json={"kind": "new_requirement", "proposed_name": "Wider doors", "reason": "needed"},
        headers=auth_headers(world.token),
    ).json()["id"])
    records = ((REQ, requirement), (PAIN, pain), ("decision", decision), ("change_request", cr))
    for record in records:
        _ref(world, project, record, "Jira", f"B-{record[0][:3]}", url="https://t.example/x", note="kept", role="delivery")
        _ref(world, project, record, "Customer register", "C-9")

    copy = _round_trip(world, project, "Copy")

    new_ids = {
        REQ: _only_id(world, copy, "requirements"), PAIN: _only_id(world, copy, "modules/context_strategy/pain-points"),
        "decision": _only_id(world, copy, "modules/decisions"),
        "change_request": _only_id(world, copy, "change-requests"),
    }
    for artefact_type, record_id in new_ids.items():
        body = world.client.get(_refs_url(copy, (artefact_type, uuid.UUID(record_id))), headers=auth_headers(world.token)).json()
        got = {(r["system_name"], r["key"]): r for r in body["references"]}
        assert set(got) == {("Jira", f"B-{artefact_type[:3]}"), ("Customer register", "C-9")}, artefact_type
        jira = got[("Jira", f"B-{artefact_type[:3]}")]
        assert (jira["url"], jira["note"], jira["role"]) == ("https://t.example/x", "kept", "delivery"), artefact_type
        assert str(copy["id"]) != str(project["id"]) and body["can_edit"] is True


def test_every_module_that_bundles_tags_bundles_references():
    """A record type that travels in a bundle with its tags must travel with its references: the calls sit side by
    side wherever a bundle row is written or read (Product Feedback writes its own list through the same service)."""
    root = Path(__file__).resolve().parent.parent / "app"
    gaps = []
    for path in root.rglob("*.py"):
        if "/tests/" in str(path) or path.name in {"tags.py", "placements.py", "external_references.py"}:
            continue
        text = path.read_text()
        for tags_call, reference_calls in (
            ("restore_record_tags(", ("restore_record_references(", "import_record_references(")),
            ("record_tag_names(", ("record_references(", "import_record_references(")),
        ):
            tags_n = len(re.findall(rf"(?<![\w.]){re.escape(tags_call)}", text))
            references_n = sum(len(re.findall(rf"(?<![\w.]){re.escape(c)}", text)) for c in reference_calls)
            if references_n < tags_n and "triage" not in path.name:
                gaps.append(f"{path.relative_to(root)}: {tags_call} x{tags_n} but {reference_calls} x{references_n}")
    assert not gaps, gaps


# --- scaling -------------------------------------------------------------------------------------------------------


def test_referenced_records_do_not_add_statements_to_the_list_export_or_bundle(world):
    """References are read for a whole page at once, so the statements behind a list, its export and the project
    bundle stay the same however many records carry references."""
    from tests.test_scaling_shapes import _Statements

    project = world.project()
    paths = {
        "list": f"{_base(project)}/modules/context_strategy/pain-points",
        "filtered list": f"{_base(project)}/modules/context_strategy/pain-points?external_system=Jira",
        "export": f"{_base(project)}/records/{PAIN}/export",
        "page": f"{_base(project)}/external-references/{PAIN}",
        "bundle": f"{_base(project)}/export",
    }
    ids: list[str] = []

    def measure() -> dict[str, int]:
        found = {}
        for name, path in paths.items():
            params = {"id": ids[:50]} if name == "page" else None
            assert world.client.get(path, params=params, headers=auth_headers(world.token)).status_code == 200
            with _Statements() as statements:
                assert world.client.get(path, params=params, headers=auth_headers(world.token)).status_code == 200
            found[name] = statements.count
        return found

    def add(count: int) -> None:
        for i in range(count):
            pain = world.pain_point(project, f"Pain {uuid.uuid4().hex[:6]}-{i}")
            ids.append(str(pain))
            _ref(world, project, (PAIN, pain), "Jira", f"S-{i}-{uuid.uuid4().hex[:4]}")
            _ref(world, project, (PAIN, pain), "GitHub", f"G-{i}")

    add(2)
    small = measure()
    add(8)
    assert measure() == small
