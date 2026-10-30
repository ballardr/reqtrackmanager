"""Tests for a layout's record-images block and the confidential mark behind it: the tree check, the text view, the
wildcard matcher, the attachment registry, a run over Pain Points with name, type, count, size and order rules, the
confidential switch (who may set it, that a report never prints it) and its carriage in the project bundle.
"""

from __future__ import annotations

import io
import os
import re
import uuid
from typing import Any

import pytest
from PIL import Image as PilImage
from sqlalchemy import select

from app.database import SessionLocal
from app.models.enums import ProjectRole
from app.models.file import FileAsset
from app.models.generated_report import GeneratedReport
from app.models.project import UserProjectRole
from app.modules.registry import (
    get_all_registered_artefact_types,
    get_no_record_attachment_reasons,
    get_record_attachment_providers,
    get_report_field_providers,
)
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import InvalidLayoutError, assert_valid, empty_tree
from app.services.report_record_images import (
    candidate_files,
    compile_pattern,
    extension_of,
    wildcard_match,
)
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World


def png(colour: str = "red", size: tuple[int, int] = (60, 30)) -> bytes:
    out = io.BytesIO()
    PilImage.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


def noise(side: int = 400) -> bytes:
    """A picture that does not compress, so its file size is large (about `side` squared times three bytes)."""
    out = io.BytesIO()
    PilImage.frombytes("RGB", (side, side), os.urandom(side * side * 3)).save(out, "PNG")
    return out.getvalue()


def each_pain_point(**keys: Any) -> dict[str, Any]:
    """A layout printing, for each Pain Point, its pictures by the given block settings."""
    block = {"type": "record_images", **keys}
    return {
        **empty_tree("document"),
        "nodes": [{"type": "each", "source": {"record_type": "pain_point"}, "as": "pp", "children": [block]}],
    }


