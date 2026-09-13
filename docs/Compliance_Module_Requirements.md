# ReqTrackManager — Compliance Module Requirements

## Overview

Add a **Compliance Module** to ReqTrackManager that allows an organisation to define reusable compliance standards and apply those standards to multiple projects.

A compliance standard is a centrally managed, version-controlled collection of requirements that may apply to one or many projects. Each project independently assesses its compliance against the applicable version of the standard.

The key distinction is:

- A **Compliance Standard** defines what must be satisfied.
- A **Project Compliance** represents a specific project's obligation to comply with a specific version of that standard.
- A **Project Compliance Requirement** records how that project satisfies each requirement.
- A **Required Action** defines activities that must be completed to demonstrate compliance.
- **Evidence** provides supporting documentation or other artefacts for the compliance assessment.

Example use cases include:

- EMC/EMF compliance.
- An organisation's internal security standard.
- Industry standards such as ICOLD.
- Regulatory standards.
- Customer-specific compliance requirements.
- Environmental, safety, quality or engineering standards.

The implementation should integrate naturally with ReqTrackManager's existing organisation, project, requirement, RBAC, versioning, baseline, review, attachment and audit concepts rather than creating parallel mechanisms where existing functionality can be reused.

---

# 1. Module Configuration

The Compliance Module must:

- Be enabled/disabled at the organisation level.
- Be **enabled by default** for existing and newly created organisations.
- When disabled:
  - Compliance functionality should not be presented to users.
  - Existing compliance data must be retained.
  - Re-enabling the module must restore access to existing compliance data.
- Module configuration must be controlled by the Organisation Administrator.

---

# 2. Compliance Standards

A **Compliance Standard** is a reusable collection of compliance requirements managed independently from projects.

Examples:

- EMC/EMF Compliance.
- Corporate Security Standard.
- ICOLD Compliance.
- ISO requirements.
- Customer-specific standards.

A compliance standard should contain:

- Name.
- Description.
- Identifier/reference.
- Issuing organisation, where applicable.
- Owner.
- Status.
- Version information.
- Effective date.
- Requirements.
- Required Actions associated with requirements.
- Appropriate audit/history information.
- Review schedule.

A standard must be capable of being assigned to multiple projects.

A project must not need to duplicate the underlying compliance requirements simply because multiple projects use the same standard.

---

# 3. Compliance Standard Ownership and Permissions

Compliance standards must have their own management permissions.

Introduce an organisation-level role:

## Compliance Manager

A Compliance Manager can:

- Create compliance standards.
- Edit compliance standards.
- Create and edit compliance requirements within standards.
- Define required actions.
- Manage standard versions.
- Publish and retire standard versions.
- Assign standards to projects, subject to appropriate permissions.
- View compliance across projects.
- Manage compliance-related configuration.
- Manage scheduled compliance reviews.
- Manage cross-standard requirement mappings.

Compliance Managers are separate from Organisation Administrators.

Organisation Administrators should retain full access, but it must not be necessary to be an Organisation Administrator to manage compliance standards.

Use ReqTrackManager's existing RBAC patterns where appropriate rather than introducing a completely separate permissions framework.

---

# 4. Compliance Standard Versioning

Compliance standards must be version controlled.

This is important because changing a centrally managed standard must not silently alter the historical compliance assessment of existing projects.

For example:

- Corporate Security Standard v1.0.
- Corporate Security Standard v1.1.
- Corporate Security Standard v2.0.

A project should be associated with a specific version of a compliance standard.

Example:

- Project A → Corporate Security Standard v1.1.
- Project B → Corporate Security Standard v1.0.
- Project C → Corporate Security Standard v2.0.

Changes to a standard should result in a new version/baseline where appropriate rather than modifying the requirements that historical project assessments depend upon.

The implementation should reuse ReqTrackManager's existing versioning/baseline concepts where practical.

A historical Project Compliance record must remain associated with the version of the standard against which it was assessed.

Where a new standard version affects an existing project, the system should provide a controlled mechanism to assess/migrate the project to the new version rather than silently changing its existing assessment.

---

# 5. Compliance Requirements

Compliance requirements should behave similarly to existing requirements but belong to a Compliance Standard rather than directly to a project.

A compliance requirement should support the information and metadata appropriate to existing ReqTrackManager requirements where practical.

