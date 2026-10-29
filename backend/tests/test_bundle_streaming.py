"""
Pins how a project or organisation export bundle is built and sent (`services.bundle_common`).

Why: the export used to build the whole zip in memory, copy it with `getvalue()` and hold the response body beside it,
so a worker kept that memory after the request. A bundle is now written into a spooled file (a temporary file once it
is large), each JSON document is written a piece at a time, and the response streams the file in chunks and closes it.
These tests keep the zip valid and the file closed on every path, so the saving cannot cost a corrupt download or a
leaked temporary file.
"""

import json
import zipfile

import pytest

from app.services import bundle_common
from app.services.bundle_common import bundle_size, iter_bundle_file, new_bundle_file, write_json_entry


def _bundle_with(document: dict):
    bundle = new_bundle_file()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        write_json_entry(zf, "doc.json", document)
        zf.writestr("note.txt", "hello")
    return bundle


def test_a_json_entry_round_trips_and_stays_pretty_printed():
    document = {"name": "Projet été", "items": [{"id": 1, "tags": ["a", "b"]}], "none": None}
    bundle = _bundle_with(document)
    with zipfile.ZipFile(bundle) as zf:
        raw = zf.read("doc.json").decode("utf-8")
    assert json.loads(raw) == document
    assert raw.startswith("{\n  ")  # indent=2, as the bundle format has always been written


def test_the_streamed_chunks_equal_the_file_and_the_file_is_closed_at_the_end():
    bundle = _bundle_with({"k": "v" * 5000})
    size = bundle_size(bundle)
    data = b"".join(iter_bundle_file(bundle))
    assert len(data) == size and bundle.closed
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.read("note.txt") == b"hello" and json.loads(zf.read("doc.json"))["k"] == "v" * 5000


def test_the_file_is_closed_when_the_client_stops_reading(monkeypatch):
    monkeypatch.setattr(bundle_common, "BUNDLE_CHUNK_BYTES", 16)
    bundle = _bundle_with({"k": "v" * 5000})
    chunks = iter_bundle_file(bundle)
    next(chunks)
    chunks.close()  # what Starlette does when the connection drops
    assert bundle.closed


def test_a_large_bundle_spills_to_a_temporary_file_instead_of_memory(monkeypatch):
    monkeypatch.setattr(bundle_common, "BUNDLE_SPOOL_BYTES", 1024)
    bundle = new_bundle_file()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("big.bin", b"x" * 100_000)
    assert bundle._rolled
    assert bundle_size(bundle) > 100_000
    bundle.close()


def test_the_export_routes_send_a_complete_zip_with_its_length(client, admin_token):
    from tests.conftest import auth_headers, create_org_admin_in, create_project

    org, token = create_org_admin_in(client, admin_token, "Stream Co")
    project_id = create_project(client, token, org["id"], "Stream Project")["id"]
    for url in (f"/api/v1/projects/{project_id}/export", f"/api/v1/orgs/{org['id']}/export"):
        response = client.get(url, headers=auth_headers(token))
        assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
        assert int(response.headers["content-length"]) == len(response.content)
        import io

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert zf.testzip() is None and "manifest.json" in zf.namelist()


@pytest.mark.parametrize("size", [0, 1, 1024 * 1024, 1024 * 1024 + 1])
def test_chunking_handles_empty_and_boundary_sizes(size):
    bundle = new_bundle_file()
    bundle.write(b"z" * size)
    assert b"".join(iter_bundle_file(bundle)) == b"z" * size
