---
sidebar_position: 8
---

# Search, filtering, and view-mode persistence

## Search and filters

The **Projects** list is searchable by name/summary and filterable by active/archived status, by role on the project, by the project's current stage status, and — for anyone belonging to more than one organisation — by which organisation it's in. Favourited projects always sort to the top regardless of any other filter or search applied. The **Requirements** and **Change Requests** lists work the same way: search by name or ID, and click a status (or target-stage) badge to filter the list to it — click it again to clear the filter, rather than needing a separate "clear filters" control.

| Projects dashboard |
| --- |
| Favourites, role/stage filters, and a choice of tile, list, or tree view |
| ![Projects dashboard with filters and a tile-view layout](../../static/img/screenshots/projects-page.png) |

## View modes

The Projects list offers **tile**, **list**, and (for an organisation with hierarchical projects) **tree** view; the Requirements list offers tile and list view. Each page remembers its own view-mode choice independently — switching Projects to list view doesn't change what Requirements shows, and the choice persists across visits rather than resetting to a default every time the page loads.

## Where this fits

These controls appear throughout [Requirements management](./requirements-management.md), [Change requests](./change-requests.md), and the Workflows section's task walkthroughs (see [Authoring and reviewing requirements](../workflows/authoring-and-reviewing-requirements.md) for the requirements list in context) — this page exists as a single reference for behaviour that's otherwise repeated on nearly every list in the app.