A compliance requirement may have zero or more **Required Actions**.

Examples:

- "Equipment shall meet IPX9 water ingress requirements."
- "All privileged accounts shall use multi-factor authentication."
- "The system shall undergo EMC immunity testing."

Compliance requirements should be reusable across all projects assigned to the applicable standard version.

Compliance requirements should support hierarchy/parent-child relationships so that standards can be structured into sections and subsections.

---

# 6. Required Actions

Compliance requirements must support zero or more **Required Actions**.

Use the term "Required Action" rather than "Test", because demonstrating compliance may involve activities other than testing.

Examples:

- Perform IPX9 water ingress test.
- Perform EMC immunity test.
- Review a design document.
- Review a test report.
- Complete a calculation.
- Perform an inspection.
- Obtain an approval.
- Submit evidence.
- Complete a security review.

Required Actions should support:

- Name/description.
- Action type.
- Whether the action is mandatory.
- Status.
- Assignee, where applicable.
- Due date, where applicable.
- Completion information.
- Evidence.
- Notes.

Action types should preferably be configurable/extensible rather than hard-coded to only "Test".

Potential initial action types:

- Test.
- Inspection.
- Document Review.
- Analysis.
- Calculation.
- Design Review.
- Approval.
- Evidence Submission.
- Other.

The data model should allow additional action types to be added in future.

---

# 7. Applying Compliance to a Project

A project can be assigned one or more Compliance Standards.

The association between a project and a compliance standard should be treated as a distinct **Project Compliance** entity.

For example:

Project A:

- EMC/EMF Standard v2.0.
- Corporate Security Standard v3.1.
- ICOLD Standard v1.0.

Project Compliance should record at least:

- Project.
- Compliance Standard.
- Compliance Standard Version.
- Date assigned.
- Target compliance date, if applicable.
- Overall compliance status.
- Compliance Officer(s).
- Review schedule.
- Relevant audit/history information.

The same compliance standard may be assigned to many projects.

Each project must independently assess its compliance.

---

# 8. Project Compliance Requirements

When a standard is applied to a project, each requirement should have a project-specific compliance assessment.

This should be represented separately from the underlying Compliance Requirement.

For example:

```text
Compliance Standard
    EMC/EMF v2.0
        Requirement 1
        Requirement 2
        Requirement 3

Project A
    EMC/EMF v2.0
        Requirement 1 → Compliant
        Requirement 2 → In Progress
        Requirement 3 → Not Applicable

Project B
    EMC/EMF v2.0
        Requirement 1 → Compliant
        Requirement 2 → Non-Compliant
        Requirement 3 → Compliant
```

This allows the same requirement to have different compliance states for different projects.

The project-specific compliance record should support:

- Applicability.
- Compliance status.
- Justification/rationale.
- Notes.
- Evidence.
- Required Action status.
- Assessment date.
- Assessed by.
- Approval/sign-off state.
- Approval/sign-off information.
- Assessment history.

---

# 9. Applicability

Each compliance requirement assigned to a project must support an explicit applicability decision.

Applicability should be:

- Applicable.
- Not Applicable.

If a requirement is marked **Not Applicable**:

- A justification must be provided.
- The justification should be recorded as part of the audit/history.
- The user making the decision must be recorded.
- The date/time of the decision must be recorded.

The Not Applicable state must not simply mean that the requirement is ignored.

It represents an explicit compliance decision.

Only the Project Manager or an authorised Project Compliance Officer may change the applicability state.

## Hierarchical Applicability

Compliance requirements must support hierarchical applicability.

For standards containing sections, groups or parent requirements, applicability must be capable of being determined at different levels.

For example:

```text
4. Environmental Requirements
    |
    +-- 4.1 Temperature
    +-- 4.2 Humidity
    +-- 4.3 Water Ingress
    +-- 4.4 Salt Spray
```

A project should be able to determine that an entire section is Not Applicable where appropriate.

The system must define how applicability is inherited by child requirements.

Expected behaviour:

- Parent marked Not Applicable → child requirements are automatically considered Not Applicable.
- Child requirements may be individually overridden where the standard/process permits this.
- Overrides must require appropriate authorisation and justification.
- Changes to hierarchical applicability must be auditable.
- The UI must clearly distinguish:
  - Explicitly set applicability.
  - Applicability inherited from a parent.
  - An overridden inherited value.

