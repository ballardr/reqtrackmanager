---
sidebar_position: 2
---

# Glossary

Terminology introduced across this site, gathered into one alphabetical reference. Each entry links back to the page that explains it in full.

#### Action

What happens at the moment a transition is taken, for example "sound the alarm". It is drawn after a slash, following the event and the condition: `event [condition] / action`. It is text for readers and is never run. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Activity

What goes on for as long as a state is active, for example "monitor the temperature". It is drawn as a `do /` line in the state. It is text for readers and is never run. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Advisory stakeholder vote

A visible approve/reject signal a stakeholder can cast on a change request. It never approves or rejects the change itself — only a manager's or administrator's explicit decision does. See [Change requests and baselines](../concepts/change-requests-and-baselines.md).

#### Allocation

A link of the type Allocated to from a requirement to an element of the architecture. Placing an element in a component suggests the requirements of that component for allocation; a person accepts or dismisses each suggestion. See [Allocation](../modules/system-architecture-module/allocation.md).

#### Announcement

A short plain-text message written by a server administrator (for the whole platform) or an organisation administrator (for that organisation), with a severity (shown by colour, icon and name) and a start (now by default) and an optional end time. It shows on the login pages when flagged, and as a banner after sign-in that can be made not dismissible, and can be sent once as a notification. See [Server administration](../workflows/server-administration.md#messages) and [Administering an organisation](../workflows/administering-an-organisation.md#messages).

#### Attach point

One of the eight points on the edge of a box (the four corners and the four midpoints) where a line meets it. A box shows its points only while the pointer is near it, while it is selected and while a line is drawn nearby. Left automatic, a line uses the point nearest its other end; the end of a selected line can be dragged to another point on the same box. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md).

#### Audit trail

The record of security- and administration-relevant events (logins, permission grants, password changes), independent of any one requirement's own change log — *who did what* across the system. See [Discussions, notifications, and audit](../concepts/discussions-notifications-and-audit.md).

#### Baseline

A permanent snapshot of every requirement that was in draft or reviewed status at the moment a project stage was approved. Answers "what did we commit to" reliably, even after later changes. See [Change requests and baselines](../concepts/change-requests-and-baselines.md). A baseline can also hold a module's records (the architecture), and can be taken manually without a stage; see [Baselines](../modules/system-architecture-module/baselines.md).

#### Boundary box

A box on a block diagram that stands for a connection crossing the boundary of the diagram's element: one end is inside the element and the other outside. Its outline shows the direction (a point on the right is an input, on the left an output). Connections of the layer below can be marked as realising it. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md).

#### Bridged line

