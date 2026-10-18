---
sidebar_position: 2
---

# Glossary

Terminology introduced across this site, gathered into one alphabetical reference. Each entry links back to the page that explains it in full.

#### Advisory stakeholder vote

A visible approve/reject signal a stakeholder can cast on a change request. It never approves or rejects the change itself — only a manager's or administrator's explicit decision does. See [Change requests and baselines](../concepts/change-requests-and-baselines.md).

#### Audit trail

The record of security- and administration-relevant events (logins, permission grants, password changes), independent of any one requirement's own change log — *who did what* across the system. See [Discussions, notifications, and audit](../concepts/discussions-notifications-and-audit.md).

#### Baseline

A permanent snapshot of every requirement that was in draft or reviewed status at the moment a project stage was approved. Answers "what did we commit to" reliably, even after later changes. See [Change requests and baselines](../concepts/change-requests-and-baselines.md).

#### Change log

The formal, versioned history of a requirement or change request: who changed what, and when, as part of the governed content itself — distinct from its discussion thread. See [Discussions, notifications, and audit](../concepts/discussions-notifications-and-audit.md).

#### Change request

The only way to modify a locked (Approved or Completed) requirement: a proposal with its own reasoning, targeted fields, and an explicit approve/reject decision from a project manager or administrator. See [Change requests and baselines](../concepts/change-requests-and-baselines.md).

#### Custom field

A project-defined attribute (short text, long text, checkbox, or option list) attached to requirements or change requests, versioned alongside every built-in field. See [Custom fields, terminology, and templates](../concepts/custom-fields-terminology-and-templates.md).

#### Direct grant

