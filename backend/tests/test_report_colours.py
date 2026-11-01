"""Tests for report colour words and schemes: the resolver, the scheme checks, the tree and text view, the organisation's
scheme (API, bundle) and a run that resolves a name layout-first, organisation-second, standard-set-last and records
what it used."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.models.generated_report import GeneratedReport
from app.models.organization import Organization
from app.services.report_colours import (
    STANDARD_COLOURS,
    colour_word_problem,
    effective_scheme,
    known_names,
    palette_problems,
    resolve_colour,
)
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import InvalidLayoutError, assert_valid, empty_tree
from tests.conftest import auth_headers
from tests.test_report_images import db, world  # noqa: F401 - the world and db fixtures
from tests.test_report_shapes import preview

ACCENT = "#112233"


def shape_tree(palette: list[dict[str, str]] | None = None, **keys: Any) -> dict[str, Any]:
    tree = {**empty_tree("document"), "nodes": [{"type": "shape", "shape": "rectangle", "width": 5, "height": 2, **keys}]}
    if palette is not None:
        tree["palette"] = palette
    return tree


def errors_of(tree: dict[str, Any], **kwargs: Any) -> list[tuple[str, str]]:
    with pytest.raises(InvalidLayoutError) as caught:
        assert_valid(tree, **kwargs)
    return [(e.path, e.message) for e in caught.value.errors]


# ---- the resolver ------------------------------------------------------------------------------------------------


def test_reserved_words_and_hex_resolve():
    assert resolve_colour("accent", ACCENT) == ACCENT
    assert resolve_colour("white", ACCENT) == "#ffffff" and resolve_colour("black", ACCENT) == "#000000"
    assert resolve_colour("none", ACCENT) is None
    assert resolve_colour("#ABC", ACCENT) == "#aabbcc" and resolve_colour("#AA00FF", ACCENT) == "#aa00ff"


def test_the_derived_words_are_a_tint_and_a_shade_of_the_accent():
    assert resolve_colour("accent_light", "#000000") == "#d9d9d9"  # 85% of the way to white
    assert resolve_colour("accent_dark", "#ffffff") == "#bfbfbf"  # 25% of the way to black
    assert resolve_colour("accent_light", ACCENT) != ACCENT and resolve_colour("accent_dark", ACCENT) != ACCENT


def test_the_standard_names_resolve_with_no_scheme_at_all():
    assert resolve_colour("primary", ACCENT) == ACCENT
    assert resolve_colour("secondary", ACCENT) == resolve_colour("accent_dark", ACCENT)
    assert resolve_colour("tint", ACCENT) == resolve_colour("accent_light", ACCENT)
    assert resolve_colour("neutral", ACCENT) == "#6b7280"


def test_a_name_resolves_by_its_scheme_and_follows_the_accent_when_it_names_it():
    scheme = effective_scheme([{"name": "warn", "colour": "#b45309"}, {"name": "brand", "colour": "accent"}], None)
    assert resolve_colour("warn", ACCENT, scheme) == "#b45309"
    assert resolve_colour("brand", "#445566", scheme) == "#445566"  # another organisation's branding, no edit to the layout


def test_a_layout_name_overrides_the_organisation_which_overrides_the_standard_set():
    organisation = [{"name": "primary", "colour": "#111111"}, {"name": "extra", "colour": "#222222"}]
    layout = [{"name": "primary", "colour": "#333333"}]
    assert resolve_colour("primary", ACCENT, effective_scheme(None, None)) == ACCENT
    assert resolve_colour("primary", ACCENT, effective_scheme(None, organisation)) == "#111111"
    assert resolve_colour("primary", ACCENT, effective_scheme(layout, organisation)) == "#333333"
    assert resolve_colour("extra", ACCENT, effective_scheme(layout, organisation)) == "#222222"


def test_an_unknown_name_or_a_bad_accent_never_breaks_a_run():
    assert resolve_colour("ghost", ACCENT, effective_scheme(None, None)) == ACCENT
    assert resolve_colour("accent", "not a colour") == "#475569"


# ---- the checks --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("palette", "path"),
    [
        ("blue", "palette"),
        ([{"name": f"c{i}", "colour": "#000000"} for i in range(9)], "palette"),
        ([{"name": "accent", "colour": "#000000"}], "palette[0].name"),  # reserved
        ([{"name": "none", "colour": "#000000"}], "palette[0].name"),
        ([{"name": "Primary", "colour": "#000000"}], "palette[0].name"),  # lower case only
        ([{"name": "1a", "colour": "#000000"}], "palette[0].name"),  # starts with a letter
        ([{"name": "x" * 25, "colour": "#000000"}], "palette[0].name"),
        ([{"name": "a", "colour": "#000000"}, {"name": "a", "colour": "#ffffff"}], "palette[1].name"),
        ([{"name": "a", "colour": "red"}], "palette[0].colour"),
        ([{"name": "a", "colour": "none"}], "palette[0].colour"),
        ([{"name": "a", "colour": "primary"}], "palette[0].colour"),  # a name may not point at a name
        ([{"name": "a"}], "palette[0]"),
        ([{"name": "a", "colour": "#000000", "extra": 1}], "palette[0]"),
    ],
)
def test_a_bad_scheme_is_refused_with_its_path(palette, path):
    assert path in [p for p, _ in palette_problems(palette)]


def test_a_good_scheme_is_accepted_with_hex_and_derived_words():
    palette = [{"name": "primary", "colour": "#1f3a5f"}, {"name": "dark", "colour": "accent_dark"}, {"name": "w", "colour": "white"}]
    assert palette_problems(palette) == []


@pytest.mark.parametrize("word", ["#475569", "#abc", "accent", "accent_light", "white", "none", "primary", "tint"])
def test_known_colour_words_are_accepted(word):
    assert colour_word_problem(word, known_names(None, [])) is None


def test_an_unknown_name_is_a_problem_only_where_the_organisations_names_are_known():
    assert colour_word_problem("ghost", None) is None  # not known here: the save and the run decide
    assert "no colour called ghost" in colour_word_problem("ghost", known_names(None, []))
    assert colour_word_problem("ghost", known_names([{"name": "ghost", "colour": "#000000"}], [])) is None
    assert colour_word_problem("ghost", known_names(None, ["ghost"])) is None
    assert colour_word_problem("Red!", None) is not None and colour_word_problem("#12345", None) is not None


def test_none_can_be_refused_where_a_colour_is_required():
    assert colour_word_problem("none", None, allow_none=False) is not None


# ---- the tree ----------------------------------------------------------------------------------------------------


def test_a_shape_may_use_a_scheme_name_and_a_standard_name():
    assert_valid(shape_tree([{"name": "warn", "colour": "#b45309"}], fill="warn", outline="primary"), organization_colours=[])


def test_a_name_used_but_not_in_any_scheme_is_refused_with_the_blocks_path_when_the_organisation_is_known():
    assert ("nodes[0].fill", "There is no colour called warn in this layout's scheme or the organisation's.") in errors_of(
        shape_tree(fill="warn"), organization_colours=[]
    )
    assert_valid(shape_tree(fill="warn"))  # no organisation at hand: accepted unchecked


def test_removing_a_scheme_name_that_a_block_still_uses_is_a_checked_problem():
    with_name = shape_tree([{"name": "warn", "colour": "#b45309"}], fill="warn")
    assert_valid(with_name, organization_colours=[])
    without = {k: v for k, v in with_name.items() if k != "palette"}
    assert [p for p, _ in errors_of(without, organization_colours=[])] == ["nodes[0].fill"]
    assert_valid(without, organization_colours=["warn"])  # the organisation's scheme still has it


def test_a_scheme_is_only_for_a_document_layout():
    tree = {**empty_tree("table"), "palette": [{"name": "a", "colour": "#000000"}]}
    assert "palette" in [p for p, _ in errors_of(tree)]


def test_the_scheme_in_the_tree_is_checked_for_its_entries():
    assert "palette[0].name" in [p for p, _ in errors_of(shape_tree([{"name": "white", "colour": "#000000"}]))]


# ---- the text view -----------------------------------------------------------------------------------------------


def test_the_text_view_round_trips_a_scheme_and_names_in_blocks():
    text = ("@layout document\n@palette primary=#1f3a5f secondary=accent warn=#b45309\n\n"
            "@shape rectangle fill primary outline warn width 3 height 1\n")
    parsed = parse_text(text)
    assert parsed.errors == []
    assert parsed.tree["palette"] == [
        {"name": "primary", "colour": "#1f3a5f"}, {"name": "secondary", "colour": "accent"}, {"name": "warn", "colour": "#b45309"},
    ]
    assert format_tree(parsed.tree) == text


def test_palette_follow_is_the_same_as_no_scheme_and_writes_nothing():
    parsed = parse_text("@layout document\n@palette follow\n\n@shape rectangle width 3 height 1\n")
    assert parsed.errors == [] and "palette" not in parsed.tree
    assert "@palette" not in format_tree(parsed.tree)


@pytest.mark.parametrize(
    "line",
    ["@palette", "@palette primary", "@palette =#fff", "@palette a=red", "@palette a=#000000 a=#ffffff", "@palette follow extra"],
)
def test_a_bad_palette_line_is_reported_on_its_line(line):
    parsed = parse_text(f"@layout document\n{line}\n")
    assert parsed.errors and parsed.errors[0].line == 2


def test_a_palette_is_written_once_and_before_the_first_block():
    twice = parse_text("@layout document\n@palette a=#000000\n@palette follow\n")
    assert twice.errors and "once" in twice.errors[0].message
    late = parse_text("@layout document\n@shape rectangle width 3 height 1\n@palette a=#000000\n")
    assert late.errors and "before the first block" in late.errors[0].message


# ---- the organisation's scheme, a run and provenance -------------------------------------------------------------


def put_scheme(world, scheme: list[dict[str, str]]):  # noqa: F811
    return world.client.put(
        f"/api/v1/orgs/{world.org['id']}/branding", json={"report_colour_scheme": scheme}, headers=auth_headers(world.token)
    )


def test_the_organisation_keeps_its_scheme_and_a_bad_one_is_refused(world, db):  # noqa: F811
    good = [{"name": "primary", "colour": "#0a1b2c"}, {"name": "alert", "colour": "#cc0000"}]
    resp = put_scheme(world, good)
    assert resp.status_code == 200, resp.text
    assert resp.json()["report_colour_scheme"] == good
    assert db.get(Organization, uuid.UUID(world.org["id"])).report_colour_scheme == good
    assert put_scheme(world, [{"name": "accent", "colour": "#000000"}]).status_code == 422
    assert put_scheme(world, [{"name": "a", "colour": "red"}]).status_code == 422
    assert put_scheme(world, [{"name": "a", "colour": "#000000"}] * 2).status_code == 422
    assert world.client.get(f"/api/v1/orgs/{world.org['id']}", headers=auth_headers(world.token)).json()["report_colour_scheme"] == good
    assert put_scheme(world, []).json()["report_colour_scheme"] is None  # an empty list clears it


def test_a_branding_update_that_does_not_mention_the_scheme_leaves_it(world):  # noqa: F811
    put_scheme(world, [{"name": "alert", "colour": "#cc0000"}])
    resp = world.client.put(
        f"/api/v1/orgs/{world.org['id']}/branding", json={"header_title": "Hi"}, headers=auth_headers(world.token)
    )
    assert resp.json()["report_colour_scheme"] == [{"name": "alert", "colour": "#cc0000"}]


def test_a_run_resolves_a_name_layout_first_then_organisation_then_the_standard_set(world, db):  # noqa: F811
    organization = db.get(Organization, uuid.UUID(world.org["id"]))
    organization.report_accent_color_hex = "#0a1b2c"
    organization.report_colour_scheme = [{"name": "alert", "colour": "#cc0000"}, {"name": "primary", "colour": "#00aa00"}]
    db.commit()
    project = world.project("Alpha")
    own = shape_tree([{"name": "alert", "colour": "#0000dd"}], fill="alert", outline="primary")
    html = preview(world, project, own)["html"]
    assert 'fill="#0000dd"' in html and 'stroke="#00aa00"' in html  # the layout's alert, the organisation's primary
    follow = preview(world, project, shape_tree(fill="alert", outline="tint"))["html"]
    assert 'fill="#cc0000"' in follow  # the organisation's alert
    standard = preview(world, project, shape_tree(fill="secondary"))["html"]
    assert 'fill="#081421"' in standard  # accent_dark of #0a1b2c


def test_a_saved_run_records_the_colours_it_actually_used(world, db):  # noqa: F811
    organization = db.get(Organization, uuid.UUID(world.org["id"]))
    organization.report_accent_color_hex = "#0a1b2c"
    organization.report_colour_scheme = [{"name": "alert", "colour": "#cc0000"}]
    db.commit()
    project = world.project("Alpha")
    h = auth_headers(world.token)
    tree = shape_tree([{"name": "own", "colour": "accent_dark"}], fill="alert", outline="own")
    made = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts", json={"name": "Used", "description": "", "family": "document", "tree": tree}, headers=h
    )
    assert made.status_code == 201, made.text
    run = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{made.json()['id']}/run", params={"format": "html"}, headers=h
    )
    assert run.status_code == 200, run.text
    row = db.scalars(
        select(GeneratedReport).where(GeneratedReport.layout_id == uuid.UUID(made.json()["id"])).order_by(GeneratedReport.created_at.desc())
    ).first()
    assert row.stats["colours"] == {"alert": "#cc0000", "own": "#081421"}  # only names, as they resolved in that run


def test_a_name_the_organisation_no_longer_has_is_refused_at_save_and_at_run(world, db):  # noqa: F811
    organization = db.get(Organization, uuid.UUID(world.org["id"]))
    organization.report_colour_scheme = [{"name": "alert", "colour": "#cc0000"}]
    db.commit()
    project = world.project("Alpha")
    h = auth_headers(world.token)
    body = {"name": "Uses alert", "description": "", "family": "document", "tree": shape_tree(fill="alert")}
    made = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts", json=body, headers=h)
    assert made.status_code == 201, made.text
    layout = made.json()
    put_scheme(world, [{"name": "other", "colour": "#000000"}])
    run = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": "html"}, headers=h
    )
    assert run.status_code == 422 and "no colour called alert" in run.text and "nodes[0].fill" in run.text
    bad = {**body, "name": "Uses ghost", "tree": shape_tree(fill="ghost")}
    refused = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts", json=bad, headers=h)
    assert refused.status_code == 422 and "nodes[0].fill" in refused.text
    check = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts/validate", json={"tree": bad["tree"]}, headers=h)
    assert check.status_code == 200 and check.json()["ok"] is False and check.json()["errors"][0]["path"] == "nodes[0].fill"


def test_the_standard_colours_are_the_four_the_plan_names():
    assert tuple(STANDARD_COLOURS) == ("primary", "secondary", "tint", "neutral")


def test_the_designer_is_told_the_branding_colour_and_the_schemes_at_both_levels(world, db):  # noqa: F811
    organization = db.get(Organization, uuid.UUID(world.org["id"]))
    organization.report_accent_color_hex = "#0a1b2c"
    organization.report_colour_scheme = [{"name": "alert", "colour": "#cc0000"}]
    db.commit()
    project = world.project("Alpha")
    h = auth_headers(world.token)
    expected = {
        "accent": "#0a1b2c", "organization_scheme": [{"name": "alert", "colour": "#cc0000"}],
        "standard": [{"name": n, "colour": c} for n, c in STANDARD_COLOURS.items()],
    }
    assert world.client.get(f"/api/v1/orgs/{world.org['id']}/report-layouts/colours", headers=h).json() == expected
    assert world.client.get(f"/api/v1/projects/{project['id']}/report-layouts/colours", headers=h).json() == expected
