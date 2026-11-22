"""
Pictures inside a record's Markdown text (`![alt](attachment:<file id>)`): the reader and its limits, the write check that a
picture is an attachment of the record that holds it (a Decision for a record with its own id, a Requirement for a
versioned one), the project bundle round trip (a picture follows its file to the copy), and the report that prints the
picture, or its alternative text when the file is confidential, another record's or not a picture. Each test builds its
own organisation, so none depends on state left by another test.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

import pytest
from PIL import Image as PilImage
from sqlalchemy import select

from app.database import SessionLocal
from app.models.file import RequirementFile
from app.models.organization import Organization
from app.models.project import Project
from app.modules.decisions.models import Decision, DecisionFile
from app.modules.decisions.tests.test_decisions_api import _base, _create_decision, _first_decision_type_id, _setup
from app.modules.registry import MarkdownField, get_markdown_fields
from app.services import markdown_images
from app.services.link_graph import ArtefactResolver
from app.services.markdown_text import (
    MAX_CAPTION_CHARS,
    MAX_IMAGES,
    MarkdownLimitError,
    check_images,
    image_references,
    plain_text,
)
from app.services.report_framework import ReportContext
from app.services.report_layout_eval import evaluate_layout
from app.services.report_model import Gap, Image, Paragraph
from tests.conftest import auth_headers, create_component_and_category, create_project
from tests.link_world import World
from tests.test_report_layout_tree import doc

FILE_A = "3f2c9a52-6c1e-4f6e-9b7a-0a1b2c3d4e5f"
FILE_B = "9d8c7b6a-5e4f-4a3b-8c2d-1e0f9a8b7c6d"


def _png() -> bytes:
    out = io.BytesIO()
    PilImage.new("RGB", (8, 6), "red").save(out, format="PNG")
    return out.getvalue()


def _picture(file_id: str, alt: str = "Plot", caption: str = "") -> str:
    return f'![{alt}](attachment:{file_id}{f" {chr(34)}{caption}{chr(34)}" if caption else ""})'


# --- The reader and its limits ---------------------------------------------------------------------------------------


def test_a_picture_is_read_with_its_alternative_text_and_caption():
    refs = image_references(f"Before\n\n{_picture(FILE_A, 'A plot', 'Figure one')}\n\nAfter")

    assert [(str(r.file_id), r.alt, r.caption) for r in refs] == [(FILE_A, "A plot", "Figure one")]


def test_only_an_attachment_picture_is_a_reference():
    text = f"![x](https://example.com/a.png) ![y](attachment:not-a-file) ![z](attachment:{FILE_A.upper()}) [l](attachment:{FILE_A})"

    assert image_references(text) == []  # an outside address, a bad id, a non-canonical id and a link are not pictures


def test_a_picture_shows_its_alternative_text_where_only_words_are_shown():
    assert plain_text(f"See {_picture(FILE_A, 'the plot')} here") == "See the plot here"


def test_a_field_that_may_not_hold_pictures_refuses_one():
    with pytest.raises(MarkdownLimitError, match="cannot hold pictures"):
        check_images(_picture(FILE_A), allowed=False, field="Body")
    assert check_images("No pictures here", allowed=False) == []


def test_pictures_are_counted_and_a_picture_must_name_a_file_and_a_caption_stays_short():
    with pytest.raises(MarkdownLimitError, match="more than"):
        check_images("\n\n".join(_picture(str(uuid.uuid4())) for _ in range(MAX_IMAGES + 1)), allowed=True)
    with pytest.raises(MarkdownLimitError, match="does not name an attachment"):
        check_images("![x](attachment:nope)", allowed=True)
    with pytest.raises(MarkdownLimitError, match="caption"):
        check_images(_picture(FILE_A, caption="c" * (MAX_CAPTION_CHARS + 1)), allowed=True)
    assert len(check_images(_picture(FILE_A, caption="c" * MAX_CAPTION_CHARS), allowed=True)) == 1


def test_every_declared_picture_field_names_a_type_with_an_attachment_table():
    from app.modules.registry import get_record_attachment_providers

    providers = get_record_attachment_providers()
    declared: list[MarkdownField] = [f for f in get_markdown_fields() if f.images is not None]

    assert declared
    for declaration in declared:
        assert declaration.images is not None
        assert declaration.images.artefact_type in providers, declaration.column
        if declaration.images.resolve is None:
            assert declaration.images.record_id.class_ is declaration.column.class_


# --- The write check: a picture is an attachment of its own record ---------------------------------------------------


def _decision_world(client, admin_token, name: str):
    _org, project, token = _setup(client, admin_token, name)
    return project, token, _first_decision_type_id(client, token, project["id"])


def _attach(client, token, project: dict, decision: dict, filename: str = "plot.png") -> str:
    resp = client.post(
        f"{_base(project['id'])}/{decision['id']}/files", files={"file": (filename, _png(), "image/png")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _put(client, token, project: dict, decision: dict, **changes):
    return client.put(f"{_base(project['id'])}/{decision['id']}", json={**decision, **changes}, headers=auth_headers(token))


def test_a_decision_holds_a_picture_that_is_its_own_attachment(client, admin_token):
    project, token, type_id = _decision_world(client, admin_token, "Pictures Own Co")
    decision = _create_decision(client, token, project["id"], type_id)
    file_id = _attach(client, token, project, decision)
    text = f"As drawn:\n\n{_picture(file_id, 'The plot', 'Figure 1')}\n"

    saved = _put(client, token, project, decision, rationale=text)

    assert saved.status_code == 200, saved.text
    assert saved.json()["rationale"] == text  # stored as typed, never rewritten
    assert client.get(f"{_base(project['id'])}/{decision['id']}", headers=auth_headers(token)).json()["rationale"] == text


def test_a_picture_of_another_records_file_or_an_unknown_file_is_refused(client, admin_token):
    project, token, type_id = _decision_world(client, admin_token, "Pictures Other Co")
    first = _create_decision(client, token, project["id"], type_id)
    second = _create_decision(client, token, project["id"], type_id, title="Another")
    others_file = _attach(client, token, project, second)

    for reference in (others_file, str(uuid.uuid4())):
        refused = _put(client, token, project, first, rationale=_picture(reference))
        assert refused.status_code == 422, refused.text
        assert "not an attachment of this record" in refused.text


def test_a_record_that_does_not_exist_yet_holds_no_picture(client, admin_token):
    project, token, type_id = _decision_world(client, admin_token, "Pictures New Co")

    resp = client.post(
        _base(project["id"]), headers=auth_headers(token),
        json={"title": "T", "decision_statement": _picture(str(uuid.uuid4())), "decision_type_id": type_id},
    )

    assert resp.status_code == 422, resp.text


def test_a_comment_is_text_only(client, admin_token):
    project, token, type_id = _decision_world(client, admin_token, "Pictures Comment Co")
    decision = _create_decision(client, token, project["id"], type_id)
    file_id = _attach(client, token, project, decision)

    resp = client.post(
        f"{_base(project['id'])}/{decision['id']}/comments", json={"body": _picture(file_id)}, headers=auth_headers(token),
    )

    assert resp.status_code == 422 and "cannot hold pictures" in resp.text


def test_removing_a_file_does_not_block_editing_the_rest_of_the_text(client, admin_token):
    project, token, type_id = _decision_world(client, admin_token, "Pictures Removed Co")
    decision = _create_decision(client, token, project["id"], type_id)
    file_id = _attach(client, token, project, decision)
    with_picture = _put(client, token, project, decision, rationale=_picture(file_id)).json()
    assert client.delete(f"{_base(project['id'])}/{decision['id']}/files/{file_id}", headers=auth_headers(token)).status_code == 204

    kept = _put(client, token, project, with_picture, rationale=f"{_picture(file_id)}\n\nA new sentence.")
    added = _put(client, token, project, with_picture, rationale=f"{_picture(file_id)}\n\n{_picture(str(uuid.uuid4()))}")

    assert kept.status_code == 200, kept.text  # the picture was already in the text, so it is not checked again
    assert added.status_code == 422  # a new reference is checked


def test_a_requirements_picture_follows_its_attachment_through_a_new_version(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    base = f"/api/v1/projects/{project['id']}/requirements"
    h = auth_headers(admin_token)
    requirement = client.post(
        base, json={"name": "Req", "component_id": component_id, "category_id": category_id}, headers=h,
    ).json()
    file_id = client.post(
        f"{base}/{requirement['id']}/files", files={"file": ("p.png", _png(), "image/png")}, headers=h,
    ).json()["id"]

    def edit(description: str):
        return client.put(
            f"{base}/{requirement['id']}", headers=h,
            json={
                "name": "Req", "component_id": component_id, "category_id": category_id, "owner": requirement["owner"],
                "description": description,
            },
        )

    first = edit(_picture(file_id))
    second = edit(f"{_picture(file_id)}\n\nMore.")
    refused = edit(_picture(str(uuid.uuid4())))

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert refused.status_code == 422, refused.text
    db = SessionLocal()
    try:
        assert db.scalar(select(RequirementFile).where(RequirementFile.requirement_id == uuid.UUID(requirement["id"]))) is not None
    finally:
        db.close()


def test_a_change_request_proposes_text_with_the_requirements_own_pictures(client, admin_token):
    world = World(client, admin_token, "Pictures CR Org")
    project = world.project("CR Pictures P")
    requirement = world.requirement(project, "Target")
    base = f"/api/v1/projects/{project['id']}"
    h = auth_headers(world.token)
    file_id = client.post(
        f"{base}/requirements/{requirement}/files", files={"file": ("p.png", _png(), "image/png")}, headers=h,
    ).json()["id"]
    assert client.post(f"{base}/requirements/{requirement}/approve", headers=h).status_code == 200

    def propose(description: str):
        return client.post(
            f"{base}/change-requests", headers=h,
            json={
                "kind": "modify_requirement", "requirement_id": str(requirement), "changed_fields": ["description"],
                "proposed_description": description, "reason": "clearer",
            },
        )

    refused = propose(_picture(str(uuid.uuid4())))
    created = propose(f"With a figure.\n\n{_picture(file_id, 'Plot')}")

    assert refused.status_code == 422, refused.text
    assert created.status_code == 201, created.text
    cr_id = created.json()["id"]
    assert client.post(f"{base}/change-requests/{cr_id}/submit", headers=h).status_code == 200
    decided = client.post(f"{base}/change-requests/{cr_id}/decide", json={"approve": True, "note": ""}, headers=h)
    assert decided.status_code == 200, decided.text  # the approved text is written to the requirement, picture and all
    current = client.get(f"{base}/requirements/{requirement}", headers=h).json()
    assert _picture(file_id, "Plot") in current["description"]


# --- The project bundle ---------------------------------------------------------------------------------------------


def _import(client, token, org_id, bundle: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_picture_follows_its_file_into_an_imported_copy(client, admin_token):
    org, project, token = _setup(client, admin_token, "Pictures Bundle Co")
    type_id = _first_decision_type_id(client, token, project["id"])
    decision = _create_decision(client, token, project["id"], type_id)
    file_id = _attach(client, token, project, decision)
    other = _attach(client, token, project, decision, "spare.png")
    _put(client, token, project, decision, rationale=f"{_picture(file_id, 'Plot', 'Fig')}\n\n{_picture(other, 'Spare')}")
    bundle = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token)).content

    imported = _import(client, token, org["id"], bundle, "Pictures Bundle Copy")

    assert imported["warnings"] == []
    db = SessionLocal()
    try:
        copy = db.scalars(select(Decision).where(Decision.project_id == uuid.UUID(imported["project"]["id"]))).one()
        attached = {str(row.file_id) for row in db.scalars(select(DecisionFile).where(DecisionFile.decision_id == copy.id))}
        references = image_references(copy.rationale or "")
        assert [(r.alt, r.caption) for r in references] == [("Plot", "Fig"), ("Spare", "")]
        assert {str(r.file_id) for r in references} == attached  # every picture names a file of the copy, none of the source
        assert not ({str(r.file_id) for r in references} & {file_id, other})
    finally:
        db.close()


def test_an_imported_picture_whose_file_did_not_arrive_becomes_its_alternative_text(client, admin_token):
    org, project, token = _setup(client, admin_token, "Pictures Missing Co")
    type_id = _first_decision_type_id(client, token, project["id"])
    decision = _create_decision(client, token, project["id"], type_id)
    file_id = _attach(client, token, project, decision)
    _put(client, token, project, decision, rationale=f"Look:\n\n{_picture(file_id, 'The plot')}")
    bundle = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token)).content
    stripped = _without_files(bundle)

    imported = _import(client, token, org["id"], stripped, "Pictures Missing Copy")

    db = SessionLocal()
    try:
        copy = db.scalars(select(Decision).where(Decision.project_id == uuid.UUID(imported["project"]["id"]))).one()
        assert copy.rationale == "Look:\n\nThe plot"
    finally:
        db.close()


def _without_files(bundle: bytes) -> bytes:
    """The bundle with every embedded file's bytes removed (the entries stay, as in a bundle whose files were stripped)."""
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle)) as source, zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            if item.filename.startswith("files/"):
                continue
            target.writestr(item, source.read(item.filename))
    return out.getvalue()