A dashed line on a block diagram that stands in for an element hidden by a [view switch](#view-switch). It joins the two elements either side of the hidden one. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md).

#### Change log

The formal, versioned history of a requirement or change request: who changed what, and when, as part of the governed content itself — distinct from its discussion thread. See [Discussions, notifications, and audit](../concepts/discussions-notifications-and-audit.md).

#### Change request

The only way to modify a locked (Approved or Completed) requirement: a proposal with its own reasoning, targeted fields, and an explicit approve/reject decision from a project manager or administrator. See [Change requests and baselines](../concepts/change-requests-and-baselines.md).

#### Choice

A diamond in a state machine diagram. The conditions (guards) on its outgoing transitions decide which path is taken. It can carry a symbol label, text drawn inside the diamond or beside it. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Close the loop

Recording that the people who asked for an [enhancement request](#enhancement-request) were told its outcome once it was delivered or declined. Nothing is sent to them. See [Product Feedback → Relationships and closing the loop](../modules/product-feedback-module/relationships-and-closing-the-loop.md#closing-the-loop).

#### Commercial licence

The second licence the product is offered under, for organisations that cannot or do not wish to meet the terms of the AGPL. Terms are agreed with the licensor. See [Licensing](licensing.md).

#### Composite state

A state that holds other states, drawn as a frame around them, for example "Running" holding "Warming up" and "At speed". See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Condition (guard)

A condition, written as text, that must be true for a transition to be taken, for example "battery low". It is shown in square brackets after the event, and the lines leaving a choice are told apart by their conditions. The stored and exported name of the field is `guard`. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Component placement

The place a record sits in the project's component and category tree. A record other than a requirement can hold several, for example *Hardware / Cooling* and *Software*, and lists, search, reports and exports can be filtered by them. A requirement keeps its own single component and category. See [Core Features → Components on every record](../core-features/components-on-records.md).

#### Connection

A record of a link between two elements of the architecture, such as a REST API between a gateway and a service. It has a [connection type](#connection-type), an optional protocol, and an optional [port](#port) at each end. See [Elements, ports and connections](../modules/system-architecture-module/elements-ports-and-connections.md).

#### Connection type

The kind of interface a connection is, such as REST API, message queue or I2C bus. Types are organised in groups (Serial bus holds I2C and SPI), set how a line is drawn, and can be one-way or two-way. See [Elements, ports and connections](../modules/system-architecture-module/elements-ports-and-connections.md).

#### Cost of Delay

A Pain Point scoring model that adds User/business value, Time criticality and Risk reduction / opportunity enablement with equal importance. See [Pain Point scoring](../modules/context-strategy-module/pain-point-scoring.md#the-criteria).

#### Contributor licence agreement (CLA)

The agreement a contributor signs before a contribution is accepted. It lets the licensor offer the contribution under both the AGPL and the commercial licence. See [Licensing](licensing.md) and [Contributing](contributing.md).

#### Custom field

A project-defined attribute (short text, long text, checkbox, or option list) attached to requirements or change requests, versioned alongside every built-in field. See [Custom fields, terminology, and templates](../concepts/custom-fields-terminology-and-templates.md).

#### Direct grant

A project role assigned to one specific user — the default and simplest way to grant access, as opposed to a [project group](#project-group). See [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md).

#### Discussion thread

Informal comments (which can carry file attachments) for the conversation around a requirement or change request, kept deliberately separate from its formal [change log](#change-log). See [Discussions, notifications, and audit](../concepts/discussions-notifications-and-audit.md).

#### Display note

A short line of text, up to 500 characters, drawn inside an element's box on every diagram that places it. It differs from a note, which belongs to one diagram. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md).

#### Domain

A name that element types and connection types of the System Architecture module can be in, such as Software, Hardware or Mechanical. An organisation and each project can add its own; a type in several domains is listed under each, and a type in none fits every domain. See [Elements, ports and connections](../modules/system-architecture-module/elements-ports-and-connections.md#domains).

#### Element

A part of the product: a service, a board, a datastore. It has a code (`ELM-001`), a type, an optional parent and any number of [ports](#port). Elements are drawn as boxes on block diagrams, each at least as large as its symbol, code and name need. See [Elements, ports and connections](../modules/system-architecture-module/elements-ports-and-connections.md).

#### Enablement

The org-tier switch turning a [module](#module) on for one specific organisation, among whichever modules it's entitled to. See [Modules → Overview](../modules/overview.md).

#### Enhancement request

A proposed solution someone asked the product for, kept in the Product Feedback [module](#module) with a triage lifecycle, [weighted demand](#weighted-demand) and a score. It is a solution; the Pain Point it addresses is the problem. See [Product Feedback → Overview](../modules/product-feedback-module/overview.md).

#### Entitlement

The server-tier licensing lever controlling whether an organisation is allowed to use a given [module](#module) at all, independent of whether the organisation has actually turned it on. See [Modules → Overview](../modules/overview.md).

#### Entry action

What happens each time a state is entered, for example "start the motor". It is drawn as an `entry /` line in the state. It is text for readers and is never run. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Event

What triggers a transition in a state machine diagram, such as `overpressure`. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Exit action

What happens each time a state is left, for example "stop the motor". It is drawn as an `exit /` line in the state. It is text for readers and is never run. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Final state

The ringed dot where a state machine diagram ends. A final state has no outgoing transitions and can carry a symbol label, text drawn inside the ring or beside it. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### General (Pain Point scores)

The part of a Pain Point's scores that applies to the whole Pain Point: every criterion's level, and the default for the criteria scored per persona. A persona that differs adds its own levels, which override General for that persona. See [Pain Point scoring](../modules/context-strategy-module/pain-point-scoring.md#scoring-a-pain-point).

#### Guard

Another name for a [condition](#condition-guard) on a transition.

#### Imported person

A named record standing in for someone an import bundle names who is not a member of the importing organisation. It cannot sign in or hold access, shows an **Imported** badge, and keeps only a display name. See [Zip export/import](../core-features/zip-export-import.md#imported-people).

#### Identity (requirement identity)

The part of a requirement that never changes once created: its project, component, category, generated ID, creator, and archival state. Distinct from its versioned content. See [Requirements, versions, and the lifecycle](../concepts/requirements-versions-and-lifecycle.md).

#### Initial state

The filled dot where a state machine diagram starts. An Active diagram needs exactly one initial state at the top level. It can carry a symbol label, text drawn inside the dot or beside it. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Leader

A line from a note on a block diagram or a state machine diagram to what the note describes: a box or a drawn connection line (block diagram), a state or a transition (state machine diagram), or a free spot on the drawing. A note can have several. A leader can start at any attach point of the note, pass through vertices, be straight or smooth, and have an arrowhead or a dot at either end. Drag from an attach point of a note to draw one; select it to change where it ends, where it starts and how its ends look. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md).

#### Licences

A built-in, read-only group on the Policies page, readable without signing in: the **Product licence** (the licence the application is offered under, with links to its text, its source code and the commercial licence), the **Third-party components** (every library and program the published images contain, with its licence, where it is used and its licence text) and the **Fonts**. It is generated from the build, not written or published by an administrator, so it has no versions, audience or acceptance, and it is separate from the [policies](#policy) the page also lists.

#### Lifecycle (requirement lifecycle)

The fixed sequence a requirement moves through: Draft → Reviewed → Approved → Completed, with Archived available as an exit from Draft or Reviewed. See [Requirements, versions, and the lifecycle](../concepts/requirements-versions-and-lifecycle.md).

#### Line hop

A small arc drawn where one line crosses another on a block diagram or a state machine diagram, so the crossing is not read as a junction. It is the **Line hops** setting of the diagram, off by default. Of two crossing lines, the one that sorts later by its identifier is drawn over the other; connections, transitions and leaders are all lines. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md) and [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Line shape

How a line runs between its two ends on a block diagram or a state machine diagram. **Straight** draws segments through the line's vertices. **Curved** leaves each box straight out of the side or corner it meets and bends only as much as the positions of the boxes need, so it needs no vertices (with vertices it passes through them and still leaves each box outward). **Spline** draws a curve through the vertices, and is straight when the line has none. The diagram has a **Default line shape**, and a connection, transition or note leader can give its own shape or follow the default. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md) and [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Link

A typed relationship between two records of the same project (or a parent and child project), shown in the **Links** panel on both records. Its [link type](#link-type) names it from each end. See [Links and traceability](../core-features/links-and-traceability.md).

#### Link type

The named, directional relationship a [link](#link) carries ("Derives from" / "Is source of"). An organisation defines them, a project may add its own, and each can limit which kinds of record it joins. See [Links and traceability → Link types](../core-features/links-and-traceability.md#link-types).

#### Locking

What happens once a requirement reaches Approved or Completed: its edit form disables, and further change must go through a [change request](#change-request) rather than a silent edit. See [Requirements, versions, and the lifecycle](../concepts/requirements-versions-and-lifecycle.md).

#### Logo band colour

The colour of the band behind an organisation's or the platform's logo and name, so a logo that is white on a transparent background stays visible and the name reads as part of the logo. Its **Logo band text colour** sets the name's colour (empty is black or white by contrast). It is drawn across the top of the sign-in card, in the header of outgoing email and (once a colour is chosen) behind the logo on reports. Unset, it is the colour of the application's top bar. See [Server administration](../workflows/server-administration.md#server-management) and [Administering an organisation](../workflows/administering-an-organisation.md).

#### Module

A self-contained, optional capability area (backend endpoints, database tables, RBAC roles, frontend pages, optionally AI-assistant tools) gated by [entitlement](#entitlement) and [enablement](#enablement) rather than permanently built into the core application. Compliance, Decision Management, Context & Strategy, Stakeholders & Personas, and Risk Management are the modules shipped so far. See [Modules → Overview](../modules/overview.md).

#### Navigation name

A name a project or organisation gives an entry of the project navigation (for example "ADRs" for Decisions), shown in the navigation, as the page title and as the back link of that entry's records. A project's own name takes precedence over its parent's, which takes precedence over the organisation's. See [Administering a project](../workflows/administering-a-project.md#navigation-names).

#### Note (annotation)

Text placed on one diagram only, with a tone, an optional **Title** (drawn in bold above the text), an **Alignment** (Left, Centre or Right), a **Size** (Automatic: as large as its text needs; Manual: the size set by dragging) and any number of leaders. The line breaks typed in its text are kept. It is not a display note, which belongs to an element. A state machine diagram has notes too. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md), [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md#notes) and [Leader](#leader).

#### Organisation

The top-level container, owning users, groups, branding, SSO configuration, and every project underneath it. See [Organisations and projects](../concepts/organisations-and-projects.md).

#### Organisation code

A short upper-case code (letters and digits, no hyphen) that goes in front of the codes of records the organisation itself owns, such as `ACME-PER-001`. It never equals a project code in the organisation. See [Administering an organisation → Organisation code](../workflows/administering-an-organisation.md#organisation-code).

#### Organisation role

A role governing organisation-wide administration (`org_admin`, `project_creator`, `member`) — distinct from a [project role](#project-role). See [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md).

#### Personal access token (PAT)

A long-lived, org/project-scoped bearer credential for non-interactive use, such as scripting against the REST API or connecting an AI assistant. See [Core Features → Personal access tokens](../core-features/personal-access-tokens.md).

#### Platform subscription manager

A server role, granted by a server administrator, that provisions and bounds organisations: create, import, suspend and enable an organisation, set its module entitlements, and see the organisation list. It cannot delete an organisation, join one as its administrator or read any organisation's records. See [Server administration](../workflows/server-administration.md#server-roles).

#### Policy

A written document published by a server administrator (a privacy policy or a data policy, readable at `/policies` without signing in) or by an organisation's administrators (an access policy or a confidentiality agreement, readable only by that organisation's members, optionally limited to chosen people or groups). Written in a visual editor. Saving changes a working copy; **Publish** records a new version. Distinct from the **Personal data in exports** setting, which decides whether personal data columns may leave the application in a record export. See [Server administration](../workflows/server-administration.md#policies) and [Administering an organisation](../workflows/administering-an-organisation.md#policies).

#### Policy acceptance

The recorded agreement of one person to the current version of a [policy](#policy) that requires it: the person, the version, a fingerprint of the text and the time. Until a person has accepted, they can read but cannot create or change records. A new version asks again. It records acceptance by an account, not a signature. See [Requiring acceptance](../workflows/administering-an-organisation.md#requiring-acceptance).

#### Port

A named point where a connection meets an element, one for each interface, for example "CAN bus" or "Power in". A port is optional; it lets a connection say which interface it uses. Each port has a direction (In, Out or Both) and, optionally, the connection type it expects. See [Elements, ports and connections](../modules/system-architecture-module/elements-ports-and-connections.md).

#### Project

Belongs to exactly one organisation, and can optionally have a parent project, modelling a larger programme as a tree of related projects. See [Organisations and projects](../concepts/organisations-and-projects.md).

#### Project code

A short upper-case code (letters and digits, no hyphen) that identifies a project and goes in front of its record codes where records from several projects appear together. See [Administering an organisation → Project codes](../workflows/administering-an-organisation.md#project-codes).

#### Project group

A named group within a project that a role can be granted to as a whole, so onboarding/offboarding is a matter of group membership rather than individual grants. See [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md).

#### Project role

A role governing what someone can do inside one specific project (`project_manager`, `project_administrator`, `stakeholder`, `member`) — distinct from an [organisation role](#organisation-role). See [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md).

#### Project stage

One step in a project's sequence (e.g. Scoping → Development → Hardening). It follows a [stage workflow](#stage-workflow); entering a Locked phase creates a [baseline](#baseline) and locks the requirements it captured. See [Core Features → Stages and baselining](../core-features/stages-and-baselining.md).

#### Project template

A project marked usable as a template; creating a new project from it copies its components, categories, custom field definitions, groups, and requirements (reset to draft). See [Custom fields, terminology, and templates](../concepts/custom-fields-terminology-and-templates.md).

#### Proposed link

A link a change request carries and an approver merges, or declines, when approving it. See [Change requests → Proposing links](../core-features/change-requests.md#proposing-links).

#### Protocol

The protocol or version a [connection](#connection) carries, such as HTTPS/1.1 or SPI mode 0, held as free text on the connection. A [connection type](#connection-type) can give a default protocol that a new connection of that type starts with. A diagram with connection detail on writes it beside the line, and beside a merged line when all its connections share it. See [Elements, ports and connections](../modules/system-architecture-module/elements-ports-and-connections.md).

#### Qualified code

A record code with its owner's code in front, such as `ACME-REQ-001` (project code) or `ACME-PER-001` (the organisation's code, for a record the organisation owns). The same `REQ-001` exists in every project, so a qualified code is the unambiguous way to name a record. See [Administering an organisation → Project codes](../workflows/administering-an-organisation.md#project-codes).

#### Realises

A relation between two connections on different layers of the model: the connection below lies inside the interface that the connection above declares. A connection of the layer above with none realising it is Not covered in the boundary coverage report. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md).

#### Record code

The short name of a record, such as `REQ-001` (requirement), `PP-001` (pain point), `OQ-001` (open question), `NEED-001` (stakeholder need), `EVD-001` (compliance evidence), `CR-001` (change request), or `PER-001` (Persona), `STK-001` (Stakeholder), `SGP-001` (Stakeholder group), `STR-001` (Strategy), `FUT-001` (Future State) and `GP-001` (Guiding Principle). Numbered per project, or per organisation for a record the organisation owns, and never reused. See [Qualified code](#qualified-code) for the form that is unambiguous across projects.

#### Requirement version

One historical or current state of a requirement's content (name, reasoning, description, status, custom field values). Editing a requirement never overwrites a version — it closes the current one and opens a new one. See [Requirements, versions, and the lifecycle](../concepts/requirements-versions-and-lifecycle.md).

#### Risk treatment verdict

A Risk owner's judgement of whether one linked Requirement or Action actually reduces the Risk: Proposed, Effective, Ineffective or Needs reassessment. Only Effective counts. See [Risk Management → Treatment and relationships](../modules/risk-management-module/treatment-and-relationships.md).

#### Roll-up (rolled-up line)

A line drawn at one level of a block diagram for connections between elements inside the boxes shown, for example a connection between two parts of a subsystem drawn as one line between the subsystems. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md).

#### Shared resource

A file owned by the organisation rather than by one project, such as a standards document. Any requirement in the organisation can link it and a report can append it. It is listed on the organisation Files page, where only a person holding the `manage_org_resources` permission (organisation administrators, or anyone given it through a custom role) can upload or delete it. See [File attachments and shared resources](../core-features/file-attachments-and-shared-resources.md#organisation-wide-shared-resources).

#### Stage workflow

A named, ordered list of phases a project stage moves through. Each phase has a free-text name and a kind (Open, Review, Locked, On hold or Closed) that decides what entering it does. Defined by the organisation (available to every project, which can hide it) or by one project. See [Core Features → Stages and baselining](../core-features/stages-and-baselining.md#workflows-and-phases).

#### Component phases

A per-project setting under which each component follows its own [stage workflow](#stage-workflow) for each stage. A component's Locked phase approves only its own requirements for that stage. See [Core Features → Stages and baselining](../core-features/stages-and-baselining.md#component-phases).

#### Phase schedule

The expected range (an expected start and end, both calendar dates) of a phase of a stage or of a component's track, with its actual start and completion and the upcoming, overdue and completed reminders sent about it. See [Core Features → Stages and baselining](../core-features/stages-and-baselining.md#phase-schedule-and-reminders).

#### State

A mode an element can be in, drawn as a rounded rectangle in a state machine diagram. A state has its own code (`STE-001`) and can be linked to requirements, risks and decisions. It is not the status of a record, which is its lifecycle position such as Draft or Active. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### State machine diagram

A record of the states an element can be in and the transitions between them, drawn in UML state machine notation. Written in running text as a "state machine" once defined. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Storage limit

The most storage an organisation may use for its files and stored report outputs, set by a server administrator or Platform subscription manager (or, for an organisation with none, the deployment's default limit). Reaching it stops new files only; existing files stay readable and deletable. See [Organisation storage](../workflows/server-administration.md#organisation-storage).

#### Subscription removal authority

A server role, granted by a server administrator, that permanently deletes an organisation and all of its data after its name is typed to confirm. It holds no other power: it cannot create, suspend or read records. Independent of the Platform subscription manager. See [Server administration](../workflows/server-administration.md#server-roles).

#### Symbol

A drawing from the System Architecture symbol library (a sanitised SVG, or one of the built-in drawings) that an element or an element type shows in its box. Chosen from a List or a Gallery in the form, where a person who may change the library can also upload a new one. See [Elements, ports and connections](../modules/system-architecture-module/elements-ports-and-connections.md).

#### Task (change request task)

A short follow-up item tied to a change request, with an optional assignee and due date. See [Change requests and baselines](../concepts/change-requests-and-baselines.md).

#### Terminology override

A project-level renaming of a fixed set of nouns (project, stage, component, category, requirement, change request) so a team sees its own vocabulary throughout the UI. See [Custom fields, terminology, and templates](../concepts/custom-fields-terminology-and-templates.md).

#### Tier A / Tier B / Tier C module

The three ways a module can supply its frontend UI: Tier A is compiled directly into the core frontend image, Tier B renders in a sandboxed iframe, and Tier C is loaded dynamically at runtime with no rebuild and no sandbox. See [Modules → Overview](../modules/overview.md) and [Third-party and federated modules](../modules/third-party-and-federated-modules.md).

#### Trace

The window opened from a record's Links panel that follows its links to any depth, as a tree or a map, split into upstream, downstream and related. See [Links and traceability → Tracing where a record comes from](../core-features/links-and-traceability.md#tracing-where-a-record-comes-from).

#### Symbol label

Text drawn with an initial state, final state or choice of a state machine diagram, up to 256 characters, so a branch can say what it decides (for example "Battery low?"). It breaks between words, never inside one. Its **Label position** is inside the symbol (which then grows to hold it), left, right, above or below it (which keeps the symbol's plain size). See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Transition

An arrow between two states of a state machine diagram, labelled `event [guard] / action`. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md).

#### Two-factor authentication (2FA)

An optional TOTP-based second authentication factor a user can enrol in for their own account. See [Core Features → Two-factor authentication](../core-features/two-factor-authentication.md).

#### Validation

The checks of a state machine diagram, listed from the **Validation** button in the editor's toolbar beside **Comment** and **Note**. The button shows a count (the errors, or else the warnings, or none) and opens a list of each **error** and **warning**; choosing one selects the state it concerns. An error stops the diagram becoming Active; a warning never does. See [State machine diagrams](../modules/system-architecture-module/state-machine-diagrams.md#validation).

#### Vertex

A point a line passes through between its two ends (a vertex of the line), so it can go round another box. Drag the dot on the middle of a segment of the selected line to add one, drag a vertex to move it, and double-click it or press Delete on it to remove it; the Selection card lists the vertices with their X and Y positions for use without a pointer. The line's shape (see [Line shape](#line-shape)) decides whether it is drawn as segments or as a curve through them. Available on block diagram connections and on state machine transitions. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md).

#### View switch

A named on/off control on a block diagram that shows or hides a group of elements and connections, for example "Security devices". Flipping it changes only what is shown; hidden elements between two shown ones are bridged by a dashed line. See [Block diagram editor](../modules/system-architecture-module/block-diagram-editor.md).

#### Weighted demand

The sum of the weights of the distinct people and Personas who asked for an [enhancement request](#enhancement-request) (a Stakeholder's Influence level, a Persona's weight), counting each only once. See [Product Feedback → Demand and merging](../modules/product-feedback-module/demand-and-merging.md).

#### WSJF (Weighted Shortest Job First)

A Pain Point scoring model that divides [Cost of Delay](#cost-of-delay) by Job size, so a small piece of work ranks above a large one of the same value. See [Pain Point scoring](../modules/context-strategy-module/pain-point-scoring.md#the-criteria).