---

# 10. Compliance Status

For requirements that are applicable, the initial compliance status should support at least:

- Not Started.
- In Progress.
- Compliant.
- Non-Compliant.

Consider additional states such as:

- Blocked.
- Pending Review.
- Rejected.

Applicability should remain separate from compliance status.

For example:

```text
Applicability: Applicable
Compliance Status: In Progress
```

or:

```text
Applicability: Not Applicable
Justification: This requirement does not apply to this product configuration.
```

Do not represent Not Applicable simply as another compliance status if separating these concepts produces a cleaner domain model.

---

# 11. Project Compliance Permissions

Introduce a project-level role:

## Compliance Officer

A Compliance Officer can manage compliance assessments for projects to which they are assigned.

For a project:

- Project Managers can manage the project's compliance.
- Assigned Compliance Officers can manage the project's compliance.
- Other users should have read-only access according to existing project permissions.

Project Managers and Compliance Officers may:

- Change applicability.
- Set compliance status.
- Complete/update Required Actions.
- Add justification and notes.
- Add evidence.
- Request/perform assessment.
- Approve/sign off compliance where authorised.
- View compliance history.
- Perform compliance reviews.

The implementation should integrate with the existing project RBAC system.

---

# 12. Formal Compliance Approval / Sign-off

Compliance assessments must support a formal approval/sign-off process.

A Project Compliance Requirement may be assessed as compliant by an authorised Project Manager or Compliance Officer, but the system must support a distinct formal approval/sign-off step.

The system must record:

- Who performed the assessment.
- Who approved/signed off the assessment.
- Date/time of assessment.
- Date/time of approval.
- Previous assessment state.
- Current assessment state.
- Approval/sign-off state.
- Approval/sign-off history.

At minimum, the approval workflow should distinguish:

- Not Assessed.
- Assessed.
- Pending Approval.
- Approved.
- Rejected.
- Requires Re-assessment.

Changes to a requirement, evidence or other compliance information that materially affect an approved assessment should invalidate or require re-approval of the affected approval.

The approval/sign-off workflow should integrate with ReqTrackManager's existing review and approval mechanisms where possible.

---

# 13. Evidence

Compliance decisions must be supported by evidence.

A requirement or Required Action should be able to reference supporting evidence.

Examples:

- Test reports.
- Inspection reports.
- Design documents.
- Calculations.
- Certificates.
- Approval records.
- Security review documents.
- Photographs.
- Other project artefacts.

Reuse ReqTrackManager's existing attachment/file mechanisms where possible rather than implementing a second independent file storage mechanism.

Evidence should retain enough metadata to establish:

- What requirement/action it supports.
- Who provided or attached it.
- When it was provided.
- Issue date.
- Expiry date, where applicable.
- Current validity state.
- Whether it remains applicable.
- Revalidation history.

A single piece of evidence should be capable of supporting multiple compliance requirements and/or standards where appropriate.

---

# 14. Evidence Expiry Dates

Evidence must support an optional expiry date.

Examples:

- A test certificate expires after 12 months.
- A security certification expires on a specific date.
- An inspection report is only valid for a defined period.

Evidence should support:

- Issue date.
- Expiry date.
- Issuing organisation/person, where applicable.
- Evidence status.

The system must be able to identify:

- Valid evidence.
- Evidence approaching expiry.
- Expired evidence.

Expired evidence must not silently continue to be treated as valid supporting evidence.

The system should provide appropriate warnings/notifications when evidence is approaching expiry.

---

# 15. Evidence Validity / Revalidation

Evidence must support explicit validity/revalidation.

Where evidence expires or requires periodic confirmation, an authorised user must be able to revalidate it.

Revalidation must record:

- Who revalidated the evidence.
- Date/time of revalidation.
- New validity/expiry date.
- Optional justification.
- Any supporting evidence or documentation.

The system must retain the previous validity/revalidation history.

Revalidation must not overwrite the historical record.

For example:

```text
IPX9 Test Certificate

Issued:       01/08/2026
Expires:      01/08/2027

Revalidated:  15/07/2027
By:           Jane Smith
New expiry:   15/07/2028
```

The compliance assessment must be able to determine whether the evidence supporting it is currently valid.

