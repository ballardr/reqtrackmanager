---
sidebar_position: 5
---

# Reports and export

## Generating a report

A project's **Reports** page generates a PDF, Word (DOCX) or CSV export of its requirements, filtered by component, category, status, or keyword, with the organisation's shared resource files appended as extra sections. **Generate PDF** is the main button; **More formats** offers the Word file and CSV. A PDF or Word export can use one of the organisation's **report templates** — an accent colour, an optional cover page, footer text, and its own default introduction/chapters/appendices — for consistent, on-brand output across projects.

| Reports |
| --- |
| Filtered PDF/Word/CSV export with a selectable organisation branding template |
| ![Reports page with filters and a selected branding template](../../static/img/screenshots/reports-page.png) |

A project's Reports page can also offer reports from enabled modules (for example [Context & Strategy's](../modules/context-strategy-module/reports.md) and [Decision Management's](../modules/decision-management-module/reports.md)) in the same **Report** picker, with *Requirements report* listed first. When no module report applies, the picker is hidden and the page is the requirements report alone.

## How reports name records

Every report row that names a record leads with its [record code](../reference/glossary.md#record-code) and ends with the record's [tags](./tags.md), in the PDF, Word file, CSV and on screen alike, so a printed page or a spreadsheet can say *which* `PER-001` it means.

On screen, a long report table shows its first 50 rows with a "Showing 50 of n rows" count and a **Load more** button; the PDF, Word and CSV downloads always contain every row.

```mermaid
flowchart TD
    R["A record in a report"] --> Q{"Whose record is it?"}
    Q -->|"The organisation's<br/>(a shared Persona)"| O["Always qualified:<br/>ACME-PER-001"]
    Q -->|"Another project's, or the<br/>report covers the organisation"| P["Qualified by that project:<br/>ACME-REQ-001"]
    Q -->|"The project reported on"| S{"Does the organisation show<br/>the project code everywhere?"}
    S -->|"Yes"| P
    S -->|"No"| B["Bare: REQ-001"]
```

A report never follows your personal *Show the project code* preference, so a report that is saved, scheduled or shared reads the same for everyone. Notifications also carry the qualified code, because the notification list is read outside any project. The requirement CSV used for [import and export](./requirements-management.md#csv-import-and-export) keeps its plain `unique_code` column, which an import ignores.

## Word (DOCX) export

Every report downloads as an editable Word file with the same content, order and branding as its PDF, so it can be edited after download. Both formats are built from one shared document, so they cannot drift apart.

```mermaid
flowchart LR
    R["Requirements report<br/>or module report"] --> D["One report document<br/>headings, text, tables, images"]
    D --> P[PDF]
    D --> W["Word (DOCX)"]
    R --> C["CSV (first table)"]
```

- **Colour carries over:** a cell the screen colours as a badge (a status, a rating band, a matrix cell) is filled in the same colour in the PDF and Word file, and the word stays in the cell so a black-and-white print still reads. The text colour is chosen for contrast: white on a dark fill, black on a light one. The same applies to the header row, and a cover-page title in a very light accent colour is darkened so it stays readable on white paper, whatever accent colour your report template uses. The CSV is text only.
- **Editable structure:** real Word heading styles (insert a table of contents from them), real tables with a shaded header row that repeats on each page, bullet lists, and a footer with page numbers. A branding template's accent colour, cover page, logo and footer text apply. Module reports use landscape pages; the requirements report is portrait.
- **Text formatting:** in a layout's text and in a report's introduction, chapters and appendices, `**bold**`, `*italic*` and `` `code` `` are drawn as bold, italic and monospaced text, and bullet lists (`- item`), numbered lists (`1. item`), `#` headings and own-line images are laid out, in PDF, Word, OpenDocument text and HTML alike. **Links** are written `[the words](address)` and are clickable in all four formats: a web address (`https://…`), an email address (`mailto:name@example.org`) or a section of the same report (`#overview`, the heading's words in lower case with hyphens: the heading "Scope & Goals" is `#scope-goals`, and a second heading called Overview is `#overview-2`). In a layout the address may use a value, such as `[the spec]({{record.url}})`; the address is checked once the value is filled in, and a link whose address is not allowed (a `javascript:` address, a relative path, an address with a space) or that points at a heading that is not in the report is printed as plain words, with a warning in a layout. A bare web address, a `<…>` address, raw HTML and entities are printed as written, and so is a `*` or `_` that does not open and close a word (write `\*` for a literal asterisk, and `\[` for a bracket that would otherwise start a link). A value filled in from a record is never read as formatting. Characters Word cannot store (control characters) are dropped.
- **Languages in the PDF:** Latin, Latin Extended (for example Polish), Cyrillic and Greek print correctly. Arabic and Indic scripts are not shaped and Chinese, Japanese and Korean have no font in the PDF, so use the Word file for those; the Word file stores the text as written.
- **Images** are the organisation's shared images only, as in the PDF.
- **Document properties** carry the title and "ReqTrackManager" as author, never a person's name.

## Report content

Each report type has its own **introduction**, **body chapters** and **appendices**: a requirements report and a decision log need different openings, so content is written per report type rather than once for everything. A PDF or Word file prints the introduction and chapters first, then the report itself, then the appendices. CSV and on-screen (JSON) output carry none of it.

Content can be written at three levels, each with a **Report type** drop-down (the requirements report, then each enabled module's reports) led by **All reports**, the content used by any report type that has none of its own at that level:

| Level | Where | Applies to |
|-------|-------|-----------|
| Report template | Organisation admin → Templates & reports → Report templates | Any report generated with that template |
| Project | Project Admin → Report Setup | Reports generated for that project |
| Organisation default | Organisation admin → Templates & reports → Report Defaults | Any project that, with its parent projects, sets none |

Introduction, chapters and appendices resolve independently. Each takes the first non-blank value in this order, so a template's content wins over a project's, and so on down:

```mermaid
flowchart TD
    A["Report type K is generated"] --> T["Template: K, then All reports"]
    T -->|"blank"| P["This project: K, then All reports"]
    P -->|"blank"| D["Requirements introduction only:<br/>the project's description"]
    D -->|"blank"| N["Nearest parent project: K, then All reports"]
    N -->|"blank"| O["Organisation default: K, then All reports"]
    O -->|"blank"| B["Nothing is printed"]
```

| Report Setup | Report Defaults |
| --- | --- |
| Blank fields name their source: the project's description, its parent project, the organisation | Organisation defaults, written separately for each report type |
| ![Report Setup with a Report type drop-down, with the introduction, chapters and appendices each labelled with where their content is inherited from](../../static/img/screenshots/report-setup.png) | ![Report Defaults with a Report type drop-down and an appendix written for the requirements report](../../static/img/screenshots/report-defaults.png) |

A child project that sets nothing for a report type therefore uses its parent project's (then the grandparent's, and so on), then the organisation's. In **Report Setup**, each blank field names where its content comes from (for example "Inherited from *Parent programme*" or "Organisation default (*Acme*)") and previews it; once a project writes its own, **Use inherited** gives it back. The generation page fills its editors with the content that applies and lets you change it for that one report.

Every editor has an **Insert image** button: pick from the organisation's already-uploaded images, or upload a new one on the spot, and it's included in the generated PDF or Word file as its own paragraph. Images used by report content travel with an organisation or project export.

### Placeholders

These can be typed in any introduction, chapter title or body, or appendix, and are replaced when the report is generated:

| Placeholder | Becomes |
|-------------|---------|
| `{{project_name}}` | The project's name (the organisation's name for an organisation-wide report) |
| `{{report_title}}` | The title printed on the report |
| `{{generated_on}}` | The generation date, `YYYY-MM-DD` |
| `{{organisation}}` | The organisation's name |

Anything else in double braces is printed as written. Placeholders are plain text replacement, not a template language: the replaced value is shown as ordinary text and cannot add formatting.

## Record list report

For any other kind of record, the **Reports** picker offers **Record list**: choose a **Record type** (Requirements, Actions and every other list that has a table), optionally a **Tag**, and, on a project with parent or child projects, which **Projects** to include. The page shows the table, with the record's code first, and **Export** downloads it as a PDF, Word file or CSV. The same PDF and Word files are in each list's own **Export** menu, where they carry that list's current filters. A status or rating that is coloured on screen is coloured in the PDF and Word file too, and also written out in words. Columns holding personal data appear only when your organisation's policy and your role allow it, and the report says when some were left out. A PDF or Word file covers up to 5,000 records; for more, download the CSV or narrow the filters.

## Custom reports

A **custom report** is a report layout somebody designed: a document (headings, text, tables, and for each record its linked records) or a set of tables. Layouts are written for an organisation, which every project can run, or for one project (a child project also sees its parents'). Each appears in the **Report** picker under **Custom reports**, beside the module reports (a project can hide an organisation layout it does not want to offer). A layout never shows more than you could already read: records you cannot open are counted in a note ("2 record(s) not shown") and never named.

Layouts are written in the [designer](#designing-a-layout), opened from **Report layouts** in a project's **Report Setup** or the organisation's **Templates & reports**; they can also be created through the REST API, or by an AI assistant that has the [MCP tools](../api-integrations/ai-assistants-mcp/overview.md) in write mode. A layout can have its own introduction, chapters and appendices (the **Report type** drop-down in Report Setup and Report Defaults lists it by name), and a PDF or Word download uses the chosen branding template as for any report.

### Starter layouts

Every organisation starts with three ready-made document layouts, so a first report needs no design work:

| Starter | What it gives you |
|---|---|
| **Business Requirements Document** | Purpose and scope, Pain Points, stakeholders and Personas, needs, Strategy, Future State, requirements, constraints and assumptions, decisions, risks, traceability coverage, Open Questions and the approval state of each record. |
| **Engineering Specification** | Scope, guiding principles, requirements by component, requirement types, needs, constraints, compliance obligations, decisions, traceability coverage and each requirement's review date. |
| **Review Package** | What needs a person now: requirements still in draft or reviewed, change requests under review, decisions awaiting approval, open and overdue questions and risk reviews. |

Each section is built from the project's records when you run it, so the document is a view of them, not a copy to keep up to date. A section whose module a project does not use is left out, not printed empty. The starters are ordinary layouts: open one in **Report layouts** to change the words and sections, rename it or delete it. If you delete one, or your organisation was created before the starters existed, choose **Add starter layouts** in the organisation's **Report layouts**; it adds only the starters you do not already have and never changes one you edited.

### Designing a layout

**Report layouts** lists a project's own layouts, those shared by its parent projects and by the organisation, and, for an organisation, its own. Choose **New layout**, give it a name and say whether it is a **Document** (headings, text and tables, for PDF, Word or HTML) or a **Table** (one or more plain tables, for Excel or CSV); the kind cannot be changed later. A layout shared from elsewhere opens read-only: **Make a copy** to change it for this project, or **Hide in this project** and bring it back with **Add organisation defaults**.

The designer shows the layout in up to three views you can switch between at any time: **Text**, **Outline** and, for a document layout, **Document**. In the text view each block is a line starting with `@`, and `{{req.title}}` puts a field of a record in the text.

```text
@layout document

@heading Requirements of {{project_name}}

@each requirement sort title as req
  @heading level=2 {{req.code}} {{req.title}}
@end
```

```mermaid
flowchart LR
    T["Type the text, or build the outline<br/>(insert a block, field or widget)"] --> C["Checked as you pause<br/>problems listed by line or on the block"]
    C -->|valid| P["Run preview<br/>real records, your access,<br/>nothing stored"]
    C -->|valid| S["Save new version<br/>(with a note)"]
    S --> H["History<br/>compare any two versions"]
    H -->|use an old version| T
```

- **Problems** are listed by line and column; choosing one puts the cursor there. **Save new version** and **Run preview** wait until the text is valid. A layout's first line must declare its own kind (`@layout document` or `@layout table`).
- **Insert block** buttons add a heading, text, *for each record*, a group, a table, an *if*, an equation or a page break at the cursor (a sheet for a table layout). The **Fields** tab lists what `{{name.field}}` can use at the cursor, using the name after `as` of the block you are in, and the global placeholders such as `{{project_name}}`. The **Widgets** tab lists the report components you can embed, with each report's settings, and inserts the finished line.
- **Outline** shows the same layout as a list of blocks, with a form for each, so you can build a layout without writing the `@` syntax. **Add block** offers each kind of block; a block that holds others (*for each record*, a group, an *if*) has its own **Contents** list. Move a block with **Move up** and **Move down**, put it inside the block above with **Move into the block above**, take it out with **Move out of this block**, or use **Duplicate** and **Delete block**. A form offers only what the blocks around it give: *Linked from* lists the names of the enclosing blocks, and a filter offers the fields and operators that suit the field you chose. A block with a problem is outlined and shows the message under the field; **Layout settings** at the top holds the page orientation and the [variables](#designing-a-layout). The outline and the document are checked as you pause, **Save new version** and **Run preview** wait until there are no problems, and switching to **Text** shows the same layout as text. You can switch from the text only while it reads without problems, and the document view says why when it cannot show a layout without changing it (the outline always can).
- **Document** shows the layout as a page you write on: a heading or a text block is typed in place, and every other block (a table, a *for each record*, an *if*, a report component) is a framed card with the same buttons and settings as the outline. The buttons above the page apply **Bold**, **Italic**, **Code**, a **Link**, a **Bullet list** or a **Numbered list** to the words under the cursor; typing `**bold**`, `*italic*`, `- ` or `1. ` does the same. **Link** opens a small window where you choose a web address, an email address or a section of the same layout (listed from its headings), and can remove a link you made. A heading holds no formatting. Text the page cannot draw exactly as written (for example a `*` or `_` it is unsure of) stays in a plain source box so nothing is rewritten. A table layout has no Document view.
- **Preview** runs the layout as you, on the real records, and shows a document as it will print or a table layout's first rows of each sheet (with the real row count). It stores nothing, and a project preview can include child projects while an organisation preview can be limited to chosen projects.
- **Saving** adds a version with an optional note. If somebody saved while you were editing, you are told and can reload their version; nothing is overwritten. Leaving with unsaved changes asks first.
- **History** lists every version and compares any two line by line (added lines start with `+`, removed with `-`). **Use this version as the new text** puts an old version in the editor; saving it adds a new version, so history is never rewritten.
- Organisation administrators can design organisation layouts, and project administrators their own project's; others can run layouts but not open the designer.

| Run | What you get |
| --- | --- |
| A project's Reports page | The layout for that project; **Include child projects** adds the readable child projects |
| The organisation overview's Reports group | An organisation layout evaluated once for **each project you can read**, merged into one report: a document has a heading and a new page per project, a table layout a leading *Project* column |

```mermaid
flowchart TD
    L["Organisation layout"] --> S["Projects selector<br/>(none chosen = all you can read)"]
    S --> A["Project A<br/>evaluated with your access to A"]
    S --> B["Project B<br/>evaluated with your access to B"]
    A --> M["One merged report"]
    B --> M
    M --> O["On screen · PDF · Word · OpenDocument text · HTML<br/>Excel · OpenDocument spreadsheet · CSV (zip for several sheets)"]
```

- **Formats:** a document layout downloads as PDF, Word, OpenDocument text (ODT, for LibreOffice and other office suites) or a standalone HTML page (no scripts, safe to open or email); a table layout as an Excel workbook or OpenDocument spreadsheet (ODS), one tab per sheet, or CSV, which is a zip of one CSV file per sheet when the layout has several sheets. Text a cell starts with `=`, `+`, `-` or `@` is stored as plain text, never run as a formula. The on-screen view shows each table of the report as a section, titled by the headings above it.
- **Choosing projects:** the **Projects** selector lists exactly the projects you hold a role in; downloads carry the same choice as the screen. A project that has hidden the layout is left out, and the report says so.
- **Equations:** write an equation on its own line with `@equation \frac{a}{b} = c`, or inside a text line between `\( ... \)` (inline) or `$$ ... $$` (display). Equations are drawn in the preview, the HTML page and the PDF, are native, editable equations in Word when the equation is one Word handles (otherwise a picture), and are pictures in OpenDocument text. A record field shows equations too when it is one people write them in (a requirement's description, reasoning and clarification), including in a table column; any other record text, such as a title, is never read as an equation. Equations work in headings, list items and table cells as well as paragraphs (a `$$ ... $$` there is drawn inline); Excel, OpenDocument spreadsheet and CSV tables keep the TeX as text. The same equations are typeset on a requirement's page once it is locked. Only a set of common commands is accepted (Greek letters, operators, fractions, roots, subscripts, matrices and the like); `\href`, `\input` and anything else is refused when you save. An equation that cannot be drawn is printed as you wrote it, with a warning on the run.
- **Embedded report tables (widgets):** a document layout can include a table, the headline figures or the notes of any module report, such as the Risk register's table of Risks or the Context & Strategy summary's figures, as a line of its own, `[[widget.context_strategy.summary.figures stale_months=12]]`. A widget is only the component: the headings and the sentences around it are the layout's own, so the same table can sit under different words in different reports. It keeps the report's cell colours, can be ordered by one of its columns (`sort "Next review" desc`; numbers sort as numbers, dates as dates, other text without regard to case) and can say what to show when it is empty (`empty "No risks recorded."`). It is produced for the project being reported on, so a project that has switched the module off shows a note that the report is not available there and the rest of the layout still runs. The list of components (with each report's settings) comes from the REST API or the `list_report_widgets` MCP tool; a layout can run up to 20 different reports (components of one report with the same settings share a run).
- **Leaving a part out where a module is off:** `@if module risk_management` ... `@end` (with `@else` if you want) shows its contents only in a project that uses that module, so one organisation layout can span modules and still read cleanly in a project that uses only some of them. The starters are built this way.
- **Choosing which records a layout lists:** a layout's `where` can combine tests with `and`, `or`, `not` and brackets, and test a field against a list: `category in Safety, Security` or `status not_in draft, rejected`, on any field that has a value to compare (text, status, person, number, date), so "every category except General" and "these three categories in one table" are both a single line. A record with no value for the field counts as not in the list.
- **Variables:** a layout can ask for values when it is run, so one layout serves any selection. Declare each at the top of the text view, for example `@var categories enum list label "Categories" from requirement.category`, and use it as `where category in $categories` or in a sentence as `{{var.categories}}`. The Reports page and the designer's preview then show a form: a list of the project's own categories to tick, a date, a number, a switch or text. A variable with a default (`default today` for a date) runs at once; one without a default holds the report back, and Export is hidden, until you choose. A download carries the same choice, and the run records the values it used. Variables only narrow what a report shows; they never show you anything you could not already open, and a value outside the current list still runs but warns that it may match nothing.
- **Limits:** a report shown on screen that is too large or takes too long is refused with a message to narrow the layout or the project choice; nothing partial is produced. A **file** download (PDF, Word, HTML, Excel, CSV) that is too big to produce while you wait is [prepared in the background](#large-reports-are-prepared-in-the-background) instead.
- **Provenance:** every run is recorded (which layout and version, who ran it, when, which projects, how many records of each kind, the version of each versioned record such as a requirement, and a fingerprint of all the records used) without storing the report's content, so a report can be traced back to what produced it. Layouts are versioned: saving a change adds a version and never rewrites an earlier one.
- Layouts, and their introductions, chapters and appendices, travel in a project or organisation [export](./zip-export-import.md).

### Report packs

A **report pack** is a list of several reports you hand over together, each in its own format, downloaded as **one zip**: for example the overview and strategy as PDF and the requirements and Pain Points as Excel, for the categories an external team cares about. A pack is configuration, like a layout: an organisation's packs are shared with every project, a project can have its own, and a child project also sees its parents'. Build one in **Report packs** under a project's **Report Setup** or the organisation's **Templates & reports** (it needs the same permission as designing layouts); a pack shared from elsewhere can be copied, hidden in a project and shown again.

```mermaid
flowchart LR
    V["Your choices<br/>(variables or a saved set)"] --> P["Preview<br/>records per report"]
    V --> Z["Download zip"]
    Z --> L["Layout report<br/>run as you"]
    Z --> M["Module report<br/>run as you"]
    L --> F["manifest.json + numbered files"]
    M --> F
```

- **Reports in a pack.** Each is a custom layout (named, optionally the organisation's or a project's) or a module report, with its format (PDF, Word, OpenDocument text, HTML, Excel, OpenDocument spreadsheet or CSV for a layout; PDF, Word or CSV for a module report), the name of its file inside the zip, and optionally values it always uses. Files are numbered by their position (`01-overview.pdf`), so two reports can share a name, and a file name can never be a path.
- **Variables.** A pack declares the choices a person makes once, such as the categories to include. A layout in the pack that has a variable of the same name and type receives the choice; a value the pack entry fixes itself wins. Variables narrow what the reports show. They are not access control: every report runs with the access of the person downloading it, so the zip holds only what they may read.
- **Saved sets.** A pack can keep named choices ("Team Alpha: categories A and B") so a repeat download is one click. A set saved with an organisation pack can be **overridden for a project**, variable by variable: the project sees the shared value beside its own and can reset it. A project can also add sets of its own. In an organisation-wide run, each project's reports use that project's values. A saved value that is no longer one of the variable's options is flagged on the form, not dropped.
- **See before you download.** The Reports page lists, for the chosen values, how many records each report would include and which reports are **not available** (the layout was hidden, its module is off, you lack the role it needs) and why. Nothing is stored or produced until you download.
- **The manifest.** The zip's `manifest.json` records the pack and its version, who it was run for and when (UTC), the values used (and the saved set), each report with its format, layout version, record counts and status, and the reports that were left out. It holds no record content. A pack where nothing can run is refused.
- **Large packs** that cannot be produced while you wait are prepared in the background like any large report, and the zip appears under **Background reports**.
- Packs, their saved sets and project overrides travel in a project or organisation [export](./zip-export-import.md), and an AI assistant with the [MCP tools](../api-integrations/ai-assistants-mcp/overview.md) can list, preview and queue them.

### Large reports are prepared in the background

When you download a file that is too big to produce while you wait, the Reports page says so ("It is being prepared in the background and you will be notified when it is ready") and the report joins **Background reports**, a list under the report. The server works through the queue, allows a bigger report than a download you wait for, and **notifies you** (in the app, and by email if your notification settings send it) when the file is ready or could not be produced.

```mermaid
flowchart LR
    A["Download too big<br/>to wait for"] --> B["Waiting"]
    B --> C["Preparing"]
    C --> D["Ready<br/>(notification)"]
    C --> F["Failed<br/>(notification, with the reason)"]
    D -->|"download, until it expires"| G["Your file"]
    D -->|"Delete file, or the retention passes"| H["Expired<br/>(file deleted)"]
```

- **Only you can download it.** The file belongs to the person who asked for it; nobody else, including administrators, can fetch it. It is produced with your access at that moment, and downloading it re-checks that you still have access to what it covers.
- **It is kept for a limited time.** An organisation administrator sets how many days a file is kept in **Org Admin → Templates & reports → Background reports**, up to a maximum the platform sets; leave it blank to use the platform default (7 days). When the time passes, or when you choose **Delete file**, the file is deleted. The record of the run (which layout and version, when, how many records) stays, as for any run.
- **A waiting report can be cancelled**; one being prepared cannot be stopped, and at most five of your reports can be waiting or being prepared at once.
- A report that is too large even for the background (or whose access you lose before it runs) shows as **Failed** with the reason.

## CSV export and import

The same Reports page exports requirements as CSV — every field, including custom field values and target stage — and the Requirements page's **List actions** menu (CSV that re-imports and updates records by code) reverse the trip, mapping a spreadsheet's columns back onto a project's fields. See [Requirements management](./requirements-management.md#csv-import-and-export) for the import side.

## Where this fits

See [Workflows → Reporting and CSV import/export](../workflows/reporting-and-csv-import-export.md) for the end-to-end task walkthrough, and [Project templates](./project-templates.md) for how report content carries into a newly created project.
