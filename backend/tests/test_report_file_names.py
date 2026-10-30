"""Tests for default report file names (`services.report_file_names`): the template check and fill (including hostile
values), the layout `file_name` key and its `@filename` text form, a layout run's download name, a pack's zip and entry
names, the organisation default for reports that set none (and its settings route), the header the name reaches and
the live example endpoint. Each test builds its own organisation.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote

import pytest

from app.services.downloads import file_response
from app.services.report_file_names import (
    MAX_STEM_CHARS,
    ORG_FILE_NAME_PLACEHOLDERS,
    clean_filename,
    example,
    render_stem,
    template_problems,
)
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import empty_tree, validate_tree
from tests.conftest import auth_headers
from tests.link_world import REQ, World

VALUES = {
    "report_title": "Quarterly review", "project_name": "Apollo", "project_code": "ACME", "organisation": "Acme Ltd",
    "generated_on": "2026-10-29", "layout_version": "3", "format": "pdf",
}


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Names Org")


def tree_with(file_name: str | None, **extra: Any) -> dict[str, Any]:
    tree: dict[str, Any] = {
        **empty_tree("document"), "nodes": [{"type": "heading", "text": "Report of {{project_name}}"}], **extra,
    }
    if file_name is not None:
        tree["file_name"] = file_name
    return tree


def make_layout(world: World, name: str, tree: dict[str, Any], *, project: dict | None = None) -> dict:
    base = f"/api/v1/projects/{project['id']}" if project else f"/api/v1/orgs/{world.org['id']}"
    resp = world.client.post(
        f"{base}/report-layouts", json={"name": name, "description": "d", "family": tree["family"], "tree": tree},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def run(world: World, project: dict, layout: dict, fmt: str = "pdf", **headers: str):
    return world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": fmt},
        headers={**auth_headers(world.token), **headers},
    )


def downloaded_name(resp) -> str:
    assert resp.status_code == 200, resp.text
    match = re.search(r'filename="([^"]*)"', resp.headers["content-disposition"])
    assert match is not None
    return match.group(1)


def set_org_default(world: World, template: str | None):
    url = f"/api/v1/orgs/{world.org['id']}/advanced-settings"
    current = world.client.get(url, headers=auth_headers(world.token)).json()
    return world.client.put(url, json={**current, "report_file_name": template}, headers=auth_headers(world.token))


# ---- the template and its fill ---------------------------------------------------------------------------------


def test_a_template_is_filled_with_the_run_facts():
    stem = render_stem("{{project_code}}-{{report_title}}-{{generated_on}}", VALUES)
    assert stem == "ACME-Quarterly review-2026-10-29"


def test_a_list_variable_is_cut_to_a_short_value():
    stem = render_stem("{{var.cats}}", VALUES, {"cats": ", ".join(f"Category{i}" for i in range(30))})
    assert stem is not None and len(stem) <= 40


@pytest.mark.parametrize("template", [None, "", "   ", "{{project_code}}", "{{var.none}}", "///", "..."])
def test_a_template_with_nothing_usable_falls_back(template):
    values = {**VALUES, "project_code": ""}
    assert render_stem(template, values, {"none": ""}) is None


@pytest.mark.parametrize(
    "hostile",
    ["../../etc/passwd", "a\r\nX-Evil: 1", 'a"b', "a/b\\c", "con", "NUL.txt", "..", "x" * 500, "tab\tname", "ünï/çødé", "%2e%2e%2f", "\x00x"],
)
def test_a_hostile_value_can_never_make_a_path_or_a_header(hostile):
    stem = render_stem("{{report_title}}-{{var.v}}", {**VALUES, "report_title": hostile}, {"v": hostile})
    assert stem is None or (
        len(stem) <= MAX_STEM_CHARS and re.fullmatch(r"[A-Za-z0-9 ._-]+", stem)
        and ".." not in stem and "/" not in stem and "\\" not in stem and not stem.startswith(".")
    )


def test_a_literal_in_the_template_is_cleaned_too():
    assert render_stem("../../{{project_name}}\r\n", VALUES) == "Apollo"


def test_accents_fold_to_their_base_letter():
    assert render_stem("{{project_name}}", {**VALUES, "project_name": "Café Zoë"}) == "Cafe Zoe"


@pytest.mark.parametrize("device", ["CON", "nul", "COM1", "lpt9.txt"])
def test_a_windows_device_name_is_not_a_stem(device):
    assert clean_filename(device).startswith("_")


def test_the_template_check_names_the_problem():
    assert template_problems("{{report_title}}-{{var.x}}", variables=["x"]) == []
    assert any("Unknown placeholder" in p for p in template_problems("{{nope}}"))
    assert any("current record" in p for p in template_problems("{{record.code}}"))
    assert any("not a variable" in p for p in template_problems("{{var.y}}", variables=["x"]))
    assert template_problems("{{var.anything}}", any_variable=True) == []
    assert any("at most" in p.lower() for p in template_problems("x" * 201))
    assert template_problems("", variables=[]) != []
    assert template_problems(5) == ["Must be text."]  # type: ignore[arg-type]


def test_the_organisation_default_has_no_layout_version_and_no_variables():
    assert "layout_version" not in ORG_FILE_NAME_PLACEHOLDERS
    assert template_problems("{{layout_version}}", allowed=ORG_FILE_NAME_PLACEHOLDERS, variables=None) != []
    assert template_problems("{{var.x}}", allowed=ORG_FILE_NAME_PLACEHOLDERS, variables=None) != []


def test_the_live_example_uses_sample_values_and_reports_problems():
    assert example("{{project_code}}-{{report_title}}", kind="layout") == ("ACME-Quarterly review.pdf", [])
    name, problems = example("{{var.region}}", kind="layout", variables=["region"], extension="docx")
    assert name == "Region value.docx" and problems == []
    name, problems = example("{{record.code}}", kind="layout")
    assert name is None and problems
    assert example("{{layout_version}}", kind="organization")[0] is None


def test_a_name_cannot_inject_a_header():
    response = file_response(b"x", 'a"b\r\nX-Injected: 1', "pdf")
    value = response.headers["content-disposition"]
    assert "\r" not in value and "\n" not in value and "X-Injected" not in response.headers
    assert unquote(value).count('"') >= 2


# ---- the layout's key and its text form ---------------------------------------------------------------------------


def test_a_layout_may_carry_a_file_name_and_the_text_view_round_trips_it():
    tree = tree_with("{{project_code}}-{{report_title}}")
    assert validate_tree(tree).ok
    text = format_tree(tree)
    assert '@filename "{{project_code}}-{{report_title}}"' in text
    assert parse_text(text).tree == tree


@pytest.mark.parametrize(
    ("file_name", "fragment"),
    [("{{nope}}", "Unknown placeholder"), ("{{record.code}}", "current record"), ("{{var.missing}}", "not a variable"), ("", "Write a name")],
)
def test_a_layout_file_name_with_a_bad_placeholder_is_refused_at_save(file_name, fragment):
    errors = validate_tree(tree_with(file_name)).errors
    assert any(e.path == "file_name" and fragment in e.message for e in errors)


def test_a_layout_file_name_may_use_its_own_variables():
    tree = tree_with("{{var.team}}", variables=[{"name": "team", "type": "text", "default": "Blue"}])
    assert validate_tree(tree).ok


def test_the_text_view_refuses_a_misplaced_or_repeated_filename():
    after = parse_text('@layout document\n@heading "A"\n@filename "x"\n')
    assert after.tree is None and any("before the first block" in e.message for e in after.errors)
    twice = parse_text('@layout document\n@filename "x"\n@filename "y"\n')
    assert twice.tree is None and any("once" in e.message for e in twice.errors)


# ---- a layout run's download name --------------------------------------------------------------------------------


def test_a_layout_downloads_under_its_file_name_template(world):
    project = world.project("Apollo Programme")
    layout = make_layout(world, "Quarterly review", tree_with("{{project_name}}-{{report_title}}-v{{layout_version}}"), project=project)

    for fmt, ext in (("pdf", "pdf"), ("docx", "docx"), ("html", "html"), ("odt", "odt")):
        assert downloaded_name(run(world, project, layout, fmt)) == f"Apollo Programme-Quarterly review-v1.{ext}"


def test_the_format_placeholder_follows_the_file_produced(world):
    project = world.project("P")
    layout = make_layout(world, "Doc", tree_with("{{report_title}}.{{format}}"), project=project)
    assert downloaded_name(run(world, project, layout, "docx")) == "Doc.docx.docx"


def test_a_layout_without_a_name_keeps_the_name_it_always_had(world):
    project = world.project("Plain")
    layout = make_layout(world, "Overview", tree_with(None), project=project)
    assert downloaded_name(run(world, project, layout)) == "Plain-Overview.pdf"


@pytest.mark.parametrize("offset_hours", [10, -8])
def test_the_run_date_is_the_callers_own_day(world, offset_hours):
    project = world.project("Dated")
    layout = make_layout(world, "Dated", tree_with("{{generated_on}}"), project=project)
    client_day = (datetime.now(UTC) + timedelta(hours=offset_hours)).date().isoformat()

    assert downloaded_name(run(world, project, layout, **{"X-Client-Date": client_day})) == f"{client_day}.pdf"


def test_a_run_time_variable_can_name_the_file(world):
    project = world.project("Vars")
    tree = tree_with("{{report_title}}-{{var.team}}", variables=[{"name": "team", "type": "text", "default": "Blue"}])
    layout = make_layout(world, "Teams", tree, project=project)

    default = run(world, project, layout)
    chosen = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run",
        params={"format": "pdf", "variables": json.dumps({"team": "Red/../Team"})}, headers=auth_headers(world.token),
    )

    assert downloaded_name(default) == "Teams-Blue.pdf"
    assert chosen.status_code == 200
    name = downloaded_name(chosen)
    assert name.startswith("Teams-") and "/" not in name and ".." not in name


def test_a_table_layout_names_a_zip_of_sheets_with_the_zip_extension(world):
    project = world.project("Sheets")
    sheet = lambda n: {"type": "sheet", "name": n, "source": {"record_type": REQ}, "columns": [{"field": "title"}]}  # noqa: E731
    tree = {**empty_tree("table"), "nodes": [sheet("A"), sheet("B")], "file_name": "{{project_name}}.{{format}}"}
    layout = make_layout(world, "Two", tree, project=project)

    assert downloaded_name(run(world, project, layout, "csv")) == "Sheets.zip.zip"


# ---- the organisation default ---------------------------------------------------------------------------------------


def test_the_organisation_default_names_a_layout_that_sets_none(world):
    project = world.project("Org Default")
    plain = make_layout(world, "Plain", tree_with(None), project=project)
    own = make_layout(world, "Own", tree_with("mine-{{report_title}}"), project=project)

    assert set_org_default(world, "{{organisation}}-{{report_title}}").status_code == 200

    assert downloaded_name(run(world, project, plain)) == f"{world.org['name']}-Plain.pdf"
    assert downloaded_name(run(world, project, own)) == "mine-Own.pdf"  # the layout's own name wins


def test_the_organisation_default_names_a_module_report(world):
    project = world.project("Module")
    before = world.client.post(
        f"/api/v1/projects/{project['id']}/reports", json={"format": "csv"}, headers=auth_headers(world.token),
    )
    assert downloaded_name(before) == "Module-requirements.csv"

    assert set_org_default(world, "{{project_name}}-{{report_title}}-{{format}}").status_code == 200
    after = world.client.post(
        f"/api/v1/projects/{project['id']}/reports", json={"format": "csv"}, headers=auth_headers(world.token),
    )

    assert downloaded_name(after) == "Module-Requirements report-csv.csv"


def test_the_settings_route_refuses_a_bad_default_and_clears_a_blank_one(world):
    assert set_org_default(world, "{{record.code}}").status_code == 422
    assert set_org_default(world, "{{var.x}}").status_code == 422
    assert set_org_default(world, "{{layout_version}}").status_code == 422
    saved = set_org_default(world, " {{project_name}} ")
    assert saved.status_code == 200 and saved.json()["report_file_name"] == "{{project_name}}"
    cleared = set_org_default(world, "  ")
    assert cleared.status_code == 200 and cleared.json()["report_file_name"] is None


# ---- a pack ------------------------------------------------------------------------------------------------------


def pack_definition(**extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "entries": [
            {"kind": "layout", "name": "Named", "format": "pdf"},
            {"kind": "layout", "name": "Plain", "format": "docx"},
            {"kind": "layout", "name": "Override", "format": "html", "filename": "{{report_title}}-x"},
        ],
        **extra,
    }


def make_pack(world: World, project: dict, definition: dict[str, Any]):
    return world.client.post(
        f"/api/v1/projects/{project['id']}/report-packs", json={"name": "Board pack", "description": "d", "definition": definition},
        headers=auth_headers(world.token),
    )


def test_a_pack_names_its_zip_and_entries_by_template(world):
    project = world.project("Packed")
    make_layout(world, "Named", tree_with("{{report_title}}-named"), project=project)
    make_layout(world, "Plain", tree_with(None), project=project)
    make_layout(world, "Override", tree_with("ignored"), project=project)
    pack = make_pack(world, project, pack_definition(file_name="{{project_name}}-{{report_title}}-{{generated_on}}"))
    assert pack.status_code == 201, pack.text
    client_day = datetime.now(UTC).date().isoformat()

    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-packs/{pack.json()['id']}/run", json={},
        headers={**auth_headers(world.token), "X-Client-Date": client_day},
    )

    assert downloaded_name(resp) == f"Packed-Board pack-{client_day}.zip"
    names = sorted(zipfile.ZipFile(io.BytesIO(resp.content)).namelist())
    assert names == ["01-Named-named.pdf", "02-Plain.docx", "03-Override-x.html", "manifest.json"]


def test_a_pack_without_a_name_keeps_its_old_zip_name(world):
    project = world.project("Old")
    make_layout(world, "Named", tree_with(None), project=project)
    pack = make_pack(world, project, {"schema_version": 1, "entries": [{"kind": "layout", "name": "Named", "format": "pdf"}]})
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-packs/{pack.json()['id']}/run", json={}, headers=auth_headers(world.token),
    )
    assert downloaded_name(resp) == "Old-Board pack.zip"


@pytest.mark.parametrize(
    ("definition", "path"),
    [
        ({"file_name": "{{record.code}}"}, "file_name"),
        ({"file_name": "{{var.nope}}"}, "file_name"),
        ({"file_name": ""}, "file_name"),
        ({"entries": [{"kind": "layout", "name": "A", "format": "pdf", "filename": "{{nope}}"}]}, "entries[0].filename"),
    ],
)
def test_a_pack_with_a_bad_name_template_is_refused_with_its_position(world, definition, path):
    project = world.project("Bad")
    resp = make_pack(world, project, {"schema_version": 1, "entries": [], **definition})
    assert resp.status_code == 422
    assert path in resp.text


# ---- the live example --------------------------------------------------------------------------------------------


def test_the_example_endpoint_answers_with_the_name_or_the_problems(world):
    url = "/api/v1/report-file-names/example"
    good = world.client.post(
        url, json={"template": "{{project_code}}-{{var.team}}", "kind": "layout", "variables": ["team"], "extension": "docx"},
        headers=auth_headers(world.token),
    )
    assert good.status_code == 200 and good.json() == {
        "example": "ACME-Team value.docx", "problems": [],
        "placeholders": [
            "{{report_title}}", "{{project_name}}", "{{project_code}}", "{{organisation}}", "{{generated_on}}",
            "{{layout_version}}", "{{format}}", "{{var.team}}",
        ],
    }
    bad = world.client.post(url, json={"template": "{{record.code}}", "kind": "pack"}, headers=auth_headers(world.token))
    assert bad.json()["example"] is None and bad.json()["problems"]
    assert world.client.post(url, json={"template": "x"}).status_code in (401, 403)


# ---- the record-image name rule shares the syntax -----------------------------------------------------------------


def test_the_record_image_name_rule_reads_the_same_placeholders(world):
    from app.services.report_record_images import compile_pattern, wildcard_match

    fill = lambda text: text.replace("{{record.code}}", "REQ-001").replace("{{var.team}}", "*")  # noqa: E731
    tokens = compile_pattern("{{record.code}}-*", fill)
    assert wildcard_match(tokens, "req-001-site.png") and not wildcard_match(tokens, "other-site.png")
    hostile = compile_pattern("{{var.team}}.png", fill)
    assert wildcard_match(hostile, "*.png") and not wildcard_match(hostile, "anything.png")  # a value is literal


# ---- bundles ---------------------------------------------------------------------------------------------------------


def test_a_project_bundle_carries_a_layouts_and_a_packs_file_names(world):
    source = world.project("Source")
    make_layout(world, "Named", tree_with("{{report_title}}-{{generated_on}}"), project=source)
    pack = make_pack(world, source, {
        "schema_version": 1, "file_name": "{{project_name}}-bundle",
        "entries": [{"kind": "layout", "name": "Named", "format": "html", "filename": "{{report_title}}-entry"}],
    })
    assert pack.status_code == 201, pack.text
    exported = world.client.get(f"/api/v1/projects/{source['id']}/export", headers=auth_headers(world.token))
    assert exported.status_code == 200, exported.text

    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Copied"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(world.token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    h = auth_headers(world.token)

    layouts = world.client.get(f"/api/v1/projects/{copy['id']}/report-layouts", headers=h).json()
    layout = next(row for row in layouts if row["name"] == "Named")
    detail = world.client.get(f"/api/v1/projects/{copy['id']}/report-layouts/{layout['id']}", headers=h).json()
    assert detail["current"]["tree"]["file_name"] == "{{report_title}}-{{generated_on}}"
    packs = world.client.get(f"/api/v1/projects/{copy['id']}/report-packs", headers=h).json()
    pack_detail = world.client.get(f"/api/v1/projects/{copy['id']}/report-packs/{packs[0]['id']}", headers=h).json()
    definition = pack_detail["current"]["definition"]
    assert definition["file_name"] == "{{project_name}}-bundle"
    assert definition["entries"][0]["filename"] == "{{report_title}}-entry"