Where an approved compliance assessment relies on evidence that subsequently expires or becomes invalid, the system must identify the affected compliance assessment and, where appropriate, require re-assessment/re-approval.

---

# 16. Compliance Rationale and Auditability

Compliance decisions must be auditable.

The system should record:

- Who changed the compliance state.
- When it was changed.
- Previous state.
- New state.
- Who changed applicability.
- Previous applicability.
- New applicability.
- N/A justification.
- Relevant notes.
- Evidence changes.
- Assessment history.
- Approval/sign-off history.
- Revalidation history.

At minimum, the system must provide sufficient history to determine how a project reached its current compliance state.

A requirement should not be able to simply change from "Non-Compliant" to "Compliant" with no indication of who made the change.

For Not Applicable decisions, justification must be mandatory.

A rationale should also be required for Non-Compliant decisions.

---

# 17. Scheduled Compliance Reviews

Compliance Standards and Project Compliance records must support scheduled reviews.

A compliance review should be capable of specifying:

- Review frequency.
- Next review date.
- Review owner.
- Review status.
- Review history.
- Review outcome.
- Notes/evidence associated with the review.

Examples:

- Annual security compliance review.
- Six-monthly environmental compliance review.
- Review before product release.
- Review after a significant standard change.

The system must identify upcoming and overdue compliance reviews.

Completed reviews must be retained as part of the compliance history.

The system should support different review frequencies for different standards and/or project compliance assignments.

Scheduled reviews should be integrated with the notification/reminder system.

---

# 18. Notifications and Reminders

The Compliance Module must support notifications and reminders.

Notifications should be capable of being generated for events including:

- Required Action approaching its due date.
- Required Action becoming overdue.
- Project compliance target date approaching.
- Project compliance target date being exceeded.
- Compliance assessment requiring approval.
- Compliance assessment being rejected.
- Compliance approval becoming invalid due to a change.
- Scheduled compliance review becoming due.
- Scheduled compliance review becoming overdue.
- Evidence approaching expiry.
- Evidence expiring.
- A compliance requirement becoming Non-Compliant.
- A compliance standard being updated where affected projects require review.
- A new compliance assignment requiring action.

Notifications should respect ReqTrackManager's existing notification architecture and user preferences where available.

The system should provide configurable reminder timing where practical.

The notification system should not create a separate notification framework if an existing project-wide mechanism can be reused.

---

# 19. Cross-Standard Requirement Mapping

The system must support mapping requirements between different Compliance Standards.

This is important where multiple standards contain equivalent, related or overlapping requirements.

For example:

```text
ISO 27001
    A.5.15 Access Control
             |
             +--------------+
             |              |
             v              v
Corporate Security      Customer Security
Standard 3.0            Standard 2.1
    SEC-12                  CS-47
```

Requirement mappings should support relationships such as:

- Equivalent.
- Satisfies.
- Derived From.
- Related To.
- Overlaps.
- Conflicts With.

The exact relationship types should be configurable or extensible where practical.

Cross-standard mappings must:

- Be visible from both requirements.
- Be auditable.
- Support navigation between linked requirements.
- Work across different versions of standards where appropriate.
- Not imply that satisfying one requirement automatically satisfies another unless the relationship explicitly supports that behaviour.

The system should allow users to identify where multiple standards impose the same or overlapping compliance obligations.

Cross-standard mappings should support future capabilities such as:

- Identifying duplicate compliance work.
- Showing that one piece of evidence supports multiple standards.
- Understanding the impact of changing a requirement used by multiple standards.
- Reporting on common organisational compliance obligations.

---

# 20. Overall Project Compliance Status

A Project Compliance record should have an overall status calculated from its individual requirements.

The exact calculation must be clearly defined.

For example:

```text
152 total requirements
138 Compliant
7 In Progress
4 Non-Compliant
3 Not Applicable
```

And:

```text
Applicable requirements: 149
Compliant: 138
Compliance: 92.6%
```

Not Applicable requirements should not count against the project's compliance percentage.

However, the UI should always display the actual counts as well as any calculated percentage so that the percentage cannot be misleading.

If any requirement is Non-Compliant, the overall compliance state should clearly indicate this.

Approval/sign-off should be reflected separately from the calculated compliance percentage. A project may have 100% compliant requirements but still have an overall status of "Pending Approval".

