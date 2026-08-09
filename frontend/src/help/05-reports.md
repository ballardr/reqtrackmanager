# Reports

The **reports** page in a project generates a PDF or CSV export of its requirements.

## Filtering what's included

Before generating, you can narrow the report down by component, category, status, or a keyword, and choose whether to include archived requirements.

## Custom content

You can add a Markdown introduction and appendix to a PDF report, and optionally include an organisation's shared resource files as extra sections. The Markdown support is intentionally basic — headings, paragraphs, bold/italic text, links, bullet lists, and images. Tables and numbered lists aren't rendered.

### Images

Every Markdown editor used for report content (a project's intro/chapters/appendices, an organisation's defaults, and report templates) has an **Insert image** button in its toolbar. It opens a picker over your organisation's already-uploaded shared images, with an option to upload a new one on the spot — the same shared-resource library used elsewhere, just filtered down to images. Picking one inserts it as its own paragraph; an image can't currently be placed inline with surrounding text, and pasting or typing a plain image URL doesn't work — only images added through the picker are supported.

## Report templates

An organisation admin can create named **report templates** in Org admin, each with its own accent colour, an optional cover page, whether to include the organisation's logo, and optional footer text. Pick one when generating a PDF to apply that branding; leave it unset for a plain, unbranded report. Templates don't apply to CSV exports, since CSV has no visual styling to brand.
