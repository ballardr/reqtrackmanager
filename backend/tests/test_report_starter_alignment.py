"""
Module: tests.test_report_starter_alignment

Every starter that prints tables with the same headings prints them lined up, in each file format a person opens.

Responsibilities:
- Run each document starter on a project holding open questions (some overdue), requirements, a pain point and a
  decision, in the preview (HTML), Word and OpenDocument formats, and check that tables with identical headings
  share one set of column widths (`services.report_table_alignment`).
- Run the same starters on a merged project tree and on an organisation-wide run, which print a pair per project.
- Pin the Review Package's Open Questions pair, the one adjacent same-heading pair among the starters.

Design decisions:
- The checks are generic (group by heading list, compare widths), not a list of known pairs, so a starter or module
  report added later is covered by the same test without an edit here.
- A group is only compared when its tables share a usable page width, as the rule itself does; the starters use a
  single page style, so every same-heading table is one group.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import defaultdict
from datetime import date, timedelta

import pytest
from docx import Document as DocxDocument

from tests.conftest import auth_headers
from tests.link_world import World
from tests.test_report_starters import DOCUMENT_STARTER_NAMES, by_name, org_layouts

COL = re.compile(r"<col[^>]*width:\s*([\d.]+)%", re.I)
TABLE = re.compile(r"<table.*?</table>", re.S | re.I)
HEADING_CELL = re.compile(r"<th[^>]*>(.*?)</th>", re.S | re.I)


def full_world(client, admin_token, name: str) -> World:
    """An organisation with the starters and every module that contributes a starter part switched on."""
    world = World(client, admin_token, name, decisions=True, context_strategy=True, keep_starter_layouts=True)
    world.enable("risk_management")
    world.enable("stakeholders")
    return world


def fill(world: World, project: dict) -> None:
    """Records for every table a starter prints: open questions (one overdue), a requirement, a pain point, a decision."""
    questions = f"/api/v1/projects/{project['id']}/modules/context_strategy/open-questions"
    past = (date.today() - timedelta(days=400)).isoformat()
    bodies = (
        {"question": "Which regulator signs off the data transfer?", "due_date": past},
        {"question": "Keep Q2 pricing"},
        {"question": "Cut-over date for the production environment", "due_date": past},
    )
    for body in bodies:
        assert world.client.post(questions, json=body, headers=auth_headers(world.token)).status_code == 201
    world.requirement(project, "The system shall log in users")
    world.pain_point(project, "Slow sign in")
    world.decision(project)


def run(world: World, project: dict, name: str, fmt: str, **params):
    layout = by_name(org_layouts(world), name)
    url = f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run"
    resp = world.client.get(url, params={"format": fmt, **params}, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp


def run_org(world: World, name: str, fmt: str):
    layout = by_name(org_layouts(world), name)
    url = f"/api/v1/orgs/{world.org['id']}/custom-reports/{layout['id']}/run"
    resp = world.client.get(url, params={"format": fmt}, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp


def html_groups(html: str) -> dict[tuple[str, ...], list[list[float]]]:
    """Column percentages of every preview table, grouped by its heading cells; tables with no `<col>` are skipped."""
    groups: dict[tuple[str, ...], list[list[float]]] = defaultdict(list)
    for table in TABLE.findall(html):
        heads = tuple(re.sub(r"<[^>]+>", "", h).strip() for h in HEADING_CELL.findall(table))
        widths = [float(w) for w in COL.findall(table)]
        if len(heads) > 1 and widths:
            groups[heads].append(widths)
    return groups


def docx_groups(data: bytes) -> dict[tuple[str, ...], list[list[float]]]:
    """Grid column widths in cm of every Word table, grouped by its first row."""
    groups: dict[tuple[str, ...], list[list[float]]] = defaultdict(list)
    for table in DocxDocument(io.BytesIO(data)).tables:
        heads = tuple(c.text.strip() for c in table.rows[0].cells)
        if len(heads) > 1:
            groups[heads].append([round(c.width.cm, 2) for c in table.columns])
    return groups


def odt_groups(data: bytes) -> dict[tuple[str, ...], list[list[str]]]:
    """Column style widths of every OpenDocument table, grouped by its first row's text."""
    content = zipfile.ZipFile(io.BytesIO(data)).read("content.xml").decode()
    styles = dict(re.findall(r'<style:style style:name="([^"]+)"[^>]*>\s*<style:table-column-properties[^>]*style:column-width="([^"]+)"', content))
    groups: dict[tuple[str, ...], list[list[str]]] = defaultdict(list)
    for table in re.findall(r"<table:table .*?</table:table>", content, re.S):
        cols = re.findall(r'<table:table-column[^>]*table:style-name="([^"]+)"', table)
        first = re.search(r"<table:table-row.*?</table:table-row>", table, re.S)
        cells = re.findall(r"<table:table-cell.*?</table:table-cell>", first.group(0), re.S) if first else []
        heads = tuple(re.sub(r"<[^>]+>", "", c).strip() for c in cells)
        if len(heads) > 1:
            groups[heads].append([styles.get(c, c) for c in cols])
    return groups