The implementation must document the exact rules used to calculate overall state and percentage.

---

# 21. Project Compliance View

Provide a dedicated compliance view for each project.

The view should allow users to see:

- All compliance standards assigned to the project.
- Standard version.
- Overall compliance status.
- Compliance percentage.
- Requirement counts by state.
- Non-Compliant requirements.
- In Progress requirements.
- Not Applicable requirements.
- Required Actions and their status.
- Evidence and evidence validity.
- Evidence approaching expiry.
- Relevant due dates.
- Compliance Officer.
- Approval/sign-off state.
- Scheduled compliance reviews.
- Compliance history.

Users should be able to drill down:

```text
Project
    |
    v
Compliance Standard
    |
    v
Compliance Requirement
    |
    +-- Required Actions
    |
    +-- Evidence
    |
    +-- Assessment
    |
    +-- Approval/Sign-off
```

The view should make it easy for a Project Manager or Compliance Officer to determine what remains outstanding.

---

# 22. Organisation Compliance View

Provide an organisation-level compliance view.

This should allow Compliance Managers and authorised users to see compliance across all projects.

For example:

```text
Standard                    Projects    Compliant    Non-Compliant    In Progress
EMC/EMF v2.0                    12           8              1              3
Security Standard v3             9           4              2              3
ICOLD v1.0                       5           5              0              0
```

The organisation view should support:

- Filtering by compliance standard.
- Filtering by standard version.
- Filtering by project.
- Filtering by compliance state.
- Identifying projects with Non-Compliant requirements.
- Identifying projects with outstanding Required Actions.
- Identifying projects with expired evidence.
- Identifying projects with overdue compliance reviews.
- Identifying compliance assessments awaiting approval.
- Viewing overall compliance percentages.
- Drilling down to individual requirements.

The primary purpose is to answer:

> "Across the organisation, how are all projects performing against the standards they are required to meet?"

---

# 23. Compliance Dashboard

Provide a dashboard summarising:

- Number of active compliance standards.
- Number of projects subject to compliance.
- Overall compliance.
- Non-Compliant projects.
- Projects with outstanding actions.
- Projects with expired evidence.
- Projects with evidence approaching expiry.
- Projects with overdue compliance reviews.
- Assessments awaiting approval.
- Standards with the most outstanding issues.
- Recently changed compliance assessments.
- Upcoming compliance deadlines/reviews.

The dashboard should provide drill-down capability rather than only showing aggregate numbers.

---

# 24. Compliance Lifecycle

The implementation should support a clear lifecycle from defining a standard through to project assessment and ongoing review.

A typical lifecycle should be:

```text
Create Compliance Standard
        |
        v
Define Requirements
        |
        v
Define Required Actions
        |
        v
Publish Standard Version
        |
        v
Assign Standard Version to Project
        |
        v
Determine Applicability
        |
        v
Complete Required Actions
        |
        v
Collect Evidence
        |
        v
Assess Compliance
        |
        v
Formal Approval / Sign-off
        |
        v
Ongoing Compliance
        |
        +--> Evidence Revalidation
        |
        +--> Scheduled Review
        |
        +--> Requirement Changes
        |
        +--> Re-assessment / Re-approval
```

The system should maintain an auditable history throughout this lifecycle.

---

# 25. Data Model Principles

The following is a conceptual model rather than a requirement to use these exact database names:

```text
Organisation
    |
    +-- Compliance Standards
    |       |
    |       +-- Compliance Standard Versions
    |               |
    |               +-- Compliance Requirements
    |                       |
    |                       +-- Child Compliance Requirements
    |                       |
    |                       +-- Required Actions
    |                       |
    |                       +-- Cross-Standard Mappings
    |
    +-- Projects
            |
            +-- Project Compliance
                    |
                    +-- Project Compliance Requirements
                    |       |
                    |       +-- Applicability
                    |       +-- Compliance Status
                    |       +-- Justification
                    |       +-- Evidence
                    |       +-- Required Action Assessments
                    |       +-- Assessment
                    |       +-- Approval / Sign-off
                    |
                    +-- Compliance Reviews
```

Evidence should be capable of being associated with multiple compliance requirements where appropriate.

The exact implementation should follow the existing ReqTrackManager architecture and naming conventions.

---

# 26. Security and Permissions

All compliance functionality must respect existing organisation and project permissions.

