---
sidebar_position: 8
---

# Search, filtering, and view-mode persistence

## Search and filters

The **Projects** list is searchable by name/summary and filterable by active/archived status, by role on the project, by the project's current stage status, and — for anyone belonging to more than one organisation — by which organisation it's in. Favourited projects always sort to the top regardless of any other filter or search applied. The **Requirements** and **Change Requests** lists work the same way: search by name or ID (change requests also match on their reason and target requirement), and click a status (or target-stage) badge to filter the list to it — click it again to clear the filter, rather than needing a separate "clear filters" control. Every record list also has a **Tags** filter once the project has [tags](tags.md).

| Projects dashboard |
| --- |
| Favourites, role/stage filters, and a choice of tile, list, or tree view |
| ![Projects dashboard with filters and a tile-view layout](../../static/img/screenshots/projects-page.png) |

## Listing records from parent and child projects

In a project that has a parent or child project you can open, every record list (requirements, change requests, actions, files, and each module's lists such as risks, decisions, engagements and people) and the project **Overview** has a **Show records from** filter: *This project*, *This + parent projects*, *This + child projects*, or *This + parent and child projects*. It is not shown when the project has no relatives you can open.

- A row from another project is labelled **From {project}**, its code includes that project's code (for example `PLAT-REQ-001`), and it opens in its own project. Those rows are read-only in the list: no bulk selection or reordering, so to change one you open it where it lives.
- You only ever see records you could already see in the other project: you need a role there, the feature must be switched on there, and you need permission to view that type of record. Anything else is left out, with no hint that it exists. Siblings and projects outside the tree are never included.
- Result counts cover every project the list includes. On the Overview the tiles and charts add up the projects (a line says how many; stage progress stays this project's own), and the risk matrix plots risks from every project in the list, so you can read the risk of a whole product built from sub-projects.
- The choice is remembered for each project, and starts from **Preferences → Default list scope**. If that default is wider than a project offers (for example "both" in a project with no children), the list shows the widest choice the project does offer.

```mermaid
flowchart LR
    A["Open a list"] --> B{"Project has a parent or child you can open?"}
    B -->|"no"| C["This project only; no filter shown"]
    B -->|"yes"| D["Show records from: your remembered choice, else your default"]
    D --> E["Rows from this project, then from each project you may see"]
```

## View modes

The Projects list offers **tile**, **list**, and (for an organisation with hierarchical projects) **tree** view; the Requirements list offers tile and list view. Each page remembers its own view-mode choice independently — switching Projects to list view doesn't change what Requirements shows, and the choice persists across visits rather than resetting to a default every time the page loads.

## Project navigation order

The **Project** section of the left navigation (Overview, Requirements, Actions, and any enabled module's pages) can be reordered per user. Select the sliders icon beside the section label (in the icon-only rail, the **Customise navigation** row at the bottom of the section) to open the editor:

- **Reorder** with the up/down buttons on each row.
- **Move to More** for rarely used items. They sit behind a **More** disclosure (a popup when the rail is icon-only) and are never removed. **Overview** and **Project admin** cannot be moved into More, so there is always a way to reach admin.
- **Apply to**: *All projects* saves your personal default; *Only this project* saves a layout for that project alone. **Remove this project's own layout** drops the override.
- The page you are on is always shown, even if its link is under More.
- A module you enable later appears in its default position rather than being hidden.
- Out of the box the section runs Overview, the core work items, any module pages, then **Project history** and **Project admin** last. A module page whose part of the module is switched off for the project (for example Pain Points under Context & Strategy) is not listed, and returns as soon as it is switched back on.

The choice is stored with your account, so it follows you across devices.

```mermaid
flowchart LR
    A["This project's own layout"] -->|"none"| B["Your default for all projects"]
    B -->|"none"| C["Product default order"]
```

## Where this fits

These controls appear throughout [Requirements management](./requirements-management.md), [Change requests](./change-requests.md), and the Workflows section's task walkthroughs (see [Authoring and reviewing requirements](../workflows/authoring-and-reviewing-requirements.md) for the requirements list in context) — this page exists as a single reference for behaviour that's otherwise repeated on nearly every list in the app.
