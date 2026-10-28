"""
Module: services.report_layout_block_schema

The editor-facing description of a layout block type: the fields a person fills in, the kind of control each
needs, the lists of child blocks it holds and the name it brings into scope. The visual designer (block outline,
rich-text view) renders its forms from this, so a block type registered by a module needs no frontend edit.

Responsibilities:
- Define the vocabulary (`BlockField`, `BlockContainer`, `BlockProvides`, `BlockSchema`) and the field `kind`s the
  designer has a control for (`FIELD_KINDS`).
- Describe the layout-level fields (`LAYOUT_FIELDS`: orientation, variables).

Design decisions:
- **A description, not a validator.** `BlockSpec.validate` stays the only judge of a node; a schema only tells the
  editor what to offer, so the two cannot disagree about what is saved. A schema that is out of step shows up as
  the server's own error on the card.
- **Composite kinds are named, not nested.** A source, a column list, a condition or a widget's settings is one
  `kind` with its own editor, because each has structure (a source reads the names in scope) that a generic
  field-by-field form would lose. A module block type builds its form from these kinds; a kind the designer does
  not know is shown as JSON, checked by the server.
- **Text is English**, like the validator's messages; the designer does not translate server text.

Dependencies: none (pure data; `services.report_layout_tree` registers the core schemas).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The `kind`s of field the designer draws a control for. Anything else falls back to a JSON editor.
FIELD_KINDS: tuple[str, ...] = (
    "text",  # one line
    "longtext",  # several lines
    "integer",
    "boolean",
    "choice",  # one of `choices`
    "tex",  # one line of TeX
    "alias",  # a name this block brings into scope
    "record_field",  # a field of the record type named by the field `depends_on`
    "source",  # where records come from (record type, link, group, where, sort)
    "columns",  # the columns of a table or sheet
    "joins",  # a sheet's joins
    "condition",  # a condition (a leaf, or all / any / not)
    "widget_key",  # which report component a widget embeds
    "widget_params",  # that component's settings (depends on the widget key)
    "widget_sort",  # sort keys of a widget's table
    "variables",  # a layout's run-time variables
)


@dataclass(frozen=True)
class BlockField:
    """One key of a block (or of the layout) as the editor offers it.

    Attributes:
        key: The key in the node.
        label: What the editor calls it.
        kind: One of `FIELD_KINDS`.
        required: Whether the node must carry it.
        help: One or two sentences: what it is and what it affects.
        max_length: Longest text accepted (text kinds).
        minimum / maximum: Bounds of an integer.
        default: What the evaluator assumes when the key is absent (shown as a placeholder), if it differs from empty.
        choices: The values of a `choice`.
        features: What a text may contain: `placeholders` (`{{record.field}}`), `math` (`\\( \\)`), `markdown`.
        depends_on: The key of a sibling field this one reads (a `record_field` names its source; widget settings
            name the widget).
        families: Layout families it applies to; empty means all.
    """

    key: str
    label: str
    kind: str
    required: bool = False
    help: str = ""
    max_length: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    default: Any = None
    choices: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    depends_on: str | None = None
    families: tuple[str, ...] = ()


@dataclass(frozen=True)
class BlockContainer:
    """A list of child blocks a block holds (`children`, and an `if`'s `else_children`)."""

    key: str
    label: str


@dataclass(frozen=True)
class BlockProvides:
    """A name the block brings into scope for the blocks inside it.

    Attributes:
        key: The key holding the name (`as`).
        kind: `record` (one record of the source's type) or `group` (a bucket of them).
        default: The name used when the key is absent.
    """

    key: str
    kind: str
    default: str


@dataclass(frozen=True)
class BlockSchema:
    """What the editor needs to offer a block type.

    Attributes:
        label: Display name ("Heading", "For each record").
        description: One line about what it does.
        fields: The block's keys, in the order the form shows them.
        containers: Child lists, in the order they are shown.
        provides: The name it brings into scope, if any.
        template: The node a new block starts as. May fail validation until the author fills it in.
    """

    label: str
    description: str
    fields: tuple[BlockField, ...] = ()
    containers: tuple[BlockContainer, ...] = ()
    provides: BlockProvides | None = None
    template: dict[str, Any] = field(default_factory=dict)


#: Fields of the layout itself, beside its blocks.
LAYOUT_FIELDS: tuple[BlockField, ...] = (
    BlockField(
        "orientation", "Page orientation", "choice", choices=("portrait", "landscape"), default="portrait",
        help="How pages are laid out in PDF and Word output. A table layout has no pages.", families=("document",),
    ),
    BlockField(
        "variables", "Variables", "variables",
        help="Values the person running the report chooses, for example which categories to include. "
        "They narrow what the report shows; they are not access control.",
    ),
)
