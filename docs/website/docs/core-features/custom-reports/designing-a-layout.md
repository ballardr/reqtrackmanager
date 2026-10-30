---
sidebar_position: 2
---

# Designing a layout

**Report Setup** lists a project's own layouts, those shared by its parent projects and by the organisation, and, for an organisation, its own, in one folder list with the report packs and the reports modules provide. **Search** (name, description or folder) and the **Type**, **Show** and **Shared from** filters narrow it. Choose **New**, then **New layout**, give it a name, optionally a **Folder** for the Reports picker (such as `Handover/Quarterly`, see [finding and organising reports](./organising-reports.md)) and say whether it is a **Document** (headings, text and tables, for PDF, Word or HTML) or a **Table** (one or more plain tables, for Excel or CSV); the kind cannot be changed later. A layout shared from elsewhere opens read-only: **Make a copy** to change it for this project, or **Hide in this project** and bring it back with **Add organisation defaults**.

The designer shows the layout in two views you can switch between at any time: **Text** and **Blocks**. In the text view each block is a line starting with `@`, and `{{req.title}}` puts a field of a record in the text.

| The text view: icon buttons for the blocks and the page setup, one block per line, problems listed by line, and a live preview beside it |
| --- |
| ![The layout designer in the text view with a requirements layout, the Fields tab and the preview](../../../static/img/screenshots/layout-designer-text.png) |

```text
@layout document

@heading Requirements of {{project_name}}

@each requirement sort title as req
  @heading level=2 {{req.code}} {{req.title}}
@end
```

```mermaid
flowchart LR
    T["Type the text, or build with blocks<br/>(insert a block, field or widget)"] --> C["Checked as you pause<br/>problems listed by line or on the block"]
    C -->|valid| P["Run preview<br/>real records, your access,<br/>nothing stored"]
    C -->|valid| S["Save new version<br/>(note optional)"]
    S --> H["History<br/>compare any two versions"]
    H -->|use an old version| T
```