def test_the_import_rewrite_is_exact():
    old, new = uuid.UUID(FILE_A), uuid.UUID(FILE_B)
    text = f"{_picture(FILE_A, 'Plot', 'Cap')} and {_picture(FILE_B, 'Keep')}"

    assert markdown_images._replace_picture(text, old, new) == f"{_picture(FILE_B, 'Plot', 'Cap')} and {_picture(FILE_B, 'Keep')}"
    assert markdown_images._replace_picture(text, old, None) == f"Plot and {_picture(FILE_B, 'Keep')}"


# --- The report ------------------------------------------------------------------------------------------------------


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Pictures Report Org", decisions=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def _run(db, world: World, project: dict):
    row = db.get(Project, uuid.UUID(project["id"]))
    org = db.get(Organization, uuid.UUID(world.org["id"]))
    resolver = ArtefactResolver(db, row, world.user_id, include_related=True)
    ctx = ReportContext(module_key="reporting", organization=org, projects=[row], root_project=row)
    tree = doc({
        "type": "each", "source": {"record_type": "decision"}, "children": [{"type": "text", "text": "{{record.rationale}}"}],
    })
    return evaluate_layout(db, resolver, ctx, tree, title="Report")


def _decision_with_files(world: World, project: dict, *, confidential: bool = False, filename: str = "plot.png", data: bytes | None = None):
    """A Decision with one attachment and a rationale that is only that picture; returns the file id."""
    from app.services.files import upload_file

    decision_id = world.decision(project)
    session = SessionLocal()
    try:
        asset = upload_file(
            session, organization_id=uuid.UUID(world.org["id"]), uploaded_by=world.user_id, filename=filename,
            content_type="image/png", data=data if data is not None else _png(),
        )
        asset.confidential = confidential
        session.flush()
        session.add(DecisionFile(decision_id=decision_id, file_id=asset.id, linked_by=world.user_id, created_at=datetime.now(UTC)))
        session.flush()
        record = session.get(Decision, decision_id)
        assert record is not None
        record.rationale = f"Evidence:\n\n{_picture(str(asset.id), 'A red square', 'Figure 1')}"
        session.commit()
        return asset.id
    finally:
        session.close()


