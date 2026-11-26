"""
Module: modules.traceability.rule_presets

The three ready-made traceability rules offered beside the full rule editor: no linking required, a link to a named record
type required, and a link to either of two record types required (a higher-level requirement type or, for example, an
applicable compliance requirement).

Responsibilities:
- Describe each preset for the editor (`PRESETS`) and build its `requires` tree from a few choices (`build_preset`).

Design decisions:
- A preset is a tree built over the same structure as every rule (`rule_tree`), so it can be opened and extended in the full
  editor; it has no behaviour of its own.
- "No linking required" builds no tree: the rule it stands for is no rule (or an informational rule with nothing to
  require), so applying it removes the requirement instead of storing an empty one.

Dependencies: `rule_tree`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.traceability import rule_tree
from app.modules.traceability.rule_tree import LinkLeaf, LinkTypes, Node, Target


@dataclass(frozen=True)
class Preset:
    """One preset rule for the editor.

    Attributes:
        key: Stable identifier.
        name: Formal display name.
        description: What the preset requires.
        needs_target: Whether the preset needs a target record type.
        needs_alternative: Whether it also needs a second record type.
    """

    key: str
    name: str
    description: str
    needs_target: bool
    needs_alternative: bool


PRESETS: tuple[Preset, ...] = (
    Preset("none", "No linking required", "No upstream link is required of the record.", False, False),
    Preset("type", "Type linking required", "The record must link to a record of the chosen type.", True, False),
    Preset(
        "type_or_alternative", "Either of two types linking required",
        "The record must link to a record of the chosen type or of the alternative type.", True, True,
    ),
)


def _leaf(
    artefact_type: str, subtype: str | None, link_type_ids: Sequence[uuid.UUID], minimum: int,
) -> LinkLeaf:
    link_types = LinkTypes("types", tuple(link_type_ids)) if link_type_ids else LinkTypes("any")
    return LinkLeaf(link_types=link_types, direction="outgoing", targets=(Target(artefact_type, subtype),), minimum=minimum)


def build_preset(
    key: str, *, target_type: str | None, target_subtype: str | None, alternative_type: str | None,
    alternative_subtype: str | None, link_type_ids: Sequence[uuid.UUID], minimum: int,
) -> dict[str, Any] | None:
    """The `requires` tree of a preset.

    Args:
        key: A key of `PRESETS`.
        target_type: The record type to link to.
        target_subtype: Its sub-type, or `None`.
        alternative_type: The second record type of `type_or_alternative`.
        alternative_subtype: Its sub-type, or `None`.
        link_type_ids: The link types that count, or empty for any link.
        minimum: The fewest links required.

    Returns:
        The tree as canonical JSON, or `None` for `none`.

    Raises:
        ValueError: For an unknown key or a record type the preset needs and was not given.
    """
    if key == "none":
        return None
    if key not in {p.key for p in PRESETS}:
        raise ValueError(f"{key!r} is not a preset.")
    if not target_type:
        raise ValueError("This preset needs a target record type.")
    node: Node = _leaf(target_type, target_subtype, link_type_ids, minimum)
    if key == "type_or_alternative":
        if not alternative_type:
            raise ValueError("This preset needs an alternative record type.")
        node = rule_tree.Group("any", (node, _leaf(alternative_type, alternative_subtype, link_type_ids, minimum)))
    return rule_tree.to_json(node)