def errors_of(tree: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(InvalidLayoutError) as caught:
        assert_valid(tree)
    return [(e.path, e.message) for e in caught.value.errors]


# ---- the tree ---------------------------------------------------------------------------------------------------


def test_a_record_images_block_with_every_setting_is_valid():
    assert_valid(each_pain_point(
        names=["{{pp.code}}-*", "site-*"], types=["png", "JPG"], max_count=3, order="uploaded", max_size_mb=2.5,
        caption_source="text", caption="Photo of {{pp.title}}", caption_position="above", numbering="always",
        width=8, width_unit="cm", height=4, align="left", empty_text="No photos for {{pp.code}}.",
    ))
    assert_valid(each_pain_point(placement="wrap", align="right", caption_source="none"))
    assert_valid(each_pain_point())


def test_a_record_images_block_must_sit_inside_a_for_each_record_block():
    tree = {**empty_tree("document"), "nodes": [{"type": "record_images"}]}
    assert "inside a For each record block" in errors_of(tree)[0][1]


def test_a_type_whose_attachments_are_not_offered_says_why():
    tree = {
        **empty_tree("document"),
        "nodes": [{"type": "each", "source": {"record_type": "stakeholder"}, "children": [{"type": "record_images"}]}],
    }
    path, message = errors_of(tree)[0]
    assert path == "nodes[0].children[0]" and "identifiable person" in message


@pytest.mark.parametrize(
    ("keys", "path"),
    [
        ({"names": "site-*"}, "names"),
        ({"names": ["a"] * 11}, "names"),
        ({"names": ["a*b*c*d*e*f"]}, "names[0]"),
        ({"names": ["{{pp.nothing}}-*"]}, "names[0]"),
        ({"names": [""]}, "names[0]"),
        ({"names": ["x" * 201]}, "names[0]"),
        ({"types": ["pdf"]}, "types[0]"),
        ({"types": ["exe"]}, "types[0]"),
        ({"max_count": 0}, "max_count"),
        ({"max_count": 21}, "max_count"),
        ({"max_count": True}, "max_count"),
        ({"order": "random"}, "order"),
        ({"max_size_mb": 0}, "max_size_mb"),
        ({"max_size_mb": 51}, "max_size_mb"),
        ({"caption_source": "title"}, "caption_source"),
        ({"caption_source": "text"}, "caption"),
        ({"caption": "stray"}, "caption"),
        ({"caption_source": "none", "numbering": "auto"}, "numbering"),
        ({"placement": "behind"}, "placement"),
        ({"placement": "wrap", "caption_source": "none"}, "align"),
        ({"placement": "wrap", "align": "left"}, "caption_source"),
        ({"width": 500}, "width"),
        ({"anchor": "page"}, "anchor"),
        ({"file": "x"}, "file"),
        ({"empty_text": "{{nope.code}}"}, "empty_text"),
    ],
)
def test_a_bad_record_images_setting_is_refused_with_its_path(keys, path):
    assert f"nodes[0].children[0].{path}" in [p for p, _ in errors_of(each_pain_point(**keys))]


def test_a_record_images_block_is_a_document_block_only():
    tree = {**empty_tree("table"), "nodes": [{"type": "record_images"}]}
    assert "cannot be used in a table layout" in errors_of(tree)[0][1]


# ---- the text view ----------------------------------------------------------------------------------------------


def test_the_text_view_round_trips_every_setting_and_leaves_absent_ones_absent():
    tree = {**empty_tree("document"), "nodes": [{"type": "each", "source": {"record_type": "pain_point"}, "as": "pp", "children": [
        {"type": "record_images", "names": ["{{pp.code}}-*", "site *"], "types": ["png", "jpg"], "max_count": 3, "order": "uploaded",
         "max_size_mb": 2.5, "caption_source": "text", "caption": "Photo of {{pp.title}}", "caption_position": "above",
         "numbering": "always", "width": 8, "width_unit": "cm", "height": 40, "height_unit": "mm", "align": "left",
         "placement": "inline", "empty_text": "None."},
        {"type": "record_images", "placement": "wrap", "align": "right", "caption_source": "none"},
        {"type": "record_images"},
    ]}]}
    text = format_tree(tree)
    parsed = parse_text(text)
    assert parsed.ok, parsed.errors
    assert parsed.tree == tree
    assert format_tree(parsed.tree) == text


@pytest.mark.parametrize(
    ("line", "fragment"),
    [
        ("@record_images colour red", "Unexpected"),
        ("@record_images names", "Expected a file name pattern"),
        ("@record_images max_count three", "Expected the max count"),
        ("@record_images order name order name", "written once"),
        ("@record_images types png,", "Expected a file type"),
    ],
)
def test_a_mistake_in_a_record_images_line_is_a_positioned_error(line, fragment):
    parsed = parse_text(f"@layout document\n@each pain_point as pp\n  {line}\n@end\n")
    assert not parsed.ok and fragment in parsed.errors[0].message and parsed.errors[0].line == 3


# ---- the matcher ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "name", "expected"),
    [
        ("photo.png", "PHOTO.PNG", True),
        ("photo.png", "photo.jpg", False),
        ("site-*", "Site-12.png", True),
        ("site-*", "my-site-12.png", False),
        ("*.png", "a.b.png", True),
        ("*", "", True),
        ("?", "", False),
        ("a?c", "abc", True),
        ("a?c", "ac", False),
        ("a*b*c", "aXXbYYc", True),
        ("a*b*c", "aXXbYY", False),
        ("**x", "abx", True),
        ("*a", "banana", True),
        ("*ab*ab*ab", "ababab", True),
        ("*ab*ab*ab", "abab", False),
    ],
)
def test_the_matcher_handles_exact_names_and_wildcards_case_insensitively(pattern, name, expected):
    assert wildcard_match(compile_pattern(pattern), name) is expected


def test_a_filled_in_value_is_matched_as_plain_text_never_as_a_wildcard_or_path():
    hostile = "*"
    tokens = compile_pattern("{{rec.title}}-*", lambda text: text.replace("{{rec.title}}", hostile))
    assert wildcard_match(tokens, "*-1.png") and not wildcard_match(tokens, "anything-1.png")
    assert not wildcard_match(compile_pattern("{{v}}", lambda t: "../x"), "x")
    assert wildcard_match(compile_pattern("{{v}}", lambda t: "../x"), "../x")
    assert not wildcard_match(compile_pattern("{{v}}.png", lambda t: "?"), "a.png")


def test_a_hostile_pattern_is_not_slow():
    tokens = compile_pattern("*a*a*a*a")
    assert wildcard_match(tokens, "a" * 200 + "b") is False


def test_an_extension_is_lower_case_without_its_dot():
    assert extension_of("Photo.JPG") == "jpg" and extension_of("archive.tar.gz") == "gz"
    assert extension_of("noextension") == "" and extension_of(".hidden") == ""


class _File:
    def __init__(self, filename: str, size: int = 10, created: int = 0) -> None:
        self.id = uuid.uuid4()
        self.filename = filename
        self.size_bytes = size
        self.created_at = created