A project role assigned to one specific user — the default and simplest way to grant access, as opposed to a [project group](#project-group). See [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md).

#### Discussion thread

Informal comments (which can carry file attachments) for the conversation around a requirement or change request, kept deliberately separate from its formal [change log](#change-log). See [Discussions, notifications, and audit](../concepts/discussions-notifications-and-audit.md).

#### Enablement

The org-tier switch turning a [module](#module) on for one specific organisation, among whichever modules it's entitled to. See [Modules → Overview](../modules/overview.md).

#### Entitlement

The server-tier licensing lever controlling whether an organisation is allowed to use a given [module](#module) at all, independent of whether the organisation has actually turned it on. See [Modules → Overview](../modules/overview.md).

#### Identity (requirement identity)

The part of a requirement that never changes once created: its project, component, category, generated ID, creator, and archival state. Distinct from its versioned content. See [Requirements, versions, and the lifecycle](../concepts/requirements-versions-and-lifecycle.md).

#### Lifecycle (requirement lifecycle)

The fixed sequence a requirement moves through: Draft → Reviewed → Approved → Completed, with Archived available as an exit from Draft or Reviewed. See [Requirements, versions, and the lifecycle](../concepts/requirements-versions-and-lifecycle.md).

#### Link

A typed relationship between two records of the same project (or a parent and child project), shown in the **Links** panel on both records. Its [link type](#link-type) names it from each end. See [Links and traceability](../core-features/links-and-traceability.md).

#### Link type

The named, directional relationship a [link](#link) carries ("Derives from" / "Is source of"). An organisation defines them, a project may add its own, and each can limit which kinds of record it joins. See [Links and traceability → Link types](../core-features/links-and-traceability.md#link-types).

#### Locking

What happens once a requirement reaches Approved or Completed: its edit form disables, and further change must go through a [change request](#change-request) rather than a silent edit. See [Requirements, versions, and the lifecycle](../concepts/requirements-versions-and-lifecycle.md).

#### Module

A self-contained, optional capability area (backend endpoints, database tables, RBAC roles, frontend pages, optionally AI-assistant tools) gated by [entitlement](#entitlement) and [enablement](#enablement) rather than permanently built into the core application. Compliance, Decision Management, Context & Strategy, Stakeholders & Personas, and Risk Management are the modules shipped so far. See [Modules → Overview](../modules/overview.md).

#### Organisation

The top-level container, owning users, groups, branding, SSO configuration, and every project underneath it. See [Organisations and projects](../concepts/organisations-and-projects.md).

#### Organisation role

A role governing organisation-wide administration (`org_admin`, `project_creator`, `member`) — distinct from a [project role](#project-role). See [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md).

#### Personal access token (PAT)

A long-lived, org/project-scoped bearer credential for non-interactive use, such as scripting against the REST API or connecting an AI assistant. See [Core Features → Personal access tokens](../core-features/personal-access-tokens.md).

#### Project

Belongs to exactly one organisation, and can optionally have a parent project, modelling a larger programme as a tree of related projects. See [Organisations and projects](../concepts/organisations-and-projects.md).

#### Project code

A short upper-case code (letters and digits, no hyphen) that identifies a project and goes in front of its record codes where records from several projects appear together. See [Administering an organisation → Project codes](../workflows/administering-an-organisation.md#project-codes).

#### Project group

A named group within a project that a role can be granted to as a whole, so onboarding/offboarding is a matter of group membership rather than individual grants. See [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md).

#### Project role

A role governing what someone can do inside one specific project (`project_manager`, `project_administrator`, `stakeholder`, `member`) — distinct from an [organisation role](#organisation-role). See [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md).

#### Project stage

One step in a project's sequence (e.g. Scoping → Development → Hardening). Approving a stage creates a [baseline](#baseline) and locks the requirements it captured. See [Core Features → Stages and baselining](../core-features/stages-and-baselining.md).

#### Project template

A project marked usable as a template; creating a new project from it copies its components, categories, custom field definitions, groups, and requirements (reset to draft). See [Custom fields, terminology, and templates](../concepts/custom-fields-terminology-and-templates.md).

#### Proposed link

A link a change request carries and an approver merges, or declines, when approving it. See [Change requests → Proposing links](../core-features/change-requests.md#proposing-links).

#### Qualified code

A record code with its project code in front, such as `ACME-REQ-001`. The same `REQ-001` exists in every project, so a qualified code is the unambiguous way to name a record. See [Administering an organisation → Project codes](../workflows/administering-an-organisation.md#project-codes).

#### Record code

The short, project-scoped name of a record, such as `REQ-001` (requirement), `PP-001` (pain point), `OQ-001` (open question), `NEED-001` (stakeholder need), `EVD-001` (compliance evidence) or `CR-001` (change request). Numbered per project and never reused. See [Qualified code](#qualified-code) for the form that is unambiguous across projects.

#### Report content

The introduction, chapters and appendices written for a report type at the template, project or organisation level, with `{{placeholders}}` filled at generation. See [Reports and export → Report content](../core-features/reports-and-export.md#report-content).

#### Requirement version

One historical or current state of a requirement's content (name, reasoning, description, status, custom field values). Editing a requirement never overwrites a version — it closes the current one and opens a new one. See [Requirements, versions, and the lifecycle](../concepts/requirements-versions-and-lifecycle.md).

#### Risk treatment verdict

A Risk owner's judgement of whether one linked Requirement or Action actually reduces the Risk: Proposed, Effective, Ineffective or Needs reassessment. Only Effective counts. See [Risk Management → Treatment and relationships](../modules/risk-management-module/treatment-and-relationships.md).

#### Task (change request task)

A short follow-up item tied to a change request, with an optional assignee and due date. See [Change requests and baselines](../concepts/change-requests-and-baselines.md).

#### Terminology override

A project-level renaming of a fixed set of nouns (project, stage, component, category, requirement, change request) so a team sees its own vocabulary throughout the UI. See [Custom fields, terminology, and templates](../concepts/custom-fields-terminology-and-templates.md).

#### Tier A / Tier B / Tier C module

The three ways a module can supply its frontend UI: Tier A is compiled directly into the core frontend image, Tier B renders in a sandboxed iframe, and Tier C is loaded dynamically at runtime with no rebuild and no sandbox. See [Modules → Overview](../modules/overview.md) and [Third-party and federated modules](../modules/third-party-and-federated-modules.md).

#### Trace

The window opened from a record's Links panel that follows its links to any depth, as a tree or a map, split into upstream, downstream and related. See [Links and traceability → Tracing where a record comes from](../core-features/links-and-traceability.md#tracing-where-a-record-comes-from).

#### Two-factor authentication (2FA)

An optional TOTP-based second authentication factor a user can enrol in for their own account. See [Core Features → Two-factor authentication](../core-features/two-factor-authentication.md).