At minimum:

## Organisation Administrator

- Full access to organisation compliance functionality.
- Can enable/disable the module.
- Can manage Compliance Managers.

## Compliance Manager

- Manage Compliance Standards.
- Manage standard versions.
- Manage compliance requirements.
- Manage Required Actions.
- Manage cross-standard mappings.
- View compliance across projects.
- Manage organisation-level compliance reviews.

## Project Manager

- View project compliance.
- Modify compliance assessments for their project.
- Modify applicability.
- Complete/manage Required Actions.
- Add evidence.
- Perform assessments.
- Perform authorised approval/sign-off.
- Manage project compliance reviews.

## Compliance Officer

- View project compliance.
- Modify compliance assessments for projects to which they are assigned.
- Modify applicability.
- Complete/manage Required Actions.
- Add evidence.
- Perform assessments.
- Perform authorised approval/sign-off.
- Manage project compliance reviews.

## Other Project Users

- Read access according to existing project permissions.
- No ability to modify compliance state unless explicitly authorised.

Permission checks must be enforced at the API/backend level and not only in the frontend.

---

# 27. Version Changes and Impact Assessment

When a Compliance Standard is updated:

- Existing Project Compliance assignments must remain associated with their original version.
- The system must identify projects using an older version.
- Users should be able to see what changed between standard versions.
- Where appropriate, projects should be able to migrate/adopt a newer version through an explicit action.
- Migration must not silently change historical compliance assessments.
- The system should identify requirements that are:
  - Added.
  - Removed.
  - Modified.
  - Replaced.
  - Re-mapped.
- Where a changed requirement affects an approved project compliance assessment, the system should identify whether reassessment/reapproval is required.

---

# 28. Notifications and Scheduled Processing

Where notifications, evidence expiry and scheduled reviews depend on time, the implementation should provide appropriate scheduled/background processing.

The system should be able to identify:

- Upcoming Required Action deadlines.
- Overdue Required Actions.
- Upcoming compliance target dates.
- Overdue compliance target dates.
- Upcoming evidence expiry.
- Expired evidence.
- Upcoming compliance reviews.
- Overdue compliance reviews.
- Pending approvals.

Use existing ReqTrackManager background/scheduled processing infrastructure where available.

---

# 29. Reporting and Export

The Compliance Module should integrate with ReqTrackManager's existing reporting/export capabilities where appropriate.

Reports should be capable of including:

- Compliance standards.
- Standard versions.
- Compliance requirements.
- Project compliance assessments.
- Required Actions.
- Evidence.
- Evidence validity/expiry.
- Approval/sign-off information.
- Review history.
- Applicability decisions.
- Cross-standard mappings.

Compliance reports should support both:

- Project-level reporting.
- Organisation-level reporting.

The output should be suitable for internal reviews and external audit preparation.

---

# 30. Future-Proofing

The following capabilities are considered part of the required design where they are not already explicitly described above:

- Formal compliance approval/sign-off.
- Hierarchical applicability.
- Notifications and reminders.
- Scheduled compliance reviews.
- Evidence expiry dates.
- Evidence validity/revalidation.
- Cross-standard requirement mapping.

These are **not optional future enhancements**. They must be included in the implementation.

The design should additionally avoid preventing future capabilities such as:

- Automated compliance rules.
- Integration with dedicated test-management systems.
- Automatic compliance determination based on Required Actions.
- Compliance certificates.
- Digital signatures.
- Customer-specific compliance portals.
- Advanced evidence reuse.
- Compliance trend analysis.
- More advanced cross-standard relationship types.

---

# 31. Important Architectural Principles

The implementation must follow these principles:

