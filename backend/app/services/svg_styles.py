"""
Module: services.svg_styles

Turns a drawing's `<style>` sheet into plain attributes on the elements it styles, so the drawing keeps its colours and
line styles after `report_svg.sanitize_svg` (which removes `style` elements) and inside an HTML page.

Responsibilities:
- `flatten_styles`: resolve per element which declarations apply (CSS cascade: specificity, order, `!important`, the
  element's `style` attribute), write drawing properties as attributes, remove `display: none` elements and drop the sheets.

Design decisions:
- Only drawing properties survive (`_PROPERTIES`: fill, stroke, line styles, font, text anchoring); layout, animation and
  interaction properties mean nothing in a printed figure and dropping them makes the result safe for the sanitiser.
- A real CSS parser (`tinycss2`) and selector engine (`cssselect2`) read the sheet, since Mermaid uses descendant, class,
  id, attribute and `:not()` selectors; an unsupported selector or `@` rule is skipped.
- `var()` values are substituted from the sheet's own custom properties; an unresolved one without fallback drops the declaration.
- Nothing is fetched or executed: parsing has entities and network off, and the sanitiser checks values again.

Dependencies: `lxml`, `tinycss2`, `cssselect2` (also what `svglib` reads style sheets with).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cssselect2
import tinycss2
from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"
#: The properties that are drawing, written back as attributes (a CSS property and its SVG presentation attribute share a name).
_PROPERTIES = frozenset({
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-linecap", "stroke-linejoin",
    "stroke-dasharray", "stroke-dashoffset", "stroke-miterlimit", "opacity", "font-family", "font-size", "font-weight",
    "font-style", "text-anchor", "dominant-baseline", "letter-spacing", "stop-color", "stop-opacity", "marker-start",
    "marker-mid", "marker-end", "rx", "ry",
})
#: The weight of an element's own `style` attribute: above any selector's specificity.
_INLINE = (99, 0, 0)
_VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*))?\)")
#: A hostile sheet could chain `var()` references; a value is resolved at most this many times.
_VAR_DEPTH = 5


@dataclass(frozen=True)
class _Declaration:
    """One declaration with the weight that decides the cascade (`important`, specificity, source order)."""

    name: str
    value: str
    weight: tuple[bool, tuple[int, int, int], int]


def _resolve_vars(value: str, custom: dict[str, str]) -> str | None:
    """`value` with each `var(--name, fallback)` replaced; `None` when one cannot be resolved."""
    for _ in range(_VAR_DEPTH):
        if "var(" not in value:
            return value
        missing = False

        def substitute(match: re.Match[str]) -> str:
            nonlocal missing
            found = custom.get(match.group(1), match.group(2))
            if found is None:
                missing = True
                return ""
            return found.strip()

        value = _VAR.sub(substitute, value)
        if missing:
            return None
    return None if "var(" in value else value


def _rules(css: str) -> list[tuple[str, list[tinycss2.ast.Declaration]]]:
    """The style rules of a sheet as (selector text, declarations), `@` rules left out."""
    rules: list[tuple[str, list[tinycss2.ast.Declaration]]] = []
    for rule in tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True):
        if rule.type != "qualified-rule":
            continue
        declarations = [
            item for item in tinycss2.parse_blocks_contents(rule.content, skip_comments=True, skip_whitespace=True)
            if item.type == "declaration"
        ]
        rules.append((tinycss2.serialize(rule.prelude).strip(), declarations))
    return rules


def _own_style(element: etree._Element) -> list[tuple[str, str, bool]]:
    """The declarations of an element's `style` attribute as (name, value, important)."""
    parsed = tinycss2.parse_blocks_contents(element.get("style", ""), skip_comments=True, skip_whitespace=True)
    return [
        (item.lower_name, tinycss2.serialize(item.value).strip(), item.important)
        for item in parsed if item.type == "declaration"
    ]


def flatten_styles(source: str) -> str:
    """The drawing with its style sheets applied as attributes and removed.

    Args:
        source: SVG markup (untrusted).

    Returns:
        SVG markup with no `style` element and no `style` attribute, where every drawing property the sheet or the
        attribute set on an element is an attribute of that element, and elements hidden with `display: none` removed.

    Raises:
        ValueError: The markup declares an entity, is not well-formed XML, or its root is not an `svg` element.
    """
    if "<!entity" in source.lower():
        raise ValueError("The SVG may not declare an entity.")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False,
        remove_comments=True, remove_pis=True,
    )
    try:
        root = etree.fromstring(source.encode("utf-8"), parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise ValueError("The SVG is not well-formed.") from exc
    if etree.QName(root).localname != "svg":
        raise ValueError("The document is not an SVG.")

    sheets = [element for element in root.iter() if isinstance(element.tag, str) and etree.QName(element).localname == "style"]
    rules = [rule for sheet in sheets for rule in _rules(sheet.text or "")]
    custom = {
        item.name: tinycss2.serialize(item.value).strip()
        for _, declarations in rules for item in declarations if item.name.startswith("--")
    }
    matcher = cssselect2.Matcher()
    for selector, declarations in rules:
        try:
            compiled = cssselect2.compile_selector_list(selector)
        except cssselect2.SelectorError:
            continue  # a state or a feature a figure cannot have (`:hover`)
        payload = [
            (item.lower_name, tinycss2.serialize(item.value).strip(), item.important)
            for item in declarations if not item.name.startswith("--")
        ]
        for selector_object in compiled:
            matcher.add_selector(selector_object, payload)

    hidden: list[etree._Element] = []
    for wrapper in cssselect2.ElementWrapper.from_xml_root(root).iter_subtree():
        element = wrapper.etree_element
        if not isinstance(element.tag, str):
            continue
        weighted: list[_Declaration] = []
        for specificity, order, pseudo, payload in matcher.match(wrapper):
            if pseudo is not None:
                continue
            for name, value, important in payload:
                weighted.append(_Declaration(name, value, (important, specificity, order)))
        for index, (name, value, important) in enumerate(_own_style(element)):
            weighted.append(_Declaration(name, value, (important, _INLINE, len(rules) + index)))
        decided: dict[str, _Declaration] = {}
        for declaration in sorted(weighted, key=lambda item: item.weight):
            decided[declaration.name] = declaration
        if "style" in element.attrib:
            del element.attrib["style"]
        shown = decided.get("display")
        if shown is not None and shown.value == "none":
            hidden.append(element)
            continue
        for name, declaration in decided.items():
            if name not in _PROPERTIES:
                continue
            resolved = _resolve_vars(declaration.value, custom)
            if resolved:
                element.set(name, resolved)

    for element in hidden:
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    for sheet in sheets:
        parent = sheet.getparent()
        if parent is not None:
            parent.remove(sheet)
    return etree.tostring(root, encoding="unicode")


__all__ = ["flatten_styles"]
