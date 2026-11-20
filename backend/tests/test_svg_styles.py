"""Tests for `services.svg_styles`: a drawing's style sheet becomes attributes, following the CSS cascade, and what a printed
or embedded figure cannot use (animation, interaction, hidden elements, unresolved values) is dropped."""

from __future__ import annotations

import pytest
from lxml import etree

from app.services.svg_styles import flatten_styles

NS = 'xmlns="http://www.w3.org/2000/svg"'


def flat(body: str, css: str = "", root_attrs: str = "") -> etree._Element:
    """The flattened drawing as a parsed tree; `body` goes inside the root, `css` in a style element."""
    style = f"<style>{css}</style>" if css else ""
    return etree.fromstring(flatten_styles(f'<svg {NS} id="d" {root_attrs}>{style}{body}</svg>').encode())


def by_id(root: etree._Element, ident: str) -> etree._Element:
    found = root.xpath(f"//*[@id='{ident}']")
    assert found, f"no element {ident}"
    return found[0]


def test_a_class_rule_becomes_attributes_and_the_style_element_is_removed() -> None:
    root = flat('<rect id="r" class="node"/>', ".node{fill:#ff0000;stroke:#00ff00;stroke-width:2px}")

    assert by_id(root, "r").attrib["fill"] == "#ff0000"
    assert by_id(root, "r").attrib["stroke"] == "#00ff00"
    assert by_id(root, "r").attrib["stroke-width"] == "2px"
    assert not root.xpath("//*[local-name()='style']")


def test_the_higher_specificity_wins_and_a_later_rule_wins_a_tie() -> None:
    root = flat(
        '<rect id="a" class="x"/><rect id="b" class="x y"/>',
        ".x{fill:red}.x.y{fill:blue}#a{fill:green}.x{stroke:black}.x{stroke:white}",
    )

    assert by_id(root, "a").attrib["fill"] == "green"  # an id outweighs a class
    assert by_id(root, "b").attrib["fill"] == "blue"  # two classes outweigh one
    assert by_id(root, "a").attrib["stroke"] == "white"  # equal weight: the later rule


def test_important_beats_the_elements_own_style_which_beats_a_rule() -> None:
    root = flat(
        '<rect id="a" class="x" style="fill:yellow"/><rect id="b" class="y" style="fill:yellow"/>',
        ".x{fill:red!important}.y{fill:red}",
    )

    assert by_id(root, "a").attrib["fill"] == "red"
    assert by_id(root, "b").attrib["fill"] == "yellow"
    assert "style" not in by_id(root, "a").attrib and "style" not in by_id(root, "b").attrib


def test_descendant_and_attribute_selectors_apply() -> None:
    root = flat(
        '<g class="cluster"><rect id="in"/></g><rect id="out"/><circle id="c" data-kind="a"/>',
        '.cluster rect{fill:#111111}circle[data-kind="a"]{stroke:#222222}',
    )

    assert by_id(root, "in").attrib["fill"] == "#111111" and "fill" not in by_id(root, "out").attrib
    assert by_id(root, "c").attrib["stroke"] == "#222222"


def test_a_root_scoped_sheet_matches_through_the_drawings_own_id() -> None:
    root = flat('<g class="edge"><path id="p"/></g>', "#d .edge path{stroke:#333333}#d{font-size:16px}")

    assert by_id(root, "p").attrib["stroke"] == "#333333"
    assert root.attrib["font-size"] == "16px"


def test_states_animation_and_interaction_are_left_out() -> None:
    root = flat(
        '<rect id="r" class="n"/>',
        "@keyframes spin{from{opacity:0}}.n:hover{fill:red}.n{fill:blue;animation:spin 1s;cursor:pointer;position:absolute;transform:scale(2)}",
    )

    assert dict(by_id(root, "r").attrib) == {"id": "r", "class": "n", "fill": "blue"}


def test_var_is_resolved_from_the_sheet_with_a_fallback_and_an_unresolved_one_is_dropped() -> None:
    root = flat(
        '<text id="a" class="a"/><text id="b" class="b"/><text id="c" class="c"/>',
        ":root{--face:Verdana}.a{font-family:var(--face)}.b{font-family:var(--missing, Arial)}.c{font-family:var(--missing)}",
    )

    assert by_id(root, "a").attrib["font-family"] == "Verdana"
    assert by_id(root, "b").attrib["font-family"] == "Arial"
    assert "font-family" not in by_id(root, "c").attrib


def test_a_chain_of_var_references_stops_rather_than_looping() -> None:
    root = flat('<text id="t" class="t"/>', ":root{--a:var(--b);--b:var(--a)}.t{fill:var(--a)}")

    assert "fill" not in by_id(root, "t").attrib


def test_an_element_hidden_by_the_sheet_is_removed() -> None:
    root = flat('<g class="hidden"><rect id="gone"/></g><rect id="kept"/>', ".hidden{display:none}")

    assert not root.xpath("//*[@id='gone']") and by_id(root, "kept") is not None


def test_a_selector_the_engine_does_not_understand_skips_only_that_rule() -> None:
    root = flat('<rect id="r" class="n"/>', ".n::weird-thing{fill:red}.n{stroke:#444444}")

    assert by_id(root, "r").attrib.get("stroke") == "#444444"


def test_a_drawing_without_a_sheet_keeps_its_attributes_and_loses_a_style_attribute_it_applied() -> None:
    root = flat('<rect id="r" fill="#abcdef" style="stroke:#123456"/>')

    assert by_id(root, "r").attrib["fill"] == "#abcdef" and by_id(root, "r").attrib["stroke"] == "#123456"


@pytest.mark.parametrize("markup", ["<svg", "not xml at all", '<html xmlns="http://www.w3.org/1999/xhtml"/>'])
def test_markup_that_is_not_a_drawing_is_refused(markup: str) -> None:
    with pytest.raises(ValueError):
        flatten_styles(markup)


def test_a_drawing_that_declares_an_entity_is_refused() -> None:
    source = '<!DOCTYPE svg [<!ENTITY x "expanded">]>' + f'<svg {NS}><text id="t">&x;</text></svg>'

    with pytest.raises(ValueError, match="entity"):
        flatten_styles(source)