- **Problems** are listed by line and column; choosing one puts the cursor there. **Save new version** and **Run preview** wait until the text is valid. A layout's first line must declare its own kind (`@layout document` or `@layout table`).
- The **icon buttons** above the text add a heading (of level 1, 2 or 3), text, *for each record*, a group, a table, an *if*, an equation or a page break at the cursor (a sheet for a table layout); hover or focus a button for its name. The **Page setup** button beside them opens a dialog for the [page setup](#page-setup): the page **size**, **orientation**, **margins** and **page styles**, written into the first lines of the text; the PDF, Word and OpenDocument files use them. The **Fields** tab is one searchable list of everything `{{…}}` can name at the cursor: the report and project values (`{{project_name}}`, `{{project_code}}`, `{{project_description}}`, `{{report_title}}`, `{{generated_on}}`, `{{organisation}}`) together with the fields of the names in scope (the name after `as` of the block you are in), each saying where it comes from. Search it, or use **From** to narrow it to the report and project values or to one name. The **Widgets** tab lists the report components you can embed as a tree: each module, then each of its reports, then the report's parts, all collapsed until you open them (a search opens every branch that still holds a match). Choose a part to see the report's settings and to insert the finished line.

| The Fields tab: report and project values and the fields of the names in scope, in one searchable list |
| --- |
| ![The designer's Fields tab listing the project name, code and description with a search box and a From filter](../../../static/img/screenshots/layout-designer-fields.png) |

| The Widgets tab: modules, reports and parts as a tree that starts collapsed |
| --- |
| ![The designer's Widgets tab with Decision Management and its Decision register open and the other modules collapsed](../../../static/img/screenshots/layout-designer-widgets.png) |

- **Blocks** shows the same layout as blocks, so you can build a layout without writing the `@` syntax, and it has the full width of the page. **Add block** lists the blocks (*Heading*, *Text* and *Table* first), and the line beside it says where the next one will go: after the selected block, inside it (a block that holds others, such as *for each record*, a group or an *if*, offers each of its lists) or at the end of the layout. The new block is selected at once, and **Ctrl+Z** (**Cmd+Z** on a Mac) takes it back. Drag blocks on the canvas to reorder them or drop them inside another block. Short settings (a heading's words and level, the name a *for each* gives each record) are on the block itself. **Select a block** to edit all its settings in the panel beside the canvas (under it on a narrow screen): *Linked from* lists the names of the enclosing blocks, and a filter offers the fields and operators that suit the field you chose. The arrow keys move around the blocks. A block with a problem shows a warning mark, and the message appears under the field in the panel; **Layout settings** at the top holds the page size and orientation, the margins, the [page styles](#page-setup) and the [variables](./blocks-widgets-and-variables.md#variables). The layout is checked as you pause, **Save new version** and **Run preview** wait until there are no problems, and switching to **Text** shows the same layout as text. You can switch from the text only while it reads without problems. A block dragged outside the layout is not part of it, and the panel says so. **Preview** opens the preview in a dialog; **Preview panel** keeps it open beside the blocks (your choice is remembered).

- **Preview** runs the layout as you, on the real records, and shows a document as it will print or a table layout's first rows of each sheet (with the real row count). It stores nothing, and a project preview can include child projects while an organisation preview can be limited to chosen projects.
- **Saving** adds a version: **Save new version** asks for an optional note in a small window, then saves. If somebody saved while you were editing, you are told and can reload their version; nothing is overwritten. Leaving with unsaved changes asks first.
- **History** lists every version and compares any two line by line (added lines start with `+`, removed with `-`). **Use this version as the new text** puts an old version in the editor; saving it adds a new version, so history is never rewritten.

| History: any two versions compared line by line |
| --- |
| ![The History tab comparing two versions of a layout](../../../static/img/screenshots/layout-designer-history.png) |

- Organisation administrators can design organisation layouts, and project administrators their own project's; others can run layouts but not open the designer.

Next: [blocks, report components and variables](./blocks-widgets-and-variables.md).

## Page setup

A document layout has its own pages (size, orientation and margins) and can name other **page styles** for parts of the report, for example an A3 landscape table inside an A4 portrait report.

```mermaid
flowchart LR
    A["Report pages<br/>A4 portrait"] --> B["Section 'Wide tables'<br/>A3 landscape<br/>on new pages"]
    B --> C["Report pages<br/>A4 portrait<br/>on a new page"]
```

- **Margins** are in centimetres on each side (1 to 10), with a **gutter** (0 to 5) of extra room on the binding side for punching or binding. Left out, every side is 1.5 cm and there is no gutter.
- **Mirror margins** is for double-sided printing: left and the gutter become the *inner* edge of every page and right the *outer*, so they swap sides on facing pages. It applies to every page style of the layout.
- A **page style** has a name, and optionally its own size, orientation and margins; whatever it leaves out is the layout's own. Add one in the Page setup dialog, or with a line in the text before the first block: `@pagestyle "Wide tables" landscape A3 margins left=1 right=1`.
- A **section** lays its contents out in one page style: `@section "Wide tables"` … `@end` in the text, or the *Section* block, which asks for the page style. The section starts on a new page, and the report goes back to its own page style on a new page after it. A section that shows nothing leaves no page behind, and a section cannot contain another.
- Every style must leave at least 5 cm of text width and height; a problem is listed under the field that causes it.
- PDF, Word and OpenDocument files have real pages in the sizes and margins you set. The HTML preview has no pages: a section appears as a box as wide as its page, labelled with the paper and margins, and printing the HTML page from a browser uses the same sizes. A table layout (CSV, Excel, ODS) has no pages, so it has no page setup.

## Images

An **Image** block puts a picture from the image library into the report, in line with the text.

- **Choose** the picture with *Choose image…*. The dialog lists the library (search by name) and lets you upload a PNG, JPEG, GIF, WebP or SVG file; the largest file allowed is shown in the dialog and set by your administrator (50 MB unless changed). A project layout can use its own project's pictures and the organisation's; an organisation layout can use the organisation's only, because every project runs it. An upload goes to the library of the layout you are editing, and the dialog says which.
- **Selecting a picture shows its details**: a larger preview, its size in pixels and, for a photograph, when it was taken (on the camera's own clock), the camera, any description saved in the file and where it was taken. Use these to tell photographs apart when their names do not. The same details are behind the *i* button beside a picture's name on the project's Files page, an organisation's shared resources and any list of attachments. Double-click a picture, or press *Use image*, to choose it.
- **Alternative text** says what the picture shows, for readers who cannot see it; it is required unless you tick *Decorative*.
- **Width** is in centimetres, millimetres or as a percentage of the text width and keeps the picture's shape; **height** is in centimetres or millimetres, and setting both stretches it. With no size the picture prints at its own size, never wider than the text.
- **Alignment** is left, centre or right. A **caption** can sit above or below the picture and can use `{{project_name}}` and the other placeholders.
- **Caption numbering** is *Automatic* by default: a picture with a caption is numbered "Figure 1:", "Figure 2:" … in the order they appear, and one without (a logo) is not. Choose *Always* to number it anyway ("Figure 3") or *Never* to leave a captioned picture plain.
- In the text view an image is one line: `@image "<file id>" alt "The logo" width 85 mm align right caption "Our logo"`.
- A picture's GPS position, camera and other hidden details are removed when it is placed in a report. A picture that has been deleted is left out and the run warns about it.
- A report that is exported or imported with its project carries the pictures it uses.
