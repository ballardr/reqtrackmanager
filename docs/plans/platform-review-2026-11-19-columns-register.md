# Column choice register (phase 71)

Part of [the platform review plan](platform-review-2026-11-19-plan.md). Every list drawn with `DirectoryTable`: its data columns, which are always on, which are optional and the default for each, with the reason for a list that offers none. It is the checklist for the sweep and the source of the guard's exemptions. **Status:** signed off by the user, 2026-11-24 (**Decided by: User**): the threshold is five or more data columns, the defaults are as drafted, and Requirements and Change Requests moved onto `DirectoryTable`. Built.

Defaults follow the style guide's column chooser rule: a value already shown by an icon or by nesting, a count, a technical identifier and a rarely read date are off; the name or title, the code and the status are always on; the row's actions column is never choosable. Hiding a column changes the screen only (Sort by, Export and Import keep every column).

## Tier 1: more than five data columns (offer the chooser)

| # | List (file) | Always on | Optional, on | Optional, off | Reason for the off columns |
|---|-------------|-----------|--------------|---------------|-----------------------------|
| 1 | Diagrams (`ProjectDiagramsPage`) | Code, Name, Status | Type, Folder, Element, Contents | Switches | A count that exists only for block diagrams (a dash for the rest) |
| 2 | Elements (`ProjectElementsPage`) | Code, Name, Status | Type, Folder, Owner | Parent, Connections | Parent is shown by nesting; Connections is a count |
| 3 | Connections (`ProjectConnectionsPage`) | Code, Name, Status | Type, Source, Target | Folder, Protocol | Folder is a grouping, Protocol a technical value read on the detail page |
| 4 | Risks (`ProjectRisksPage`) | Code, Title, Status | Type, Inherent, Residual, Owner, Next review | none | Every column is read when triaging |
| 5 | Pain points (`ProjectPainPointsPage`) | Code, Title, Status | Type, Priority, Score | none | Every column is read when prioritising |
| 6 | Baselines (`ProjectBaselinesPage`) | Name | Kind, Stage, Taken, Records | Taken by | Rarely read; the detail page names the person |
| 7 | Compliance evidence (`EvidencePanel`) | Title, Code, Status | Issuing organisation, Expiry, Validity | none | Expiry and Validity are the point of the list |
| 8 | Organisation elements (`OrgElementsPanel`) | Code, Name, Status | Type, Folder, Owner | none | Same columns as the project list, no count or nesting column |
| 9 | Announcements (`AnnouncementsPanel`) | Title, Status | Severity, Window | Sign-in page, Dismissible, Send notification | Settings read when editing; the edit form shows them |
| 10 | Policies (`PoliciesPanel`) | Title, State | Version, Audience, Effective from | Updated | A rarely read date |
| 11 | Component phases (`ComponentTracksList`) | Component | Stage, Phase, Owner, State | Workflow | A technical identifier |
| 12 | Organisation users (`OrgAdminPage`) | Email, Name | Roles, Status, Last login, Two-factor | none | Security and audit columns stay visible by default |
| 13 | Server users (`ServerManagementPage`) | Email, Name, Status | Organisations, Groups, Last login | Created | A rarely read date |

## Tier 2: exactly five data columns (chooser offered, threshold five or more)

| List (file) | Always on | Optional, on | Optional, off |
|-------------|-----------|--------------|---------------|
| Decisions (`ProjectDecisionsPage`) | Code, Title, Status | Type, Owner | none |
| Open questions (`ProjectOpenQuestionsPage`) | Question, Code, Status | Priority, Due | none |
| Strategies, project and organisation (`ProjectStrategiesPage`, `OrgStrategiesPanel`) | Title, Code, Status | Priority | Version |
| Guiding principles, project and organisation | Name, Code, Status | Priority | Version |
| Future states, project and organisation | Title, Code, Status | Target date | Version |
| Standards (`StandardListPage`; six with the Organisation column) | Reference, Name, Status | Organisation, Issuing organisation | none |
| Compliance by standard (`ProjectCompliancePage`) | Standard, Compliance | Version, Non-compliant, Target date | none |
| States (`ProjectStatesList`) | Code, Name | Diagram, Kind, Element | none |
| Symbol library (`SymbolLibraryTable`) | Name | Source, Folder, Used by | none |
| Snippets (`ReportSnippetsPanel`) | Name | Category, Source, Blocks, Carries | none |
| Stage plan (`StagePlanTable`) | Stage | Phase, Owner, Progress, Expected | none |
| History (`ProjectActivityTable`) | Time, Event | Type, Record, Person | none |
| Licences, packages (`LicencesPanel`) | Name | Version, Licence, Kind, Used in | none |

## Exempt: four or fewer data columns (no chooser, reason: nothing to spare)

Imported people (`ImportedPeoplePanel`), project members (`ProjectMembersTable`), report layout history (`ReportLayoutHistory`), tag administration (`TagAdminPanel`), tag usage (`TagUsageModal`), baseline records (`BaselineRecordsCard`), symbol usage (`SymbolUsageModal`), standard applicability (`StandardApplicabilityPanel`), standard members (`StandardMembersSection`), decision templates (`DecisionTemplatesPanel`), stakeholder group members (`StakeholderGroupsPanel`), organisation groups and project groups (`OrgAdminPage`, `ProjectAdminPage`), organisations (`OrgListPage`, `ServerOrganisationsPage`), licence components and images (`LicencesPanel`, four columns each). The organisation usage table (`OrgUsageTable`) is a fixed key-value table whose every row is the point.

## Already offer a chooser

People, Personas, Stakeholders, Needs and the other `RecordListView` lists (phase 70, `useOptionalColumns`); Product Feedback requests (`RequestColumnChooser`, whose Score columns follow the organisation's scoring models, so it keeps its own list of columns) and report setup (`ReportSetupPanel`, columns of a report's field list, not a `DirectoryTable`).

## Moved onto `DirectoryTable` in this phase

| List (file) | Always on | Optional, on | Optional, off |
|-------------|-----------|--------------|---------------|
| Requirements (`RequirementsPage`) | ID, Name, Status | Target · level, Component · category, External references (when any) | none |
| Change requests (`ChangeRequestsPage`) | Code, Name, Status | Target, Level, Created | none |

Each keeps its bulk selection, ordering buttons, accent stripe (`rowAccent`) and Components and References columns (`placements`).

## Not `DirectoryTable` lists

Projects (`ProjectListPage`), Favourites (`FavouritesPage`), Actions (`ProjectActionsPage`), Reviews due (`ProjectReviewsDuePage`) and the organisation Compliance standards panel draw their own `<table>` with five or more columns. The guard keys on `DirectoryTable`, so it does not see them; they offer no chooser and are an open gap, to be moved onto `DirectoryTable` in a later change (the user limited this phase to Requirements and Change Requests).
