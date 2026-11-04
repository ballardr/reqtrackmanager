"""
Module: services.report_layout_block_schema

The editor-facing description of a layout block type: the fields a person fills in, the kind of control each
needs, the lists of child blocks it holds and the name it brings into scope. The visual designer (block outline,
rich-text view) renders its forms from this, so a block type registered by a module needs no frontend edit.

Responsibilities:
- Define the vocabulary (`BlockField`, `BlockGroup`, `BlockContainer`, `BlockProvides`, `BlockSchema`) and the field
  `kind`s the designer has a control for (`FIELD_KINDS`).
- Say how a long form is arranged (`BlockSchema.groups`, `BlockField.group` / `basic` / `control` / `inline`) and check a
  schema's declaration (`arrangement_problems`).
- Describe the layout-level fields (`LAYOUT_FIELDS`: orientation, variables).

Design decisions:
- **A description, not a validator.** `BlockSpec.validate` stays the only judge of a node; a schema only tells the
  editor what to offer, so the two cannot disagree about what is saved. A schema that is out of step shows up as
  the server's own error on the card.
- **Composite kinds are named, not nested.** A source, a column list, a condition or a widget's settings is one
  `kind` with its own editor, because each has structure (a source reads the names in scope) that a generic
  field-by-field form would lose. A module block type builds its form from these kinds; a kind the designer does
  not know is shown as JSON, checked by the server.
- **Arrangement is declared, not drawn per type.** A schema names its collapsible groups and each field names its
  group, so a block type registered by a module is arranged by the same designer code with no core edit. A schema
  that declares no groups is drawn flat.
- **Text is English**, like the validator's messages; the designer does not translate server text.

Dependencies: none (pure data; `services.report_layout_tree` registers the core schemas).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.report_layout import RUN_SCOPE_ANY, RUN_SCOPES

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
    "colour",  # a colour word: a hex colour, a reserved word (accent, white, ...) or a name in the layout's colour scheme
    "palette",  # the layout's colour scheme: up to 8 named colours
    "font",  # a font key (sans, serif, mono, unicode or a family the server administrator provides); empty inherits
    "document_styles",  # the layout's body and heading fonts (family, size, weight, slant, colour)
    "grid_columns",  # the columns of a custom table: width and the style their cells start from
    "grid_rows",  # the rows and cells of a custom table
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
        features: What a text may contain: `placeholders` (`{{record.field}}`), `math` (`\\( \\)`), `markdown`, `marks` (only `**bold**`,
            `*italic*` and `code` marks: the form offers Bold and Italic buttons).
        depends_on: The key of a sibling field this one reads (a `record_field` names its source; widget settings
            name the widget).
        families: Layout families it applies to; empty means all.
        empty_label: What an empty value means, in a word ("Auto"); the editor shows it in the empty box so the state is visible.
        group: The key of the `BlockGroup` it sits in; empty means the form's basic part (always visible).
        basic: Marks a field that stays visible although the form is arranged in groups. In a form that declares
            groups every field is in a group or basic, so the author decides each one; a basic field in a group is a mistake.
        control: How the editor draws it when the kind's usual control is not the best one: `choice-buttons` (an
            exclusive choice of up to four short values as a button group; a `choice`, or an `integer` with a
            `minimum` and `maximum` four apart or less) or `toggle` (a `boolean` as a pressed/unpressed button).
            Empty uses the kind's usual control. The stored value is the same either way.
        inline: Drawn on the same row as the field before it (a value and its unit). It must follow a field of the same
            group that is not itself inline; the editor stacks the two when the panel is too narrow.
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
    empty_label: str = ""
    group: str = ""
    basic: bool = False
    control: str = ""
    inline: bool = False


@dataclass(frozen=True)
class BlockGroup:
    """A collapsible group of a block's fields.

    Attributes:
        key: What `BlockField.group` names; also part of the key the person's open/closed choice is remembered under.
        label: The group's title on its bar.
        open: Whether it starts open (a block with no basic part, so the form is not a column of closed bars). A
            person's own choice wins.
    """

    key: str
    label: str
    open: bool = False


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
        groups: The collapsible groups the fields are arranged in, in the order they are drawn, after the basic fields.
            Empty means the form is flat.
    """

    label: str
    description: str
    fields: tuple[BlockField, ...] = ()
    containers: tuple[BlockContainer, ...] = ()
    provides: BlockProvides | None = None
    template: dict[str, Any] = field(default_factory=dict)
    groups: tuple[BlockGroup, ...] = ()


