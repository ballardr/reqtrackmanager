# Data Retention and Disposal Policy

| | |
| --- | --- |
| Policy Owner | **[Name / Title]** |
| Approved By | **[Name / Title]** |
| Effective Date | **[YYYY-MM-DD]** |
| Review Cadence | Annually |
| Applies To | Engineering, Operations |

## Purpose

Satisfies C1.2: disposing of confidential information consistent with the Company's objectives. See [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md) §C1.

## Scope

Covers retention and disposal of customer data, account data, audit/login history, and backups.

## Policy

1. **Retention periods must be defined per data category** and no data class should be retained "indefinitely by default" without that being a deliberate decision. **[Company must complete this table with actual retention periods — recommended starting points below.]**

   | Data category | Recommended minimum | Rationale |
   | --- | --- | --- |
   | Audit events / login history | 1 year | Needed as SOC 2 operating evidence and for incident investigation |
   | Customer content (requirements, change requests, attachments) | Retained for the life of the customer relationship; **[Company must define post-termination retention/export window]** | Customer-owned data |
   | Database backups | **[Company must define, e.g. 30–90 days rolling]** | Balances recovery capability against storage/exposure cost |
   | Deactivated user accounts | **[Company must define]** | See disposal mechanism below — currently deactivation, not deletion |

2. **Disposal must be complete, not merely a visibility change**, when a retention period expires or a customer requests deletion — soft-deletion/deactivation alone does not satisfy a disposal obligation if the underlying data remains fully intact and queryable by design.
3. **Backup media reaching end of retention must be securely disposed of** (deleted, not merely unlinked/left recoverable), consistent with whatever the backup storage provider's own deletion guarantees are.
4. **Uploaded file attachments must be removed from object storage**, not just have their database record removed, when the record they belong to is permanently deleted — an orphaned file left in storage after its owning record is gone is itself a disposal failure.
5. **Legal holds override normal retention/disposal schedules.** **[Company must define its legal hold process.]**

## Roles and Responsibilities

| Role | Responsibility |
| --- | --- |
| Information security owner | Owns the retention schedule |
| Engineering | Implements disposal mechanisms that actually remove data, not just hide it |
| Operations | Executes backup rotation/disposal per schedule |

## Implementation in ReqTrackManager

The current implementation supports **deactivation**, not **hard deletion**, as its access-removal mechanism for individual user accounts and content within a live organization: an organization admin can set `is_active = False` on a member (`backend/app/routers/orgs.py::deactivate_org_user`), which blocks further logins immediately, and the product's broader pattern for lifecycle state (archiving requirements, completing stages) is likewise soft-state transitions on already-versioned rows rather than physical deletion — consistent with the temporal/audit-preserving data model described in `docs/solution-architecture.md` §Data and Workflow Model. This is a deliberate, defensible design for an audit-trail-centric product (you generally do *not* want a requirement's approval history to become un-queryable), but it means **this policy's disposal requirements are not yet met by a "just deactivate it" workflow at the individual user/content level** — see Known Gaps.

**Organizations** are the one aggregate root for which real disposal now exists, alongside a reversible non-disposal option, matching a common commercial need (a hosting customer stops paying, or an org simply needs archiving): a server admin can **disable** an organization (`POST /orgs/{id}/disable` — reversible, blocks all access including the org's own admins, no data touched, see `docs/decisions.md`'s "Organisation disable and hard delete" section) or **hard-delete** it (`DELETE /orgs/{id}`, gated behind typing the organization's exact name to confirm). Hard delete satisfies this policy's disposal-completeness requirement directly: `services/org_deletion.py` plus `ON DELETE CASCADE`/`SET NULL` foreign-key actions across the schema remove every database row the organization owns (projects, requirements, change requests, comments, subscriptions, PAT scope entries) and every associated object-storage file via the existing `delete_file()` path — not merely a visibility flag — while `AuditEvent` rows are preserved with their organization link nulled (audit history survives its subject, per policy item 2's "audit events" retention category). Polymorphic rows with no foreign key, such as artefact links, comments and subscriptions on module artefacts, are found through each module's `artefact_ids_in_organization` registry hook and removed too. Until 2026-10-05 they weren't: an org with linked module data couldn't be deleted at all (it returned a 500), and module comments were orphaned. See `docs/decisions.md`.

**A Stakeholder** (Stakeholders & Personas module) is the first record about an identifiable person that can be hard-deleted inside a live organization, because it holds that person's name and contact information (Confidential personal data) and retirement alone would not meet the disposal rule. `DELETE .../stakeholders/{id}` (a tier-2 confirm in the UI: the exact name must be typed) calls `modules/stakeholders/service.py::erase_stakeholder`, which removes every version row, comment, comment attachment and direct attachment (rows *and* the object-storage bytes, via `delete_file()`), and every `ArtefactLink` touching the record. The one audit event it writes carries only the record id and the acting user; audit events for a stakeholder never carry a name, contact detail or filename, so none need scrubbing afterwards. A test asserts that no row, file, link or personal data is left behind. See `docs/decisions.md`'s "Module 2 Phase 1.2" entry.

Backup tooling (`scripts/backup.sh`) produces timestamped, gzip'd artifacts; nothing in the repository currently expires or rotates them automatically.

## Known Gaps / Exceptions

1. **No general hard-deletion capability exists for individual user accounts or for content within a still-active organization** (a single project, a single user's data) — only deactivation/archival at that granularity. *Narrowed 2026-10-05:* a Stakeholder record (a named person's contact information) can now be permanently erased on its own (see Implementation above); the gap stays open for user accounts, projects, and every other record type. Organizations themselves are no longer part of this gap: `DELETE /orgs/{id}` performs genuine hard deletion of the org and everything it owns, including object-storage files (see Implementation above and `docs/decisions.md`). If the Company makes a contractual or regulatory commitment to erase an individual user's or project's data without deleting the whole organization, that remains a real functional gap needing the same treatment (cascading row removal + storage-file removal) at a finer grain.
2. **No automated backup rotation/expiry** exists — old backup artifacts accumulate until an operator manually removes them.
3. **No retention schedule has been formally adopted** — the table above is a starting recommendation, not a decision.

## Related Documents

[data-classification-and-confidentiality-policy.md](data-classification-and-confidentiality-policy.md), `docs/deployment.md` §Database, `docs/solution-architecture.md` §Temporal data model.
