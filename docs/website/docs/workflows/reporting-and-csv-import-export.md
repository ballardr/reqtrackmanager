---
sidebar_position: 9
---

# Reporting and CSV import/export

## Generating a PDF, Word or CSV report

Open a project's **Reports** page:

1. Filter by component, category, status, or keyword to scope what's included.
2. Optionally pick one of the organisation's **report templates** for a PDF or Word export — an accent colour, cover page, and footer, for consistent on-brand output.
3. Generate the report with **Generate PDF**, or choose **More formats** for an editable Word file or CSV — a PDF or Word file includes the introduction, chapters and appendices written for that report type (**Project Admin → Report Setup**), falling back to the parent project's and then the organisation's defaults field by field wherever the project leaves one blank. See [Report content](../core-features/reports-and-export.md#report-content).

| Reports page |
| --- |
| Filtered PDF/Word/CSV export with a selectable organisation branding template |
| ![Reports page with filters and a selected branding template](../../static/img/screenshots/reports-page.png) |

## Exporting requirements to CSV

Two doors lead to the same data. The Reports page exports requirements as a formatted CSV. The **Requirements** page's own **Export** button downloads the list *as it is filtered on screen* as a CSV that you can edit and import back: every field, including custom field values and target stage, with the record's code in the first column. Columns that your organisation's policy keeps out of exports (personal data) are left out, and the Export menu says so.

The list's **Export** menu also offers **Download PDF report** and **Download Word report**: the same rows and filters as a formatted document. The Reports page's **Record list** report produces the same table for any record type without opening its list.

## Importing requirements from a CSV file

From a project's **Requirements** page, click **Import** and choose a file:

1. A **mapping** screen lists every field the import can set (Name, Component and Category are required for a new requirement; Reasoning, Description, Level, Target version, Owner, Reviewer, Tags, review fields and custom fields are optional) alongside a dropdown to pick which column in your file supplies it. For Component, Category, Level and Target version you can instead choose **Same value for every row**. A field you leave unmapped is left alone.
2. A row with a **Code** (`SW-PERF-014`) updates that requirement; a row without one creates a new requirement. Component and Category must match an existing prefix exactly (case-sensitive).

| CSV column mapping |
| --- |
| Mapping a CSV file's columns onto requirement fields |
| ![CSV import mapping dialog with columns mapped](../../static/img/screenshots/csv-import-mapping.png) |

3. Click **Preview**. Nothing is written yet: the preview shows how many requirements would be created, updated or left unchanged, the before and after of every changed field, and any row that has an error.
4. Click **Apply**. Valid rows are applied and a message reads "N created, N updated, N failed". Rows that failed (an unrecognised component prefix, say) are listed, and **Download error file** gives you just those rows to fix and import again.

An import goes through the same rules as editing by hand, so an approved requirement still has to change through a change request, and a requirement's status is never set from a file. **Export → Download import template** gives a CSV with the right column names for the project.

## Actions and change requests

The **Actions** and **Change requests** lists have the same **Export** menu, and it downloads the list as filtered on screen (the change request list's default "Active" view exports the active requests; pick **All statuses** to export them all).

- **Actions** also have **Import**, in the same file format: a row with a code updates that action (title, description, outcome, due date), a row without one creates it. An action's type is required for a new action and must match an existing action type by name.
- **Change requests** are export-only. The file carries each request's kind, status, target requirement, reason, the values it proposes, who created and decided it, and its dates. There is no import: a change request is a proposal whose content depends on its kind, and it is submitted and approved in the application, so it is written in its form.

## Where this fits

See [Core Features → Reports and export](../core-features/reports-and-export.md) for report-content editing (Markdown/WYSIWYG, image inserts, organisation defaults), and [Authoring and reviewing requirements](./authoring-and-reviewing-requirements.md) for creating requirements one at a time instead of in bulk.