def test_a_report_prints_the_picture_with_its_caption(world, db):
    project = world.project("Report Pictures P")
    _decision_with_files(world, project)

    found = [b for b in _run(db, world, project).document.blocks if not isinstance(b, Gap)]

    pictures = [b for b in found if isinstance(b, Image)]
    assert len(pictures) == 1
    assert pictures[0].data and pictures[0].alt == "A red square" and pictures[0].caption == "Figure 1"
    assert [b.text for b in found if isinstance(b, Paragraph)] == ["Evidence:"]


def test_a_confidential_picture_prints_as_its_alternative_text(world, db):
    project = world.project("Report Confidential P")
    _decision_with_files(world, project, confidential=True)

    result = _run(db, world, project)
    found = [b for b in result.document.blocks if not isinstance(b, Gap)]

    assert not [b for b in found if isinstance(b, Image)]
    assert [b.text for b in found if isinstance(b, Paragraph)] == ["Evidence:", "A red square"]


def test_a_file_that_is_not_a_picture_prints_as_its_alternative_text_with_a_warning(world, db):
    project = world.project("Report Not Picture P")
    _decision_with_files(world, project, filename="notes.png", data=b"this is not a picture")

    result = _run(db, world, project)
    found = [b for b in result.document.blocks if not isinstance(b, Gap)]

    assert not [b for b in found if isinstance(b, Image)]
    assert [b.text for b in found if isinstance(b, Paragraph)] == ["Evidence:", "A red square"]
    assert any("picture attached to a record" in warning for warning in result.warnings)