def assert_every_group_lines_up(groups: dict, kind: str) -> int:
    """Every group of two or more tables has one set of widths; returns how many groups were compared."""
    compared = 0
    for heads, widths in groups.items():
        if len(widths) < 2:
            continue
        compared += 1
        assert all(w == widths[0] for w in widths), f"{kind}: tables headed {heads} differ: {widths}"
    return compared


@pytest.mark.parametrize("name", DOCUMENT_STARTER_NAMES)
def test_a_starter_lines_up_its_same_heading_tables_in_every_format(client, admin_token, name):
    world = full_world(client, admin_token, "Starter Align")
    project = world.project("Aligned")
    fill(world, project)

    assert_every_group_lines_up(html_groups(run(world, project, name, "html").text), "html")
    assert_every_group_lines_up(docx_groups(run(world, project, name, "docx").content), "docx")
    assert_every_group_lines_up(odt_groups(run(world, project, name, "odt").content), "odt")
    assert run(world, project, name, "pdf").content.startswith(b"%PDF")


def test_the_review_package_pair_lines_up_in_every_format(client, admin_token):
    world = full_world(client, admin_token, "Starter Pair")
    project = world.project("Pair")
    fill(world, project)
    name = "Review Package"

    html = html_groups(run(world, project, name, "html").text)
    docx = docx_groups(run(world, project, name, "docx").content)
    odt = odt_groups(run(world, project, name, "odt").content)

    assert assert_every_group_lines_up(html, "html") >= 1
    assert assert_every_group_lines_up(docx, "docx") >= 1
    assert assert_every_group_lines_up(odt, "odt") >= 1
    assert sum(len(w) for w in html.values()) >= 2
    # Word and OpenDocument lined up before the rule too (equal columns); the rule makes them follow the content.
    nine = next(w for heads, w in docx.items() if heads[0] == "Question")
    assert len(set(nine[0])) > 1, nine[0]
    assert len(set(next(w for heads, w in odt.items() if heads[0] == "Question")[0])) > 1


@pytest.mark.parametrize("name", DOCUMENT_STARTER_NAMES)
def test_a_merged_project_tree_lines_up_its_same_heading_tables(client, admin_token, name):
    world = full_world(client, admin_token, "Starter Tree")
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    fill(world, parent)
    fill(world, child)

    html = run(world, parent, name, "html", include_children="true").text
    docx = run(world, parent, name, "docx", include_children="true").content

    assert_every_group_lines_up(html_groups(html), "html")
    assert_every_group_lines_up(docx_groups(docx), "docx")


@pytest.mark.parametrize("name", ["Review Package", "Business Requirements Document"])
def test_an_organisation_run_lines_up_the_tables_of_every_project(client, admin_token, name):
    world = full_world(client, admin_token, "Starter Org Run")
    first, second = world.project("First"), world.project("Second")
    fill(world, first)
    fill(world, second)

    html = run_org(world, name, "html").text
    docx = run_org(world, name, "docx").content

    assert_every_group_lines_up(html_groups(html), "html")
    assert_every_group_lines_up(docx_groups(docx), "docx")
