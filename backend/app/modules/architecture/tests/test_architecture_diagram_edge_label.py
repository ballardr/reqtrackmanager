"""Tests for the connection names a block diagram can draw beside its lines: the label rule (pinned with the browser's port by
`diagramLabelCases.json`), the setting stored with the version lock, the view's labels for one connection, an unnamed
one, a merged line and a rolled-up line, the server SVG and Mermaid text, the project bundle (and a bundle written before the
setting) and the migration. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import os
import xml.etree.ElementTree as ET
import zipfile

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.diagram_edge_label import NAME_LINE_MAX, NAME_LINES_MAX, edge_label
from app.modules.architecture.tests._helpers import (
    make_connection,
    make_diagram,
    make_element,
    place_all,
    project_base,
    setup,
    view,
)
from app.modules.architecture.tests._repository import FRONTEND_SRC, needs_repository
from tests.conftest import auth_headers, build_alembic_config

CASES_FILE = FRONTEND_SRC / "modules" / "architecture" / "diagramLabelCases.json"
SVG = "{http://www.w3.org/2000/svg}"

#: `(name, count, type_name, protocol, detail, names)`.
CASES = [
    ("nothing to write", 1, None, "", False, []),
    ("one named connection, no detail", 1, "REST API", "HTTPS", False, ["Telemetry"]),
    ("one named connection with detail", 1, "REST API", "HTTPS", True, ["Telemetry"]),
    ("one named connection with a type and no protocol", 1, "REST API", "", True, ["Telemetry"]),
    ("one unnamed connection with detail is today's label", 1, "REST API", "HTTPS", True, []),
    ("one unnamed connection with no detail has no label", 1, "REST API", "HTTPS", False, [""]),
    ("a connection with no type, protocol or detail but a name", 1, None, "", True, ["Telemetry"]),
    ("a merged line of two names with no detail keeps its count", 2, "REST API", "", False, ["Telemetry", "Commands"]),
    ("a merged line of two names with detail", 2, "REST API", "", True, ["Telemetry", "Commands"]),
    ("a merged line of mixed types with detail", 2, None, "", True, ["Telemetry", "Commands"]),
    ("a merged line with a shared protocol and detail", 2, "SPI", "SPI mode 0", True, []),
    ("a merged line of mixed types with a shared protocol", 2, None, "UART 115200", True, []),
    ("a merged line with a shared protocol and no detail shows no protocol", 2, "SPI", "SPI mode 0", False, ["A"]),
    ("a merged line with a shared protocol, names and detail", 3, "SPI", "SPI mode 0", True, ["A", "B"]),
    ("three names fit", 3, "SPI", "", True, ["A", "B", "C"]),
    ("five names show three and count the rest", 5, "SPI", "", True, ["A", "B", "C", "D", "E"]),
    ("four names with no detail", 4, "SPI", "", False, ["A", "B", "C", "D"]),
    ("a merged line where only one connection has a name", 3, "SPI", "", True, ["", "Telemetry", ""]),
    ("a merged line where none has a name is today's label", 3, "SPI", "", True, ["", ""]),
    ("a name's whitespace and line breaks are collapsed", 1, "SPI", "", False, ["  Sensor \n  read\tout  "]),
    ("a long name is cut with an ellipsis", 1, "SPI", "", False, ["x" * 80]),
    ("a name at the limit is kept", 1, None, "", False, ["y" * NAME_LINE_MAX]),
]


def label_cases() -> list[dict]:
    """Every case with the label the Python rule gives, as the shared file holds them."""
    return [
        {
            "name": n, "count": c, "type_name": t, "protocol": p, "detail": d, "names": names,
            "label": edge_label(c, t, p, detail=d, names=names),
        }
        for n, c, t, p, d, names in CASES
    ]


@needs_repository
def test_the_shared_label_cases_are_current():
    produced = json.dumps(label_cases(), indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_SHAPE_CASES") == "1":
        CASES_FILE.write_text(produced, encoding="utf-8")
    assert CASES_FILE.read_text(encoding="utf-8") == produced, (
        "diagramLabelCases.json is out of date with diagram_edge_label; run this test with UPDATE_SHAPE_CASES=1, review the "
        "diff and update edgeLabelText in diagramLines.ts to match."
    )


def test_the_label_writes_names_first_then_the_detail_and_only_a_named_connection_adds_a_line():
    assert edge_label(1, "REST API", "HTTPS", detail=True) == "REST API · HTTPS"  # unchanged without names
    assert edge_label(1, "REST API", "HTTPS", detail=True, names=["Telemetry"]) == "Telemetry\nREST API · HTTPS"
    assert edge_label(1, "REST API", "HTTPS", detail=False, names=["", "  "]) is None
    assert edge_label(2, "SPI", "", detail=False, names=["A", "B"]) == "A\nB\n×2"
    assert edge_label(5, "SPI", "", detail=True, names=list("ABCDE")) == "A\nB\nC\n+2 more\nSPI ×5"
    assert len(edge_label(1, None, "", detail=False, names=["z" * 500]) or "") == NAME_LINE_MAX
    assert NAME_LINES_MAX == 3


# --- The setting ---------------------------------------------------------------


def test_a_diagram_shows_connection_names_off_and_the_setting_is_edited_with_the_version_lock(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch names setting")
    p = project["id"]
    diagram = make_diagram(client, token, p, "Plain")
    assert diagram["show_connection_names"] is False
    url = f"{project_base(p)}/diagrams/{diagram['id']}"
    on = client.put(url, json={"version": diagram["version"], "show_connection_names": True}, headers=auth_headers(token))
    assert on.status_code == 200 and on.json()["show_connection_names"] is True and on.json()["version"] == diagram["version"] + 1
    same = client.put(url, json={"version": diagram["version"] + 1, "show_connection_names": True}, headers=auth_headers(token))
    assert same.status_code == 200 and same.json()["version"] == diagram["version"] + 1  # no change, no new version
    other = client.put(url, json={"version": diagram["version"] + 1, "name": "Renamed"}, headers=auth_headers(token))
    assert other.json()["show_connection_names"] is True  # a field left out is kept
    stale = client.put(url, json={"version": diagram["version"], "show_connection_names": False}, headers=auth_headers(token))
    assert stale.status_code == 409
    assert make_diagram(client, token, p, "Born named", show_connection_names=True)["show_connection_names"] is True
    listed = client.get(f"{project_base(p)}/diagrams", headers=auth_headers(token)).json()
    assert {d["name"]: d["show_connection_names"] for d in listed} == {"Renamed": True, "Born named": True}


# --- The view ------------------------------------------------------------------


def _two_boxes(client, token, p, **fields):
    a = make_element(client, token, p, "Alpha")
    b = make_element(client, token, p, "Bravo")
    diagram = place_all(client, token, p, make_diagram(client, token, p, "Names", **fields), a["id"], b["id"])
    return a, b, diagram


def _set(client, token, p, diagram, **fields) -> dict:
    resp = client.put(
        f"{project_base(p)}/diagrams/{diagram['id']}", json={"version": diagram["version"], **fields}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_line_is_labelled_with_the_name_of_its_connection_and_an_unnamed_one_adds_nothing(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch names one")
    p = project["id"]
    a, b, diagram = _two_boxes(client, token, p)
    make_connection(client, token, p, a["id"], b["id"], name="Telemetry", protocol="HTTPS")
    (edge,) = view(client, token, p, diagram["id"])["edges"]
    assert edge["label"] is None  # off by default and no detail
    diagram = _set(client, token, p, diagram, show_connection_names=True)
    assert view(client, token, p, diagram["id"])["edges"][0]["label"] == "Telemetry"
    diagram = _set(client, token, p, diagram, connection_detail=True)
    assert view(client, token, p, diagram["id"])["edges"][0]["label"] == "Telemetry\nREST API · HTTPS"
    diagram = _set(client, token, p, diagram, show_connection_names=False)
    assert view(client, token, p, diagram["id"])["edges"][0]["label"] == "REST API · HTTPS"  # detail alone is unchanged
    unnamed_a, unnamed_b, plain = _two_boxes(client, token, p, show_connection_names=True)
    make_connection(client, token, p, unnamed_a["id"], unnamed_b["id"], protocol="SPI mode 0")
    assert view(client, token, p, plain["id"])["edges"][0]["label"] is None  # the code is not a name


def test_a_merged_line_writes_up_to_three_names_in_code_order_then_the_rest_and_keeps_its_count(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch names merged")
    p = project["id"]
    a, b, diagram = _two_boxes(client, token, p, show_connection_names=True)
    for name in ("Echo", "Delta", "Charlie", "Bravo", "Alpha"):  # created in this order, so codes follow it
        make_connection(client, token, p, a["id"], b["id"], name=name)
    (edge,) = view(client, token, p, diagram["id"])["edges"]
    assert edge["count"] == 5 and edge["label"] == "Echo\nDelta\nCharlie\n+2 more\n×5"
    diagram = _set(client, token, p, diagram, connection_detail=True)
    labels = {e["label"] for e in view(client, token, p, diagram["id"])["edges"]}
    # With detail on parallel connections are not merged: each line carries its own name above its type.
    assert labels == {f"{n}\nREST API" for n in ("Echo", "Delta", "Charlie", "Bravo", "Alpha")}


def test_a_rolled_up_line_names_the_connections_behind_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch names rollup")
    p = project["id"]
    platform = make_element(client, token, p, "Platform", type_name="System")
    api = make_element(client, token, p, "API", parent_id=platform["id"])
    db = make_element(client, token, p, "Database", parent_id=platform["id"])
    cloud = make_element(client, token, p, "Cloud", type_name="System")
    make_connection(client, token, p, api["id"], cloud["id"], name="Uplink")
    make_connection(client, token, p, db["id"], cloud["id"], name="Backup")
    diagram = place_all(
        client, token, p, make_diagram(client, token, p, "Context", connection_detail=True, show_connection_names=True),
        platform["id"], cloud["id"],
    )
    (edge,) = view(client, token, p, diagram["id"])["edges"]
    assert edge["rolled_up"] and edge["label"] == "Uplink\nBackup\nREST API ×2"


# --- The exports ---------------------------------------------------------------


def test_the_svg_writes_each_label_line_as_its_own_escaped_text_and_mermaid_breaks_the_lines(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch names exports")
    p = project["id"]
    a, b, diagram = _two_boxes(client, token, p, show_connection_names=True, connection_detail=True)
    make_connection(client, token, p, a["id"], b["id"], name='Gate <script> & "co"', protocol="HTTPS")
    base = f"{project_base(p)}/diagrams/{diagram['id']}"
    svg = client.get(f"{base}/svg", headers=auth_headers(token)).text
    root = ET.fromstring(svg)  # well-formed
    texts = ["".join(t.itertext()) for t in root.iter(f"{SVG}text")]
    assert 'Gate <script> & "co"' in texts and "REST API · HTTPS" in texts
    assert "<script" not in svg and "Gate &lt;script&gt; &amp;" in svg
    ys = {t.text: float(t.get("y") or 0) for t in root.iter(f"{SVG}text") if t.text in ('Gate <script> & "co"', "REST API · HTTPS")}
    assert ys['Gate <script> & "co"'] < ys["REST API · HTTPS"]  # the name is above the type and protocol
    mermaid = client.get(f"{base}/mermaid", headers=auth_headers(token)).text
    (line,) = (x for x in mermaid.splitlines() if "-->" in x)
    assert 'Gate #lt;script#gt; #amp; #quot;co#quot;<br/>REST API · HTTPS"' in line and "<script" not in mermaid


# --- Travel --------------------------------------------------------------------


def _export(client, token, project_id) -> tuple[bytes, dict]:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content, json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))


def _import(client, token, org_id, content: bytes, name: str) -> str:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["project"]["id"]


def test_the_setting_round_trips_through_the_project_bundle_and_an_older_bundle_imports_it_off(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch names bundle")
    p = project["id"]
    _two_boxes(client, token, p, show_connection_names=True)
    content, data = _export(client, token, p)
    assert data["architecture_diagrams"][0]["show_connection_names"] is True
    copy = _import(client, token, org["id"], content, "Arch names copy")
    (imported,) = client.get(f"{project_base(copy)}/diagrams", headers=auth_headers(token)).json()
    assert imported["show_connection_names"] is True

    source = zipfile.ZipFile(io.BytesIO(content))
    for entry in data["architecture_diagrams"]:
        entry.pop("show_connection_names")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item, json.dumps(data) if item.filename == "project.json" else source.read(item.filename))
    older = _import(client, token, org["id"], out.getvalue(), "Arch names old copy")
    (diagram,) = client.get(f"{project_base(older)}/diagrams", headers=auth_headers(token)).json()
    assert diagram["show_connection_names"] is False


def test_the_diagram_table_export_has_a_connection_names_column(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch names table")
    p = project["id"]
    _two_boxes(client, token, p, show_connection_names=True)
    resp = client.get(f"/api/v1/projects/{p}/records/architecture_diagram/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    header, row = resp.content.decode("utf-8-sig").splitlines()[:2]
    columns = header.split(",")
    assert "show_connection_names" in columns and row.split(",")[columns.index("show_connection_names")] == "Yes"


def test_the_migration_adds_the_column_off_for_existing_diagrams_and_reverses_cleanly(client, admin_token):
    config = build_alembic_config()
    try:
        command.downgrade(config, "0199")
        with engine.connect() as connection:
            names = {
                row[0] for row in connection.execute(text(
                    "SELECT table_name FROM information_schema.columns WHERE column_name = 'show_connection_names'"
                ))
            }
        assert names == set()
        command.upgrade(config, "0200")
        with engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT table_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE column_name = 'show_connection_names'"
            )).all()
        assert [r[0] for r in rows] == ["architecture_diagrams"]
        assert all(r[1] == "NO" and "false" in str(r[2]) for r in rows)
    finally:
        command.upgrade(config, "head")
