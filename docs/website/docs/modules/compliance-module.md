---
sidebar_position: 2
---

# Compliance module

The Compliance module lets an organisation define reusable compliance standards (an internal security standard, a regulatory obligation, or a customer-mandated framework), version them, and track each project's own compliance assessment against whichever standards it's assigned — independently of every other project. It ships as one of ReqTrackManager's built-in modules, enabled by default per organisation.

| Compliance standards |
| --- |
| An organisation's compliance standards, each tracked separately with its own issuing organisation and status |
| ![Compliance Standards list showing three standards with their issuing organisations and Active status](../../static/img/screenshots/compliance-standards-list.png) |

## Enabling the module

Compliance defaults to **enabled** for every organisation. A server admin can turn it off deployment-wide (module entitlement), and an org admin can enable or disable it per organisation (module enablement) from the organisation's Modules settings — see [Modules → Overview](./overview.md#gating-entitlement--enablement) for the exact mechanics. Disabling it hides its navigation and endpoints for that organisation; no data is deleted.

## Roles

Compliance defines four of its own roles, module-contributed rather than new core role values (they render through the same role-management UI as every other role):

| Role | Scope | Grants |
| --- | --- | --- |
| **Compliance Manager** | Organisation | Creates and manages compliance standards, versions, requirements, and required actions; assigns standards to projects; views compliance across every project in the organisation. |
| **Compliance Officer** | Project | Modifies a project's compliance assessments, applicability decisions, and evidence, and performs approval/sign-off for the projects they're assigned to. |
| **Standards Manager** | One specific standard | Everything a Compliance Manager can do, but scoped to just this one standard — requirements, versions, publish/retire, and this standard's own "Members" roster. |
| **Standards Contributor** | One specific standard | May edit a draft version's requirements and required actions on this one standard, and propose/discuss changes — may not publish/retire a version or manage the standard's own membership. |

Both Compliance Manager and Compliance Officer compose with the roles that already carry equivalent authority elsewhere in ReqTrackManager: a server admin or an organisation's own org admin can do everything a Compliance Manager can; a project's Project Manager can do everything a Compliance Officer can, on that project. Every other project member (or org member, for standards) has read-only access — granted automatically once the module is enabled, with no role needed just to view.

