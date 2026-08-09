"""Tests for embedding images in generated PDF reports via
`![alt](attachment:<file id>)` references (see `services/reports.py`'s
`_markdown_to_flowables`/`_image_flowable` and
`routers/reports.py::_resolve_report_images`), including the tenant-
isolation check that stops an attachment reference from leaking a
different organisation's file into a report."""

import struct
import zlib

from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project

# No PDF-parsing dependency is added just for this check: ReportLab always
# writes `/Subtype /Image` into the PDF object stream for an embedded
# raster image, so a raw byte-string search is enough to confirm (or rule
# out) that an Image flowable actually made it into the output, without a
# new test-only library dependency.
_IMAGE_MARKER = b"/Subtype /Image"


def _tiny_png() -> bytes:
    """Builds a minimal valid, decodable 1x1 white PNG from scratch (no
    Pillow dependency needed for the test) — a fake/truncated PNG header
    alone isn't decodable by ReportLab's image loader, so a real one is
    needed to actually exercise the embed-into-PDF path."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw_scanline = b"\x00" + b"\xff\xff\xff"  # filter byte + one white RGB pixel
    idat = chunk(b"IDAT", zlib.compress(raw_scanline))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _upload_image(client, token, org_id) -> str:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/resources",
        files={"file": ("pixel.png", _tiny_png(), "image/png")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_report_pdf_embeds_a_valid_attachment_image(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "ImageReportOrg")
    project = create_project(client, org_admin_token, org["id"])
    file_id = _upload_image(client, org_admin_token, org["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"pre_markdown": f"# Intro\n\n![a pixel](attachment:{file_id})\n"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert _IMAGE_MARKER in resp.content, "expected the embedded pixel image to appear in the generated PDF"


def test_report_pdf_silently_skips_attachment_from_a_different_org(client, admin_token):
    """A crafted/stale attachment: reference pointing at another
    organisation's file must never leak that file into the report — the
    image is simply omitted, and report generation must still succeed."""
    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "OtherImageOrg")
    other_file_id = _upload_image(client, other_org_admin_token, other_org["id"])

    org, org_admin_token = create_org_admin_in(client, admin_token, "VictimImageOrg")
    project = create_project(client, org_admin_token, org["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"pre_markdown": f"![cross-org](attachment:{other_file_id})\n"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert _IMAGE_MARKER not in resp.content, "a cross-organisation attachment must never be embedded"


def test_report_pdf_silently_skips_a_same_org_requirement_attachment_from_a_different_project(client, admin_token):
    """Deeper hardening-review finding: org scoping alone isn't enough.
    `download_file` gates a direct (non-shared) requirement attachment on
    *project*-level access, not just org membership — a project manager on
    one project in a multi-project org has no automatic right to another
    project's attachments. Before this fix, `_resolve_report_images` only
    checked `organization_id`, so a hand-typed `attachment:<id>` reference
    could pull a different project's requirement attachment into this
    project's report. It must be silently skipped, same as any other
    unresolvable reference."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "CrossProjectImageOrg")
    other_project = create_project(client, org_admin_token, org["id"], name="Other Project")
    component_id, category_id = create_component_and_category(client, org_admin_token, other_project["id"])
    requirement = client.post(
        f"/api/v1/projects/{other_project['id']}/requirements",
        json={"name": "Req With Attachment", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(org_admin_token),
    ).json()
    resp = client.post(
        f"/api/v1/projects/{other_project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("pixel.png", _tiny_png(), "image/png")},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    attachment_file_id = resp.json()["id"]

    project = create_project(client, org_admin_token, org["id"], name="Report Project")
    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"pre_markdown": f"![borrowed](attachment:{attachment_file_id})\n"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert _IMAGE_MARKER not in resp.content, "a same-org but non-shared requirement attachment must never be embedded"


def test_report_pdf_silently_skips_unknown_attachment_reference(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "MissingImageOrg")
    project = create_project(client, org_admin_token, org["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"pre_markdown": "![missing](attachment:00000000-0000-0000-0000-000000000000)\n"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