- A Compliance Standard is **not a Project**.
- Compliance Standards are organisation-level reusable definitions.
- Projects reference specific versions of Compliance Standards.
- Compliance assessments are project-specific.
- A Compliance Requirement must not contain the compliance state of a project.
- Project-specific compliance state belongs to the Project Compliance Requirement.
- Changes to a Compliance Standard must not unexpectedly alter historical project compliance.
- Not Applicable is an explicit applicability decision, not simply an absence of assessment.
- Applicability can be inherited through the requirement hierarchy.
- Compliance decisions must be auditable.
- Evidence must be associated with the relevant compliance requirement/action.
- Evidence validity must be independently tracked.
- Expired evidence must be identifiable and must not silently remain valid.
- Compliance Managers manage standards.
- Project Managers and Compliance Officers manage project compliance.
- Formal approval/sign-off must be distinct from simply setting a compliance state.
- Approved compliance must be re-assessed/re-approved when material underlying information changes.
- Existing ReqTrackManager RBAC, requirements, attachments, versioning, baselines, reviews and audit functionality should be reused where appropriate.
- Avoid duplicating existing infrastructure unnecessarily.
- Follow the existing project's coding, API, database, frontend and documentation conventions.
- Maintain backwards compatibility with existing projects and organisations.
- Add appropriate automated tests for the new domain model, permissions, API behaviour, scheduled processing and UI functionality.

---

# 32. Acceptance Criteria

The feature should be considered complete when:

- An organisation can enable/disable the Compliance Module.
- The module defaults to enabled.
- A Compliance Manager can create and manage Compliance Standards without being an Organisation Administrator.
- A Compliance Standard can contain reusable requirements.
- Compliance requirements can be hierarchical.
- Compliance Standards can be versioned.
- A specific version of a standard can be assigned to multiple projects.
- Each project has an independent compliance assessment.
- Project Managers can manage project compliance.
- Compliance Officers can manage project compliance.
- Users cannot modify project compliance unless authorised.
- Each project-specific requirement can be marked Applicable or Not Applicable.
- Not Applicable requires a justification.
- Hierarchical applicability is supported.
- Applicable requirements support compliance states.
- Requirements support multiple Required Actions.
- Required Actions can represent tests or non-test activities.
- Required Actions can have their own status and supporting evidence.
- Compliance requirements can have supporting evidence.
- Evidence can have expiry dates.
- Evidence validity can be revalidated.
- Evidence revalidation history is retained.
- Expired evidence is identified.
- Compliance assessments can reference evidence.
- Compliance decisions are auditable.
- Formal compliance assessment and approval/sign-off are supported.
- Approval/sign-off history is retained.
- Changes requiring re-assessment/re-approval are identified.
- Scheduled compliance reviews are supported.
- Review history is retained.
- Upcoming and overdue reviews are identified.
- Notifications/reminders are generated for relevant compliance events.
- Cross-standard requirement mappings are supported.
- Cross-standard mappings are navigable from both requirements.
- A project can view its compliance against each assigned standard.
- An organisation can view compliance across all projects.
- Users can identify Non-Compliant requirements and outstanding Required Actions.
- Users can identify expired or soon-to-expire evidence.
- Users can identify overdue compliance reviews.
- Users can identify assessments awaiting approval.
- Compliance percentages and overall statuses are calculated consistently.
- Not Applicable requirements do not count against compliance percentages.
- Historical project compliance is not silently changed when a standard is subsequently modified.
- Standard version changes can be explicitly adopted by projects.
- Appropriate impact/reassessment requirements are identified when standards change.
- Existing ReqTrackManager functionality and permissions continue to work correctly.
- Appropriate backend, frontend, API, scheduled-processing and integration tests are added.
- Documentation is updated to describe the Compliance Module, roles, data model, permissions and workflows.

---

# 33. Implementation Guidance

Before implementing, inspect the existing ReqTrackManager architecture and identify existing mechanisms that can be reused for:

- Organisation settings/features.
- Roles and permissions.
- Requirements and hierarchical requirements.
- Projects.
- Versioning and baselines.
- Reviews and approvals.
- Attachments/evidence.
- Audit history.
- Notifications.
- Background/scheduled jobs.
- Reporting.
- Search/filtering.
- Import/export.

Do not introduce duplicate mechanisms where existing functionality can be extended.

Before making schema/API changes:

1. Understand the existing data model.
2. Identify the smallest set of new domain entities required.
3. Identify existing entities that can be extended.
4. Consider migration and backwards compatibility.
5. Consider how standard versioning interacts with existing baseline/version concepts.
6. Consider how permissions interact with existing organisation/project RBAC.
7. Consider how evidence can be reused across requirements and standards.
8. Consider how scheduled jobs and notifications should integrate with existing infrastructure.

The implementation should be delivered as a cohesive feature rather than a collection of unrelated additions.

All relevant documentation, API specifications, database schemas and user-facing documentation should be updated alongside the implementation.