#: The `control` hints the designer understands.
FIELD_CONTROLS: tuple[str, ...] = ("choice-buttons", "toggle")

#: The most values an exclusive choice may have and still be drawn as a button group.
MAX_CHOICE_BUTTONS = 4


def arrangement_problems(schema: BlockSchema) -> list[str]:
    """Mistakes in how a schema arranges its form; empty when it is sound.

    Checks that group keys are unique, that every field names a declared group (or none), that a `basic` field is in
    no group, that in an arranged form every field is in a group or marked basic, that each declared group holds at least one field,
    that an `inline` field follows a field of its own group, that a required field is not hidden in a group that starts
    closed (a person must not be able to miss a setting the block cannot do without) and that a `control` suits its field.

    Args:
        schema: The block schema to check.

    Returns:
        One sentence per mistake, naming the field or group.
    """
    problems: list[str] = []
    keys = [g.key for g in schema.groups]
    for key in {k for k in keys if keys.count(k) > 1}:
        problems.append(f"group {key!r} is declared twice")
    known = set(keys)
    starts_open = {g.key for g in schema.groups if g.open}
    used: set[str] = set()
    previous: BlockField | None = None
    for f in schema.fields:
        if f.inline and (previous is None or previous.inline or previous.group != f.group or previous.basic != f.basic):
            problems.append(f"field {f.key!r} is inline but does not follow a field of its own group")
        previous = f
        if f.group:
            used.add(f.group)
            if f.group not in known:
                problems.append(f"field {f.key!r} names group {f.group!r}, which the schema does not declare")
            if f.basic:
                problems.append(f"field {f.key!r} is basic but sits in group {f.group!r}")
            if f.required and f.group in known and f.group not in starts_open:
                problems.append(f"field {f.key!r} is required but sits in group {f.group!r}, which starts closed")
        if schema.groups and not f.group and not f.basic:
            problems.append(f"field {f.key!r} is neither in a group nor marked basic")
        if f.control and f.control not in FIELD_CONTROLS:
            problems.append(f"field {f.key!r} has unknown control {f.control!r}")
        if f.control == "toggle" and f.kind != "boolean":
            problems.append(f"field {f.key!r} is a toggle but its kind is {f.kind!r}, not boolean")
        if f.control == "choice-buttons":
            if f.kind == "choice":
                count = len(f.choices)
            elif f.kind == "integer" and f.minimum is not None and f.maximum is not None:
                count = int(f.maximum - f.minimum) + 1
            else:
                problems.append(f"field {f.key!r} has choice-buttons but its kind is {f.kind!r}")
                continue
            if not 2 <= count <= MAX_CHOICE_BUTTONS:
                problems.append(f"field {f.key!r} has choice-buttons for {count} values (2 to {MAX_CHOICE_BUTTONS} fit)")
    for key in keys:
        if key not in used:
            problems.append(f"group {key!r} holds no field")
    return problems


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
        "repeat_table_header", "Repeat table header rows", "boolean", default=True,
        help="Whether a table's column headings are printed again at the top of every page the table runs onto. On unless "
        "switched off; applies to every table in the layout.", families=("document",),
    ),
    BlockField(
        "align_tables", "Line up tables with the same columns", "boolean", default=True,
        help="Whether tables with the same column headings share one set of column widths, so they read as one list. On "
        "unless switched off; turn it off to let each table size its columns from its own content.", families=("document",),
    ),
    BlockField(
        "run_scope", "Projects it runs for", "choice", choices=RUN_SCOPES, default=RUN_SCOPE_ANY,
        empty_label="Not set (any number of projects)",
        help="Whether the report may cover several projects (an organisation-wide run merges them), exactly one project (for a "
        "sign-off sheet or a charter that names the project), or one project together with its child projects merged into the "
        "same report. A run that does not fit is refused.",
    ),
    BlockField(
        "palette", "Colour scheme", "palette",
        help="Named colours for this layout, so a block uses a colour by name (primary, warning) and changing the scheme changes "
        "every block that uses it. With none of its own the layout follows the organisation's scheme, then the standard four "
        "(primary, secondary, tint, neutral) taken from the branding colour.", families=("document",),
    ),
    BlockField(
        "styles", "Fonts", "document_styles",
        help="The document's body font and size, and its headings' font, weight, slant and colour, set once so every block "
        "follows. Left alone, each format keeps its own look. PDF always prints in the font chosen; Word, OpenDocument and the "
        "web page name it, so a reader without it sees a similar font unless Embed fonts is on.", families=("document",),
    ),
    BlockField(
        "table_header_fill", "Table heading fill", "colour", empty_label="Default (the organisation's accent)",
        help="The background of the heading row of every table in the layout, as a colour from the colour scheme or a hex colour. "
        "Set once instead of on each table. A custom table's own cell colours still win; left alone, headings use the "
        "organisation's accent colour.", families=("document",),
    ),
    BlockField(
        "table_header_text", "Table heading text colour", "colour", empty_label="Automatic (black or white, whichever reads best)",
        help="The text colour of table heading rows. Left alone it is chosen to contrast with the heading fill, so a light fill "
        "gets black text and a dark one white.", families=("document",),
    ),
    BlockField(
        "embed_fonts", "Embed fonts", "boolean", default=False,
        help="Put the font files of the extra fonts the server administrator provides inside Word and OpenDocument files, so they "
        "print the same where the font is not installed. The file grows by about 0.3 to 0.4 MB for each face used; the four "
        "standard fonts are never embedded, and Word on the web and some Mac versions ignore embedded fonts.", families=("document",),
    ),
    BlockField(
        "contents_sheet", "Contents sheet", "boolean", default=False,
        help="Start the workbook with a Contents sheet: one row per sheet, its name linking to the sheet, and how many rows "
        "it holds. Excel and OpenDocument spreadsheets link; a CSV zip gets a plain Contents file.", families=("table",),
    ),
    BlockField(
        "page_styles", "Page styles", "page_styles",
        help="Named page styles (paper, orientation, margins) that a section block lays its contents out in, for example "
        "an A3 landscape table inside an A4 portrait report. A style leaves out what it shares with the layout.",
        families=("document",),
    ),
    BlockField(
        "header", "Header", "running_band",
        help="Text printed at the top of every page, in a left, centre and right cell: {{report_title}}, {{project_report_name}}, "
        "{{page}}, the organisation's {{org.footer_text}} and so on; a logo may be the organisation's own (org_logo). "
        "Each cell fits its text unless given a width (left_width, centre_width, right_width: \"25%\" or \"4 cm\"); the cells sit at "
        "the top unless valign (top, middle, bottom) or left_valign, centre_valign, right_valign says otherwise. "
        "A page style that sets none uses this one.", families=("document",),
    ),
    BlockField(
        "footer", "Footer", "running_band",
        help="Text printed at the bottom of every page, in a left, centre and right cell, for example \"Page {{page}} of {{pages}}\". "
        "The cells sit at the bottom unless valign (top, middle, bottom) or left_valign, centre_valign, right_valign says otherwise. "
        "A page style that sets none uses this one. With none here, a page number prints. {{org.footer_text}} is the organisation's "
        "default footer text.",
        families=("document",),
    ),
    BlockField(
        "file_name", "File name", "file_name", max_length=200,
        help="What a downloaded or stored copy of this report is called, without the extension, for example "
        "{{project_code}}-{{report_title}}-{{generated_on}}. It may use {{report_title}}, {{project_name}}, "
        "{{project_report_name}}, {{project_code}}, {{organisation}}, {{generated_on}}, {{layout_version}}, {{format}} and "
        "{{var.name}} for a variable. "
        "Left empty, the organisation's default name applies.",
    ),
    BlockField(
        "variables", "Variables", "variables",
        help="Values the person running the report chooses, for example which categories to include. "
        "They narrow what the report shows; they are not access control.",
    ),
)