**Standards Manager/Contributor** (a standard's own dedicated working group, for organisations that maintain standards internally) are narrower still: scoped to one specific standard, not every standard in the organisation. A Compliance Manager already satisfies either check with no per-standard grant needed. A standard's creator is automatically granted Standards Manager on it, and a standard must always have at least one Standards Manager — the last one can't be removed unless another explicit grant, or the organisation's designated fallback compliance-managers group, covers the floor. Manage this roster from a standard's own "Members" section — either role can be granted directly to a person, or to an org group as a whole.

## Data model

A compliance **standard** is an organisation-level, reusable definition — never a project, and never duplicated per project. A standard has one or more **versions**; each version's own requirement tree is immutable once published, so a project that adopts version 1.1 keeps working from exactly that content even after version 2.0 is published or version 1.0 is retired. A project's **assignment** to one specific standard version is where per-project compliance state actually lives — a standard or a requirement definition never itself holds a compliance state.

```mermaid
flowchart TD
    Standard["Compliance Standard<br/>(organisation-level)"] --> Version["Standard Version<br/>draft / published / retired"]
    Version --> Requirement["Compliance Requirement<br/>(hierarchical: sections/subsections)"]
    Requirement --> Action["Required Action<br/>(test, review, inspection, ...)"]

    Project["Project"] --> Assignment["Project Compliance<br/>(assignment to one Standard Version)"]
    Assignment --> PCR["Project Compliance Requirement<br/>applicability + status + approval, per requirement"]
    PCR --> ActionAssessment["Required Action Assessment<br/>status, assignee, due date, per action"]

    Requirement -.defines.-> PCR
    Action -.defines.-> ActionAssessment

    Evidence["Evidence<br/>(project-scoped)"] -.supports.-> PCR
    Evidence -.supports.-> ActionAssessment
```

Every Project Compliance Requirement/Required Action Assessment row is created automatically, in full, the moment a standard version is assigned to a project — nothing is materialised lazily, since a published version's own content can never change underneath an existing assignment.

## Standards lifecycle

A Compliance Manager authors a standard's requirement tree while its current version is in **draft** — creating, editing, reordering, and deleting requirements and required actions freely. **Publishing** a version locks its content permanently (no further edits, ever) and makes it assignable to projects; a version can later be **retired**, which only stops it being offered to *new* assignments — projects already on it keep working from it unchanged. A new version can be cloned from an existing one (carrying its requirement tree forward as a fresh draft) so an update to a standard doesn't mean starting from a blank sheet.

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> Published: publish
    Published --> Retired: retire
    Draft --> Draft: edit requirements/actions
```

## Assigning a standard and assessing a project

A Compliance Manager assigns a **published** version of a standard to a project. From there, the project's Project Manager or Compliance Officer(s) work through the assessment:

- **Applicability** — each requirement is marked Applicable or Not Applicable (with a mandatory justification for Not Applicable), inherited down the requirement hierarchy: marking a parent section Not Applicable makes its children Not Applicable too, unless a child is explicitly overridden back to Applicable. Not Applicable requirements never count against the compliance percentage.
- **Compliance status** — an applicable requirement is assessed Not Started / In Progress / Compliant / Non-Compliant / Blocked / Pending Review / Rejected (a mandatory justification is required for Non-Compliant).
- **Required actions** — each requirement's required actions get their own per-project assessment (status, assignee, due date, completion), independent of the requirement's overall compliance status.
- **Evidence** — a piece of evidence (a certificate, test report, or similar) can support one or many requirements and/or required actions at once. Evidence can carry an expiry date; the module tracks Valid / Expiring Soon / Expired independently, and a revalidation records the previous and new expiry alongside who did it and why, without losing that history.
- **Approval/sign-off** — a formally distinct step from assessment: an assessed requirement is submitted for approval, then approved or rejected, with the decision and its rationale retained. A material change afterwards (the applicability decision changing, or linked evidence being archived/revalidated) automatically flags an approved or pending requirement as **Requires Re-assessment**, so a stale sign-off is never silently left looking current.

| Assessing a standard |
| --- |
| One standard's assignment: overall compliance status, per-status breakdown, and the requirement tree with each requirement's applicability, status, and approval state |
| ![ASA-1 assignment detail showing overall Non-compliant status, a status breakdown, and its requirement tree](../../static/img/screenshots/compliance-assessment-view.png) |

```mermaid
stateDiagram-v2
    [*] --> NotAssessed
    NotAssessed --> Assessed: assess compliance status
    Assessed --> PendingApproval: submit for approval
    PendingApproval --> Approved: approve
    PendingApproval --> Rejected: reject
    Approved --> RequiresReassessment: material change
    PendingApproval --> RequiresReassessment: material change
    RequiresReassessment --> Assessed: re-assess
```

Every applicability/status/approval change is logged to the same audit trail every other ReqTrackManager mutation goes through, viewable per-requirement as its own compliance history.

## Overall status and dashboards

For each assignment, the module calculates a compliance percentage (compliant applicable requirements ÷ all applicable requirements), an overall compliance state (Compliant / Non-Compliant / In Progress / Not Applicable), and an overall approval state — kept as two separate figures, since a project can be 100% compliant while still Pending Approval. A project's own Compliance page shows this per assigned standard, with drill-downs into Non-Compliant requirements, outstanding required actions, expiring/expired evidence, and reviews due. An organisation's Compliance overview rolls the same figures up across every project, with the equivalent cross-project drill-downs and a "standards with the most outstanding issues" summary.

## Scheduled reviews and notifications

A standard itself, or a project's assignment to one, can have one or more scheduled reviews — a frequency label, an optional automatic recurrence, a next-due date, an owner, and (once completed) a retained outcome. Completing a recurring review creates the next cycle as a new row rather than reopening the old one, so review history is never overwritten. Daily background sweeps notify the relevant Compliance Officers/Managers about evidence approaching or past expiry, required actions approaching or past their due date, reviews coming due or overdue, a project's target compliance date approaching or passed, a Non-Compliant assessment, and an approval request or an invalidated approval — each notification sent at most once per underlying event, not repeated on every sweep.

## Cross-standard mapping and version migration

A Compliance Manager can record a directed, typed relationship between any two requirements — even across different standards, or across two versions of the same standard (Equivalent, Satisfies, Derived From, and similar relationship types are themselves an extensible, organisation-defined vocabulary). A mapping is metadata for navigation and impact analysis only; it never implies that satisfying one requirement automatically satisfies another.

When a project wants to move an assignment onto a newer published version of its standard, the two versions can first be **diffed** (added / removed / modified / replaced / re-mapped requirements) so the impact is visible before committing. Migrating is then an explicit, user-triggered action: it creates a new assignment on the new version, carries forward assessments only for requirements that are unchanged (or, with the compliance officer's own per-migration confirmation, explicitly marked equivalent via a mapping), and leaves everything else to be reassessed — the original assignment is archived, never overwritten, so its history is preserved.

## Reporting and export

**Reports.** Both a project's compliance and an organisation's cross-project compliance can be exported as a PDF or CSV report, suitable for internal review and audit preparation — the PDF carries the fuller, multi-section report (main table plus evidence/review/mapping appendices); the CSV carries the flat, one-row-per-requirement (or, at organisation scope, one-row-per-assignment) table.

| Exporting a report |
| --- |
| A project's Compliance page offers a PDF or CSV export of its full assessment |
| ![The Compliance page's Export control open, offering a Download PDF report or Download CSV report choice](../../static/img/screenshots/compliance-report-export.png) |

A project's report covers every requirement's applicability, compliance status, approval state and history, required actions, linked evidence (with validity/expiry), review history, and any cross-standard mappings touching its assigned standards — available to anyone who can view the project's compliance. An organisation's report rolls up across every project (one row per project/assigned-standard-version pair), plus appendices for non-compliant requirements, pending approvals, and expiring/expired evidence across every project — restricted to Compliance Managers.

**Export/import bundles.** Compliance content is included in ReqTrackManager's existing project/organisation export-and-import bundles, at the level the data actually belongs to:

- An **organisation** bundle carries every compliance standard it owns — with its full version/requirement/required-action tree, its action-type and mapping-relationship-type vocabularies, and its cross-standard requirement mappings — since a standard is an organisation-level, reusable resource.
- A **project** bundle carries that project's own compliance *assessment*: which standards it's assigned to, its per-requirement applicability/status/approval state, its required-action assessments, its evidence (with files and revalidation history), and its own project-level review history. It does not re-embed the standard itself; on import, the assignment is resolved against a standard/version of the same reference and version label already present in the target organisation, and is skipped (with a warning, never silently fabricated) if no match exists there.

Both directions round-trip: exporting and re-importing a project or organisation reproduces its compliance data intact.

**Standard-level import/export.** A single standard can also be exported and re-imported on its own, distinct from the whole-organisation bundle above — useful for backing up or transferring just one standard, e.g. into a different organisation or deployment. Every version is always re-created as draft on import, regardless of its original published/retired status — an imported standard must be reviewed and re-published locally before it governs any project, never silently live.

## MCP tools

The Compliance module contributes ten read-only tools to the MCP server an AI assistant can call — listing standards/versions/requirements, a project's overall status, non-compliant requirements, expiring evidence, pending approvals, reviews due, requirement mappings, and a version diff. See [API & Integrations → AI assistants (MCP)](../api-integrations/ai-assistants-mcp/overview.md) for the full, current list with parameters — nothing that approves, decides, or otherwise mutates compliance state is ever exposed there, by the same "approval stays human-only" design as every other approval-shaped action in ReqTrackManager.

## Known limitations

- Compliance reports/exports do not currently support the branded report-template styling (logo, accent colour, cover page) core requirement reports can use — they render with a fixed, unbranded layout.
- A project bundle's compliance assignment can only be restored into an organisation that already has a matching standard/version (by reference and version label) — it is never recreated from the bundle itself. Re-establish the standard first (directly, or via an organisation bundle import) if importing a project into an organisation that doesn't yet have it.
- Automated compliance rules, automatic compliance determination from required-action outcomes, compliance certificates/digital signatures, and customer-facing compliance portals are explicitly out of scope for this module today — the data model is deliberately built so none of them are precluded later.
- Standards Manager/Standards Contributor grants are direct, per-person grants only — there is no way to grant either role to everyone in a group at once (the org's designated fallback compliance-managers group is a narrow floor-satisfaction mechanism only, not a general group-based grant path).

## Where this fits

See [Modules → Overview](./overview.md) for how the module system itself works, and [Modules → Building your own module](./building-your-own-module.md) for how a module like this one is put together.