def test_candidates_are_filtered_by_name_type_and_size_then_ordered():
    files = [_File("b.png", created=3), _File("A.jpg", created=1), _File("c.pdf", created=2), _File("d.png", size=5_000_000, created=0)]
    names = [f.filename for f in candidate_files(files, patterns=[], extensions=[], order="name", max_bytes=None)]
    assert names == ["A.jpg", "b.png", "d.png"]
    by_upload = candidate_files(files, patterns=[], extensions=[], order="uploaded", max_bytes=None)
    assert [f.filename for f in by_upload] == ["d.png", "A.jpg", "b.png"]
    small_pngs = candidate_files(files, patterns=[compile_pattern("*.png")], extensions=["PNG"], order="name", max_bytes=1000)
    assert [f.filename for f in small_pngs] == ["b.png"]


# ---- the registry -----------------------------------------------------------------------------------------------


def test_every_reportable_type_offers_its_attachments_or_says_why_not():
    offered, reasons = get_record_attachment_providers(), get_no_record_attachment_reasons()
    for artefact_type in get_report_field_providers():
        assert artefact_type in offered or reasons.get(artefact_type), f"{artefact_type} has neither attachments nor a reason"
        assert not (artefact_type in offered and artefact_type in reasons), f"{artefact_type} is both"
    assert (set(offered) | set(reasons)) <= get_all_registered_artefact_types()


def test_every_attachment_provider_names_a_link_table_with_a_file_column():
    for artefact_type, provider in get_record_attachment_providers().items():
        assert hasattr(provider.link, "file_id"), artefact_type
        assert provider.record_column.table is provider.link.__table__, artefact_type


