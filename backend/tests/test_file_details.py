"""Tests for a picture file's details (`GET /files/{id}/details`, `services.image_details`): the EXIF a photograph is
recognised by, how it is cleaned, and that the endpoint follows exactly the read rule of the download.
"""

from __future__ import annotations

import io
import uuid

import pytest
from PIL import Image as PilImage

from app.services.image_details import image_details
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="100" height="50"/></svg>'


def png(width: int = 200, height: int = 100) -> bytes:
    out = io.BytesIO()
    PilImage.new("RGB", (width, height), "red").save(out, "PNG")
    return out.getvalue()


def photo_with_exif() -> bytes:
    image = PilImage.new("RGB", (60, 30), "green")
    exif = image.getexif()
    exif[0x010F], exif[0x0110], exif[0x010E], exif[0x0112] = "Canon", "Canon EOS 5D", "North gate, pump house", 6
    exif.get_ifd(0x8769)[0x9003] = "2026:10:12 14:03:11"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "S", (33.0, 52.0, 0.0), "E", (151.0, 12.0, 36.0)
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    return out.getvalue()


def test_the_details_of_a_photograph_are_read_for_the_picker():
    details = image_details(photo_with_exif())
    assert (details.width_px, details.height_px) == (30, 60)  # as displayed, orientation applied
    assert details.taken == "2026-10-12 14:03:11" and details.camera == "Canon EOS 5D"
    assert details.description == "North gate, pump house"
    assert (details.latitude, details.longitude) == pytest.approx((-33.866667, 151.21))


def test_a_picture_with_no_metadata_and_an_svg_have_no_details_beyond_their_size():
    plain = image_details(png(20, 10))
    assert (plain.width_px, plain.height_px) == (20, 10) and plain.taken is None and plain.camera is None and plain.latitude is None
    assert image_details(b"junk") == image_details(b"")  # not a picture: empty


def test_exif_text_is_cleaned_and_cut_before_it_is_shown():
    image = PilImage.new("RGB", (4, 4))
    exif = image.getexif()
    exif[0x010E] = "bad\x00name\x1b[31m " + "x" * 500
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    description = image_details(out.getvalue()).description
    assert description is not None and "\x00" not in description and "\x1b" not in description and len(description) <= 200


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "File Details Org")


def upload_resource(world: World, data: bytes, name: str) -> str:
    resp = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/resources", files={"file": (name, data, "application/octet-stream")},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def upload_project_picture(world: World, project: dict, data: bytes, name: str) -> str:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-images", files={"file": (name, data, "application/octet-stream")},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def details(world: World, file_id: str, token: str | None = None):
    return world.client.get(f"/api/v1/files/{file_id}/details", headers=auth_headers(token) if token else {})


def test_a_member_reads_the_details_of_an_organisation_resource(world):
    file_id = upload_resource(world, photo_with_exif(), "gate.jpg")
    body = details(world, file_id, world.token).json()
    assert body["camera"] == "Canon EOS 5D" and body["taken"] == "2026-10-12 14:03:11" and body["description"] == "North gate, pump house"
    assert (body["width_px"], body["height_px"]) == (30, 60) and body["latitude"] == pytest.approx(-33.866667)


def test_a_file_that_is_not_a_raster_picture_has_empty_details(world):
    assert details(world, upload_resource(world, b"plain text, not a picture", "notes.txt"), world.token).json() == {
        "width_px": None, "height_px": None, "taken": None, "camera": None, "description": None, "latitude": None, "longitude": None,
    }


def test_an_svg_has_its_declared_size_and_no_camera_details(world):
    body = details(world, upload_resource(world, SVG.encode(), "mark.svg"), world.token).json()
    assert (body["width_px"], body["height_px"]) == (100, 50) and body["camera"] is None and body["taken"] is None


def test_the_details_need_a_signed_in_caller_and_a_real_file(world):
    file_id = upload_resource(world, png(), "p.png")
    assert details(world, file_id).status_code == 401
    assert details(world, str(uuid.uuid4()), world.token).status_code == 404


def test_the_details_follow_the_downloads_access_rule_for_a_project_file(client, world):
    project = world.project("Alpha")
    file_id = upload_project_picture(world, project, photo_with_exif(), "site.jpg")
    assert details(world, file_id, world.token).status_code == 200
    outsider = f"outsider-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(client, world.token, world.org["id"], outsider)
    token = login(client, outsider, "Password123!")
    assert client.get(f"/api/v1/files/{file_id}", headers=auth_headers(token)).status_code == 403
    assert details(world, file_id, token).status_code == 403  # no role in the project: no download, so no details


def test_a_member_of_another_organisation_cannot_read_an_organisations_resource_details(client, admin_token, world):
    file_id = upload_resource(world, photo_with_exif(), "gate.jpg")
    other = World(client, admin_token, "Other Details Org")
    assert details(world, file_id, other.token).status_code == 403
