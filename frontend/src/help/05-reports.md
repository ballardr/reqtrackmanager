# Reports

The **reports** page in a project generates a PDF or CSV export of its requirements. **Generate PDF** and **Generate CSV** sit at the top of the page; everything else — template & layout, filters, the introduction/body chapters/appendices editors, and resource sections — is collapsed by default so the page opens straight to the two actions you'll use most.

## Filtering what's included

Under **Filters**, you can narrow the report down by component, category, status, or a keyword, and choose whether to include archived requirements.

## PDF structure

A PDF report is organised as one chapter per component with one sub-section per category underneath, in the same order they appear in the project's component/category tree. Each sub-section's table lists that category's requirements as ID, Name, Reasoning, and Status (rightmost). The CSV export stays a single flat list (with its own Component/Category columns), sorted by requirement ID, for spreadsheet use.

### Chapter layout

Under **Template & layout**, **Chapter layout** controls whether the PDF chapters by component (each chapter starting on its own page) or renders continuously (category headings only, no per-component page breaks):
- **Auto** (the default) uses the selected report template's own setting; with no template selected, it chapters by component unless some component in the report has fewer than three requirements, in which case it falls back to continuous — a whole page break for one or two requirements reads worse than just letting them flow.
- **Chapter per component** / **Continuous** force that choice for this generation regardless of the template or the auto heuristic.

## Custom content

The **Introduction**, **Body chapters**, and **Appendices** sections on this page are pre-filled with the project's effective content — its own saved introduction/chapters/appendices (set in Project Admin → Report Setup), falling back to the project's description for the introduction specifically if no introduction has been set, then to the organisation's defaults. Editing them here only affects the report you're about to generate; to change the saved defaults, use Project Admin → Report Setup instead. The Markdown support is intentionally basic — headings, paragraphs, bold/italic text, links, bullet lists, and images. Tables and numbered lists aren't rendered.

### Images

Every Markdown editor used for report content (a project's intro/chapters/appendices — including on this page — an organisation's defaults, and report templates) has an **Insert image** button in its toolbar. It opens a picker over your organisation's already-uploaded shared images, with an option to upload a new one on the spot — the same shared-resource library used elsewhere, just filtered down to images. Picking one inserts it as its own paragraph; an image can't currently be placed inline with surrounding text, and pasting or typing a plain image URL doesn't work — only images added through the picker are supported.

## Report templates

An organisation admin can create named **report templates** in Org admin, each with its own accent colour, an optional cover page, whether to include the organisation's logo, optional footer text, an optional introduction/chapters/appendices override, and its own chapter-layout setting. Selecting a template on the report generation page immediately loads its content into the Introduction/Body chapters/Appendices editors (per field — a template that only sets an introduction still falls through to the project's own chapters/appendices). A project can have a **default report template** (set in Project Admin → Report Setup) that's pre-selected here, though it can still be changed or cleared for any specific report. Templates don't apply to CSV exports, since CSV has no visual styling to brand.