# ---- a run ------------------------------------------------------------------------------------------------------


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Record Images Org", context_strategy=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def attach(world: World, project: dict, pain_point: uuid.UUID, name: str, data: bytes, token: str | None = None) -> dict:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/modules/context_strategy/pain-points/{pain_point}/files",
        files={"file": (name, data, "application/octet-stream")}, headers=auth_headers(token or world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def mark_confidential(world: World, file_id: str, value: bool = True, token: str | None = None):
    return world.client.patch(
        f"/api/v1/files/{file_id}/confidential", json={"confidential": value}, headers=auth_headers(token or world.token),
    )


def preview(world: World, project: dict, tree: dict) -> dict:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts/preview", json={"tree": tree}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def captions(result: dict) -> list[str]:
    return re.findall(r"<figcaption>(.*?)</figcaption>", result["html"])


def photographed(world: World) -> tuple[dict, uuid.UUID]:
    """A project whose one Pain Point has attachments of every awkward kind."""
    project = world.project("Alpha")
    pain_point = world.pain_point(project)
    attach(world, project, pain_point, "site-photo-2.png", png("green"))
    attach(world, project, pain_point, "Site-Photo-1.PNG", png("red"))
    attach(world, project, pain_point, "overview.png", png("blue"))
    attach(world, project, pain_point, "notes.txt", b"not a picture")
    attach(world, project, pain_point, "site-fake.png", b"this is text pretending to be a picture")
    return project, pain_point


def test_a_run_prints_only_the_pictures_matching_the_name_rule_in_name_order(world):
    project, _ = photographed(world)
    result = preview(world, project, each_pain_point(names=["site-*"]))
    assert result["html"].count("<img") == 2
    assert captions(result) == ["Figure 1: Site-Photo-1.PNG", "Figure 2: site-photo-2.png"]
    assert any("is not a picture a report can print" in w for w in result["warnings"])


def test_no_name_rule_prints_every_real_picture_and_never_a_text_file(world):
    project, _ = photographed(world)
    result = preview(world, project, each_pain_point(caption_source="none"))
    assert result["html"].count("<img") == 3 and "<figcaption>" not in result["html"]


def test_a_type_rule_limits_the_extensions(world):
    project, _ = photographed(world)
    assert preview(world, project, each_pain_point(types=["svg"]))["html"].count("<img") == 0
    assert preview(world, project, each_pain_point(types=["png"], names=["overview*"]))["html"].count("<img") == 1


def test_the_count_applies_to_real_pictures_so_a_fake_one_does_not_use_a_place(world):
    project, _ = photographed(world)
    result = preview(world, project, each_pain_point(names=["site-*"], max_count=2, order="name"))
    assert result["html"].count("<img") == 2


def test_the_most_per_record_rule_cuts_the_list_after_ordering(world):
    project, _ = photographed(world)
    result = preview(world, project, each_pain_point(max_count=1, caption_source="file_name", numbering="never"))
    assert captions(result) == ["overview.png"]


def test_the_order_can_be_upload_time(world):
    project, _ = photographed(world)
    result = preview(world, project, each_pain_point(order="uploaded", numbering="never", names=["*.png"], max_count=20))
    assert captions(result)[:2] == ["site-photo-2.png", "Site-Photo-1.PNG"]


def test_a_size_ceiling_skips_a_bigger_file(world):
    project = world.project("Alpha")
    pain_point = world.pain_point(project)
    attach(world, project, pain_point, "small.png", png(size=(10, 10)))
    attach(world, project, pain_point, "big.png", noise())
    assert len(noise()) > 0.2 * 1024 * 1024
    result = preview(world, project, each_pain_point(max_size_mb=0.2, numbering="never"))
    assert "big.png" not in result["html"] and result["html"].count("<img") == 1


def test_a_name_rule_can_use_the_records_own_code(world):
    project = world.project("Alpha")
    first = world.pain_point(project, "First")
    second = world.pain_point(project, "Second")
    base = f"/api/v1/projects/{project['id']}/modules/context_strategy/pain-points"
    code_of = {
        pp: world.client.get(f"{base}/{pp}", headers=auth_headers(world.token)).json()["unique_code"] for pp in (first, second)
    }
    attach(world, project, first, f"{code_of[first]}-front.png", png())
    attach(world, project, first, f"{code_of[second]}-front.png", png("green"))
    attach(world, project, second, f"{code_of[second]}-side.png", png("blue"))
    result = preview(world, project, each_pain_point(names=["{{pp.code}}-*"], numbering="never"))
    assert sorted(captions(result)) == sorted([f"{code_of[first]}-front.png", f"{code_of[second]}-side.png"])


def test_a_caption_can_be_fixed_text_with_the_records_values(world):
    project, _ = photographed(world)
    result = preview(world, project, each_pain_point(
        names=["overview*"], caption_source="text", caption="Photo of {{pp.title}}", numbering="never",
    ))
    assert captions(result) == ["Photo of Slow reports"]


def test_a_record_with_no_matching_picture_prints_the_empty_text_or_nothing(world):
    project, _ = photographed(world)
    nothing = preview(world, project, each_pain_point(names=["zzz*"]))
    assert "<img" not in nothing["html"] and "No photos" not in nothing["html"]
    said = preview(world, project, each_pain_point(names=["zzz*"], empty_text="No photos for {{pp.title}}."))
    assert "No photos for Slow reports." in said["html"]


def test_the_picture_a_run_embeds_has_no_metadata_and_keeps_its_size_settings(world):
    project, _ = photographed(world)
    result = preview(world, project, each_pain_point(names=["overview*"], width=5, width_unit="cm"))
    assert "5cm" in result["html"] or "5.0cm" in result["html"] or "width" in result["html"]


# ---- the confidential mark --------------------------------------------------------------------------------------


def test_a_confidential_file_is_never_printed_whatever_the_rules_match(world):
    project, pain_point = photographed(world)
    secret = attach(world, project, pain_point, "site-secret.png", png("black"))
    before = preview(world, project, each_pain_point(names=["site-*"]))
    assert before["html"].count("<img") == 3
    resp = mark_confidential(world, secret["id"])
    assert resp.status_code == 200 and resp.json()["confidential"] is True
    after = preview(world, project, each_pain_point(names=["site-*"]))
    assert after["html"].count("<img") == 2 and "site-secret" not in after["html"]
    assert mark_confidential(world, secret["id"], False).json()["confidential"] is False
    assert preview(world, project, each_pain_point(names=["site-*"]))["html"].count("<img") == 3


def test_a_file_defaults_to_not_confidential_and_the_listing_says_so(world):
    project = world.project("Alpha")
    pain_point = world.pain_point(project)
    created = attach(world, project, pain_point, "a.png", png())
    assert created["confidential"] is False
    listed = world.client.get(
        f"/api/v1/projects/{project['id']}/modules/context_strategy/pain-points/{pain_point}/files", headers=auth_headers(world.token),
    ).json()
    assert [f["confidential"] for f in listed] == [False]


def test_a_confidential_file_stays_downloadable_by_those_who_could_open_it_before(world):
    project = world.project("Alpha")
    pain_point = world.pain_point(project)
    created = attach(world, project, pain_point, "a.png", png())
    mark_confidential(world, created["id"])
    assert world.client.get(f"/api/v1/files/{created['id']}", headers=auth_headers(world.token)).status_code == 200


def test_the_mark_is_audited_without_the_file_name(world, db):
    from app.models.audit import AuditEvent

    project = world.project("Alpha")
    pain_point = world.pain_point(project)
    created = attach(world, project, pain_point, "private-name.png", png())
    mark_confidential(world, created["id"])
    mark_confidential(world, created["id"])  # unchanged: no second event
    mark_confidential(world, created["id"], False)
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.entity_type == "file", AuditEvent.entity_id == created["id"]).order_by(AuditEvent.created_at)
    ).all()
    assert [e.action for e in events] == ["confidential_set", "confidential_cleared"]
    assert all("private-name" not in str(e.detail) for e in events)


