"""Tests for the width and vertical alignment of the cells of a running header or footer: the tree rules, the text view,
the neutral model (with mirroring) and `resolve_band_cells`, the one rule every renderer reads."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.report_band_cells import MIN_COLUMN_CM, resolve_band_cells
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import assert_valid
from app.services.report_model import RunningBand
from tests.test_report_styles import errors_of, styled_tree

USABLE = 17.0
LONG = "Project overview - Ballard Engineering Programme Delivery Office"


def widths_of(band: RunningBand, usable: float = USABLE) -> list[float]:
    return [cell.width_cm for cell in resolve_band_cells(band, usable)]


def valigns_of(band: RunningBand) -> list[str]:
    return [cell.valign for cell in resolve_band_cells(band, USABLE)]


# ---- the resolver -------------------------------------------------------------------------------------------------


def test_the_cells_always_add_up_to_the_band():
    for band in (
        RunningBand(), RunningBand(left=("a",), centre=(LONG,), right=("b",)),
        RunningBand(widths=("30%", None, "4 cm")), RunningBand(left=("x",), widths=("20%", None, None)),
    ):
        assert sum(widths_of(band)) == pytest.approx(USABLE)


def test_short_side_cells_shrink_and_the_centre_takes_the_room():
    left, centre, right = widths_of(RunningBand(left=("Ballard",), centre=("Project overview",), right=("Page 1",)))
    assert centre > left and centre > right
    assert centre > USABLE / 3
    assert left < USABLE / 3 and right < USABLE / 3


def test_a_long_centre_wraps_in_the_centre_only_and_the_sides_keep_their_width():
    short = widths_of(RunningBand(left=("Ballard",), centre=("Title",), right=("Page 1",)))
    long = widths_of(RunningBand(left=("Ballard",), centre=(LONG * 3,), right=("Page 1",)))
    assert long[0] == pytest.approx(short[0]) and long[2] == pytest.approx(short[2])
    assert sum(long) == pytest.approx(USABLE)


def test_an_empty_cell_takes_only_its_floor():
    left, centre, right = widths_of(RunningBand(left=("Ballard",), right=("Page 1",)))
    assert centre == pytest.approx(MIN_COLUMN_CM, abs=0.5)
    assert left + right > USABLE - 2


def test_a_band_with_no_content_still_has_three_cells():
    assert sum(widths_of(RunningBand())) == pytest.approx(USABLE)


def test_a_fixed_percentage_and_a_fixed_length_are_kept():
    left, centre, right = widths_of(RunningBand(left=("a",), centre=("b",), right=("c",), widths=("25%", None, "4 cm")))
    assert left == pytest.approx(USABLE * 0.25)
    assert right == pytest.approx(4.0)
    assert centre == pytest.approx(USABLE - left - right)


def test_two_fixed_cells_leave_the_third_the_rest():
    widths = widths_of(RunningBand(centre=("b",), widths=("20%", None, "30%")))
    assert widths == pytest.approx([USABLE * 0.2, USABLE * 0.5, USABLE * 0.3])


def test_a_logo_cell_with_a_fixed_width_keeps_it():
    assert widths_of(RunningBand(left=("Ballard",), widths=("6 cm", None, None)))[0] == pytest.approx(6.0)


def test_widths_that_cannot_fit_are_squeezed_rather_than_overflowing():
    widths = widths_of(RunningBand(widths=("80%", "80%", None)))
    assert sum(widths) == pytest.approx(USABLE)
    assert min(widths) >= MIN_COLUMN_CM - 1e-9


@pytest.mark.parametrize("spec", ["0 cm", "0%", "0.01 mm", "9" * 400 + " cm"])
def test_a_stored_width_the_check_would_refuse_never_reaches_a_renderer_as_zero_or_infinite(spec):
    widths = widths_of(RunningBand(left=("a",), widths=(spec, None, None)))
    assert all(w >= MIN_COLUMN_CM - 1e-9 and w < float("inf") for w in widths)
    assert sum(widths) == pytest.approx(USABLE)


def test_the_default_alignment_is_top_and_a_cell_can_override_it():
    band = RunningBand(left=("a",), valigns=(None, "bottom", None))
    assert valigns_of(band) == ["top", "bottom", "top"]
    assert valigns_of(RunningBand(valign="middle", valigns=("bottom", None, None))) == ["bottom", "middle", "middle"]


def test_a_footer_defaults_to_the_bottom_and_a_header_to_the_top():
    assert valigns_of(RunningBand(left=("a",))) == ["top"] * 3
    assert valigns_of(RunningBand(left=("a",), kind="header")) == ["top"] * 3
    assert valigns_of(RunningBand(left=("a",), kind="footer")) == ["bottom"] * 3


def test_a_footers_own_choices_win_over_its_default_and_an_explicit_top_is_kept():
    assert valigns_of(RunningBand(kind="footer", valign="top")) == ["top"] * 3
    assert valigns_of(RunningBand(kind="footer", valigns=("middle", None, "top"))) == ["middle", "bottom", "top"]
    assert valigns_of(RunningBand(kind="footer", valign="middle", valigns=(None, None, "top"))) == ["middle", "middle", "top"]


def test_the_kind_survives_mirroring_so_a_left_hand_footer_still_sits_at_the_bottom():
    assert valigns_of(RunningBand(kind="footer", valigns=("middle", None, None)).mirrored()) == ["bottom", "bottom", "middle"]


def test_a_mirrored_page_swaps_the_left_and_right_widths_and_alignments():
    band = RunningBand(left=("a",), right=("b",), widths=("20%", None, "4 cm"), valigns=("bottom", None, "middle"))
    flipped = band.mirrored()
    assert flipped.widths == ("4 cm", None, "20%") and flipped.valigns == ("middle", None, "bottom")
    assert widths_of(flipped)[0] == pytest.approx(4.0)


def test_the_same_page_number_width_is_measured_for_a_page_field():
    from app.services.report_model import PageField

    fixed = widths_of(RunningBand(right=("Page 1",)))[2]
    field = widths_of(RunningBand(right=("Page ", PageField.PAGE)))[2]
    assert field == pytest.approx(fixed, abs=0.3)


# ---- the tree rules -----------------------------------------------------------------------------------------------


def with_band(**band: Any) -> dict[str, Any]:
    return styled_tree(header={"left": "a", "centre": "b", "right": "c", **band})


@pytest.mark.parametrize("band", [
    {"left_width": "25%"}, {"centre_width": "4 cm"}, {"right_width": "40 mm", "left_width": "10%"},
    {"valign": "middle"}, {"left_valign": "bottom", "valign": "top"},
])
def test_a_band_may_fix_a_cell_width_and_set_an_alignment(band):
    assert_valid(with_band(**band), organization_colours=())


@pytest.mark.parametrize(("band", "path", "fragment"), [
    ({"left_width": "wide"}, "header.left_width", "percentage"),
    ({"left_width": "0%"}, "header.left_width", "percentage"),
    ({"left_width": "101%"}, "header.left_width", "percentage"),
    ({"centre_width": "1 mm"}, "header.centre_width", "length"),
    ({"centre_width": "0 cm"}, "header.centre_width", "length"),
    ({"left_width": "0 mm"}, "header.left_width", "length"),
    ({"right_width": "9" * 400 + " cm"}, "header.right_width", "length"),
    ({"right_width": 20}, "header.right_width", "percentage"),
    ({"valign": "centre"}, "header.valign", "top, middle, bottom"),
    ({"right_valign": "up"}, "header.right_valign", "top, middle, bottom"),
])
def test_a_bad_width_or_alignment_is_refused_with_its_path(band, path, fragment):
    found = errors_of(with_band(**band), organization_colours=())
    assert any(p == path and fragment in m for p, m in found), found


@pytest.mark.parametrize("band", [
    {"left_width": "60%", "centre_width": "40%"},            # nothing left for the right cell
    {"left_width": "50%", "centre_width": "50%", "right_width": "10%"},
    {"left_width": "30 cm"},                                  # wider than the page
    {"left_width": "9 cm", "right_width": "9 cm"},            # the centre keeps less than the floor
])
def test_fixed_widths_that_fill_or_pass_the_band_are_refused(band):
    assert errors_of(with_band(**band), organization_colours=())


def test_fixed_widths_that_leave_room_are_accepted_and_the_check_uses_each_styles_width():
    assert_valid(with_band(left_width="40%", right_width="40%"), organization_colours=())
    narrow = styled_tree(
        header={"left": "a", "left_width": "11 cm"},
        page_styles=[{"name": "Small", "page_size": "A5"}],
    )
    assert errors_of(narrow, organization_colours=())


# ---- the text view ------------------------------------------------------------------------------------------------


def test_the_text_view_writes_and_reads_widths_and_alignments_exactly():
    tree = with_band(left_width="20%", right_width="4 cm", left_valign="bottom", valign="middle")
    text = format_tree(tree)
    assert "leftwidth 20%" in text and "rightwidth 4 cm" in text and "leftvalign bottom" in text and "valign middle" in text
    assert parse_text(text).tree["header"] == tree["header"]


def test_a_cell_may_have_a_width_and_no_text():
    result = parse_text('@layout document\n@header centre "x" rightwidth 25%\n@text\nhi\n@end\n')
    assert result.tree["header"] == {"centre": "x", "right_width": "25%"}


@pytest.mark.parametrize(("line", "message"), [
    ('@header left "x" leftwidth', "width"),
    ('@header left "x" leftwidth wide', "percentage"),
    ('@header left "x" leftwidth 20% leftwidth 30%', "once"),
    ('@header left "x" valign sideways', "top, middle or bottom"),
    ('@header left "x" valign top valign top', "once"),
])
def test_text_view_mistakes_in_a_width_or_alignment_are_reported(line, message):
    result = parse_text(f"@layout document\n{line}\n@text\nhello\n@end\n")
    assert result.tree is None and any(message in e.message for e in result.errors), result.errors


def test_auto_leaves_a_cell_with_no_fixed_width():
    result = parse_text('@layout document\n@header left "x" leftwidth auto\n@text\nhi\n@end\n')
    assert result.tree["header"] == {"left": "x"}
