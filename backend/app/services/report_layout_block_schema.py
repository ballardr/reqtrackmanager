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
    "number",  # a decimal, within `minimum` and `maximum`
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
    "page_style",  # the name of one of the layout's page styles
    "margins",  # the margins of a page: top, bottom, left, right and a gutter, in cm
    "page_styles",  # the layout's named page styles
    "running_band",  # a header or footer: left, centre and right text, a logo and whether the first page shows it
    "image",  # a picture from the layout tier's image library (a file id)
    "text_list",  # a list of short texts, one per line
    "file_name",  # a file name template: one line of text with the placeholders a file name allows and a live example
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
        minimum / maximum: Bounds of an integer or number.
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
    minimum: float | None = None
    maximum: float | None = None
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
        "page_size", "Page size", "choice", choices=("A3", "A4", "A5", "Letter", "Legal"), default="A4",
        help="The paper size of PDF, Word and OpenDocument output. A table layout has no pages.", families=("document",),
    ),
    BlockField(
        "margins", "Margins", "margins",
        help="The white space round the text of the layout's own pages, in cm (1 to 10; the gutter 0 to 5). "
        "A page style can set its own.", families=("document",),
    ),
    BlockField(
        "mirror_margins", "Mirror margins", "boolean",
        help="For double-sided printing: left and the gutter become the inner edge and right the outer, so they swap on "
        "facing pages. Applies to every page style.", families=("document",),
    ),
    BlockField(
        "page_styles", "Page styles", "page_styles",
        help="Named page styles (paper, orientation, margins) that a section block lays its contents out in, for example "
        "an A3 landscape table inside an A4 portrait report. A style leaves out what it shares with the layout.",
        families=("document",),
    ),
    BlockField(
        "header", "Header", "running_band",
        help="Text printed at the top of every page, in a left, centre and right cell: {{report_title}}, {{project_code}}, "
        "{{page}} and so on. A page style that sets none uses this one.", families=("document",),
    ),
    BlockField(
        "footer", "Footer", "running_band",
        help="Text printed at the bottom of every page, in a left, centre and right cell, for example \"Page {{page}} of {{pages}}\". "
        "A page style that sets none uses this one. With none here, the report template's footer text and a page number print.",
        families=("document",),
    ),
    BlockField(
        "file_name", "File name", "file_name", max_length=200,
        help="What a downloaded or stored copy of this report is called, without the extension, for example "
        "{{project_code}}-{{report_title}}-{{generated_on}}. It may use {{report_title}}, {{project_name}}, {{project_code}}, "
        "{{organisation}}, {{generated_on}}, {{layout_version}}, {{format}} and {{var.name}} for a variable. "
        "Left empty, the organisation's default name applies.",
    ),
    BlockField(
        "variables", "Variables", "variables",
        help="Values the person running the report chooses, for example which categories to include. "
        "They narrow what the report shows; they are not access control.",
    ),
)