def test_a_stranger_or_anonymous_caller_cannot_change_the_mark(client, admin_token, world):
    project = world.project("Alpha")
    pain_point = world.pain_point(project)
    created = attach(world, project, pain_point, "a.png", png())
    other = World(client, admin_token, "Other Org")
    assert mark_confidential(world, created["id"], token=other.token).status_code == 403
    assert client.patch(f"/api/v1/files/{created['id']}/confidential", json={"confidential": True}).status_code == 401
    assert mark_confidential(world, str(uuid.uuid4())).status_code == 404
    with SessionLocal() as db:
        assert db.get(FileAsset, uuid.UUID(created["id"])).confidential is False


def test_a_plain_member_who_did_not_upload_the_file_cannot_change_the_mark(client, world):
    project = world.project("Alpha")
    pain_point = world.pain_point(project)
    created = attach(world, project, pain_point, "a.png", png())
    email = f"member-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(client, world.token, world.org["id"], email)
    with SessionLocal() as session:
        session.add(UserProjectRole(user_id=uuid.UUID(user_id), project_id=uuid.UUID(project["id"]), role=ProjectRole.MEMBER))
        session.commit()
    token = login(client, email, "Password123!")
    assert client.get(f"/api/v1/files/{created['id']}", headers=auth_headers(token)).status_code == 200
    assert mark_confidential(world, created["id"], token=token).status_code == 403


def test_the_run_counts_record_pictures_and_digests_their_ids_never_bytes(world, db):
    project, _ = photographed(world)
    h = auth_headers(world.token)
    created = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts",
        json={"name": "Prov", "description": "d", "family": "document", "tree": each_pain_point(names=["site-*"])}, headers=h,
    ).json()
    run = world.client.get(f"/api/v1/projects/{project['id']}/custom-reports/{created['id']}/run", headers=h)
    assert run.status_code == 200, run.text
    row = db.scalars(select(GeneratedReport).where(GeneratedReport.layout_id == uuid.UUID(created["id"]))).one()
    assert row.stats["record_images"] == 2 and re.fullmatch(r"[0-9a-f]{64}", row.stats["record_images_digest"])
    assert "image" not in str(row.stats.get("record_image_files", ""))


# ---- the formats ------------------------------------------------------------------------------------------------


def test_every_download_format_embeds_the_record_pictures(world):
    project, _ = photographed(world)
    h = auth_headers(world.token)
    created = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts",
        json={"name": "Formats", "description": "d", "family": "document", "tree": each_pain_point(names=["overview*"])}, headers=h,
    ).json()
    sizes = {}
    for fmt in ("pdf", "docx", "odt", "html"):
        resp = world.client.get(
            f"/api/v1/projects/{project['id']}/custom-reports/{created['id']}/run", params={"format": fmt}, headers=h,
        )
        assert resp.status_code == 200, (fmt, resp.text)
        sizes[fmt] = len(resp.content)
    assert all(size > 0 for size in sizes.values())
    docx = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{created['id']}/run", params={"format": "docx"}, headers=h,
    ).content
    import zipfile

    assert any(n.startswith("word/media/") for n in zipfile.ZipFile(io.BytesIO(docx)).namelist())


# ---- bundles ----------------------------------------------------------------------------------------------------


def test_a_project_bundle_carries_the_confidential_mark(world, db):
    project = world.project("Alpha")
    pain_point = world.pain_point(project)
    secret = attach(world, project, pain_point, "secret.png", png("black"))
    open_file = attach(world, project, pain_point, "open.png", png())
    mark_confidential(world, secret["id"])
    h = auth_headers(world.token)
    exported = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert exported.status_code == 200, exported.text
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Imported"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    base = f"/api/v1/projects/{new_id}/modules/context_strategy"
    new_pp = world.client.get(f"{base}/pain-points", headers=h).json()
    new_pp = new_pp["items"] if isinstance(new_pp, dict) else new_pp
    files = world.client.get(f"{base}/pain-points/{new_pp[0]['id']}/files", headers=h).json()
    assert {f["filename"]: f["confidential"] for f in files} == {"secret.png": True, "open.png": False}
    assert open_file["confidential"] is False
