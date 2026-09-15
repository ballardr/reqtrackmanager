# ReqTrackManager — Context, Stakeholders, Risks, Decisions, Requirements, Design, Traceability, Governance & Reporting
## Feature Proposal and Requirements

**Status:** Proposed  
**Purpose:** Define the proposed functional architecture and requirements for the next major ReqTrackManager capabilities following the Compliance module.

---

# 1. Executive Summary

ReqTrackManager is intended to evolve beyond a conventional requirements repository into a system that captures the broader context, stakeholders, personas, risks, rationale, decisions, requirements, design, compliance obligations, traceability and generated engineering documentation surrounding engineering and project delivery.

The proposed functionality should allow ReqTrackManager to answer not only:

> What does the system need to do?

but also:

> Why are we changing it?  
> Where are we trying to get to?  
> What principles guide us?  
> What questions remain unresolved?  
> What decisions were made and why?  
> Which requirements support the strategy?  
> Which requirements are derived from higher-level needs?  
> Which requirements satisfy compliance obligations?  
> What verifies the requirements?  
> Which projects are using an organisational standard?  
> What stakeholders and personas are we designing for?  
> Which risks are driving requirements or design mitigations?  
> Are the project's required traceability and governance conditions satisfied?  
> Can the system generate consistent business and engineering documentation from the authoritative project data?

The proposed architecture consists of ten complementary capabilities/modules:

1. **Context & Strategy**
2. **Stakeholders & Personas**
3. **Risk Management**
4. **Decision Management**
5. **Requirements & Requirement Libraries**
6. **Engineering Design**
7. **Traceability**
8. **Governance / Policies**
9. **Compliance** — already being implemented, but should integrate with the new traceability and governance model.
10. **Reporting & Analysis** — generated documentation and analysis derived from authoritative project data.

The modules should be independently useful and, where appropriate, independently enabled for projects.

In particular, **Traceability and Governance must be optional project capabilities**. Simple projects should not be forced to configure complex requirement hierarchies, mandatory links, approval workflows or traceability matrices when those capabilities provide little value.

---

# 2. Design Principles

## 2.1 Lightweight by default

ReqTrackManager should remain useful for simple projects.

A project should be able to use requirements and basic relationships without being forced to configure formal traceability or governance.

## 2.2 Progressive governance

Projects should be able to progressively introduce more formal controls as their maturity, size, risk or regulatory requirements increase.

For example:

### Basic project

- Requirements: enabled
- Decisions: enabled
- Context & Strategy: enabled
- Compliance: disabled
- Traceability: disabled
- Governance: disabled

### Managed project

- Requirements: enabled
- Decisions: enabled
- Context & Strategy: enabled
- Governance: enabled
- Traceability: disabled
- Compliance: optional

### Formal engineering project

- Requirements: enabled
- Decisions: enabled
- Context & Strategy: enabled
- Compliance: enabled
- Traceability: enabled
- Governance: enabled

## 2.3 Relationships are distinct from traceability

Relationships between artefacts should be available independently of the Traceability module.

For example, a project with Traceability disabled should still be able to link:

> PR-102 depends on PR-101

Traceability adds governance around those relationships.

For example:

> Every Project Requirement must derive from at least one Stakeholder Requirement.

Therefore:

- **Relationship:** an actual link between two artefacts.
- **Traceability rule:** a project-defined requirement describing which links are expected or mandatory.

## 2.4 Governance should not destroy flexibility

Mandatory rules should generally affect formal lifecycle transitions rather than preventing users from creating draft work.

For example, a user should normally be able to create a Project Requirement without immediately knowing its upstream source.

However, if the project says that every Project Requirement must derive from a Stakeholder Requirement, the requirement may be prevented from being approved or baselined until the required traceability is satisfied.

## 2.5 Preserve history

Approved strategic statements, principles, decisions, requirement baselines and organisational requirement-set versions should not be silently modified in ways that invalidate historical records.

Where appropriate, revisions or new versions should be created.

---

## 3.1 Module Dependencies and Composition

Modules should be independently useful where practical, but the architecture should explicitly support **module dependencies**. Dependencies should be explicit rather than creating hidden feature coupling.

Recommended configurations:

```text
Simple engineering project
  Requirements + Context & Strategy + Stakeholders & Personas
  + Decisions + Engineering Design

Managed project
  Simple engineering project + Risk Management + Governance

Formal engineering project
  Managed project + Traceability + Compliance

Reporting-enabled project
  Any project configuration + Reporting & Analysis
```

Recommended dependency principles:

- Requirements remain foundational.
- Stakeholders & Personas can be used independently of formal Traceability.
- Risk Management can be used independently, but benefits from links to Context, Requirements, Decisions, Design and Verification.
- Decisions and Engineering Design can be used without formal Governance or Traceability.
- Governance may be useful without Traceability.
- Formal Traceability should require Governance and should depend on the artefact types included in its configured rules.
- Compliance remains a distinct module but may participate in Traceability and Governance.
- Reporting & Analysis should consume authoritative data from enabled modules and should not become a second source of truth.
- Cross-project relationships should be available independently of formal Traceability so nested projects can represent system decomposition naturally.

Enabling a module with dependencies should explain those dependencies and offer to enable them rather than silently introducing substantial functionality.

# 3. Proposed Module Structure

## Module 1 — Context & Strategy

Contains:

- Organisation Strategy
- Project Strategy
- Future State
- Pain Points
- Guiding Principles
- Open Questions

## Module 2 — Stakeholders & Personas

Contains:

- Stakeholders
- Personas
- Stakeholder roles and interests
- Stakeholder needs
- Stakeholder priorities
- Stakeholder-to-requirement relationships
- Stakeholder-to-pain-point relationships
- Stakeholder participation in reviews and approvals where appropriate

## Module 3 — Risk Management

Contains:

- Risks
- Risk categories and types
- Causes, events and consequences
- Likelihood and consequence/severity
- Risk ratings and configurable matrices
- Risk owners
- Risk treatment/mitigation
- Residual risk
- Risk-to-requirement, design, decision and verification relationships
- Risk review and reassessment
- Risk history

## Module 4 — Decision Management

Contains:

- Decision Records
- Decision Types
- Decision lifecycle
- Approval
- Decision history
- Supersession

## Module 5 — Requirements & Requirement Libraries

Contains:

- Requirements
- Requirement Types
- Organisation-level reusable Requirement Sets
- Requirement Set versions
- Project adoption
- Requirement baselines

## Module 6 — Engineering Design

Contains:

- Design artefacts
- Hierarchical designs
- Design options
- Design revisions and baselines
- Design ownership and approval
- Design-to-requirement and design-to-decision traceability

## Module 7 — Traceability

Contains:

- Traceability configuration
- Traceability rules
- Mandatory relationships
- Traceability validation
- Traceability matrices
- Coverage
- Traceability exceptions
- Cross-project traceability

## Module 8 — Governance / Policies

Contains:

- Lifecycle policies
- Approval policies
- Review policies
- Baseline policies
- Governance checks
- Role assignments

## Module 9 — Compliance

The existing Compliance module should remain independently configurable but integrate with:

- Requirements
- Requirement Sets
- Risk Management
- Traceability
- Governance
- Decisions
- Engineering Design
- Verification/actions

## Module 10 — Reporting & Analysis

Contains generated and configurable outputs derived from the authoritative structured data model, including:

- Business Requirements Document
- Engineering Specification
- Executive Gap Analysis
- Engineering Change Impact
- Traceability and coverage reports
- Compliance reports
- Decision logs
- Review and approval packages
- Configurable report templates
- Future AI-assisted analysis

Reporting should be a presentation layer over project data rather than another editable copy of the same information.

# 4. Common Role and Permission Model

The new modules should not rely solely on CRUD permissions.

Most artefacts require four conceptual permission levels:

| Permission | Meaning |
|---|---|
| View | Can view the artefact |
| Propose/Create | Can create or propose an artefact |
| Manage | Can edit, classify, assign, link and administer it |
| Approve/Baseline | Can formally approve or baseline it |

Roles should be configurable rather than assuming that a Project Manager must perform every action.

Potential roles include:

- Project Member
- Project Manager
- Project Administrator
- Requirements Manager
- Decision Owner
- Decision Approver / Decision Maker
- Strategy Owner
- Strategy Approver
- Principle Owner
- Pain Point Manager
- Requirements Approver
- Compliance Manager
- Compliance Approver
- Traceability Manager
- Governance Manager
- Organisation Strategy Manager
- Requirement Set Manager
- Requirement Set Approver

A user may hold several roles.

The system should avoid requiring Organisation Administrator privileges merely to manage specialist engineering content.

---

# 5. Module 1 — Context & Strategy

## 5.1 Purpose

Context & Strategy captures why a project or organisation is changing, what future state is desired, what problems are being addressed, what principles should guide decisions and which questions remain unresolved.

The module provides the context around requirements and decisions.

A useful conceptual distinction is:

- **Pain Point:** Why change is needed.
- **Strategy:** Where we want to go.
- **Future State:** What the desired end state looks like.
- **Guiding Principle:** How decisions should generally be made.
- **Open Question:** What remains unresolved.

---

## 5.2 Organisation Strategy

Strategy should support both organisation-level and project-level scope.

Organisation strategy should capture long-term direction such as:

- Strategic objectives
- Business goals
- Strategic themes
- Organisational future state
- Strategic priorities
- Time horizons
- Measures of success

Example:

> Objective: Reduce operational support costs by 20%.

> Strategic theme: Operational efficiency.

> Desired future state: A common monitoring platform across products.

Organisation strategy should be able to be referenced by projects.

A project may state:

> This project contributes to Organisation Strategy Objective O-12.

This creates a top-down relationship:

**Organisation Strategy → Project Strategy → Requirements → Implementation**

### Strategy scope

The data model should support a strategy scope such as:

- Organisation
- Project

The architecture should allow future scopes such as:

- Portfolio
- Programme

without requiring a fundamental redesign.

---

## 5.3 Project Strategy

Project Strategy captures the strategic direction of an individual project.

It should support:

- Strategic objective
- Current state
- Desired future state
- Rationale
- Expected outcomes
- Constraints
- Measures of success
- Priority
- Time horizon
- Status

Project Strategy should be able to link to organisation strategy.

For example:

> Organisation Objective: Reduce operational cost  
> ↓  
> Project Strategy: Automate manual monitoring  
> ↓  
> Requirements

---

## 5.4 Strategy lifecycle

Suggested lifecycle:

```text
Draft
  ↓
Proposed
  ↓
Under Review
  ↓
Approved
  ↓
Active
  ↓
Superseded / Retired
```

Approved strategy should be revision-controlled.

Historical versions should remain available.

---

## 5.5 Strategy permissions

### Project members

- View published strategy
- Propose strategic items
- Comment
- Provide supporting evidence

### Strategy Owner / Project Manager

- Create
- Edit
- Manage
- Assign ownership
- Manage relationships

### Strategy Approver

- Approve
- Reject
- Retire/supersede

Organisation strategy should use equivalent organisation-level specialist roles.

---

## 5.6 Strategy relationships

Strategy should support typed relationships including:

- Driven by → Pain Point
- Contributes to → Organisation Strategy
- Drives → Requirement
- Informs → Decision
- Guided by → Guiding Principle
- Defines → Future State
- Requires resolution of → Open Question

Relationships should use the common relationship model rather than bespoke one-off link implementations.

---

# 6. Pain Points

## 6.1 Purpose

Pain Points capture existing problems, deficiencies, frustrations, risks or opportunities for improvement that provide a retrospective driver for change.

A Pain Point is not a requirement.

It represents the **problem**, not the desired solution.

---

## 6.2 Pain Point types

Default types:

- Market
- User
- Operator

### Market

Problems observed in the wider market or industry.

### User

Problems experienced by users, customers or stakeholders.

### Operator

Problems experienced by operators, maintainers, support staff or other personnel responsible for operating the system.

The types should be configurable on a per-project basis.

Project administrators should be able to:

- Add types
- Rename types
- Reorder types
- Disable types
- Remove types where no longer used

The organisation may optionally provide default types.

---

## 6.3 Pain Point data

A Pain Point should support:

- Title
- Description
- Type
- Source
- Impact
- Evidence
- Priority / significance
- Status
- Owner
- Date identified
- Related requirements
- Related decisions
- Related strategy
- Related future state
- Related open questions
- Related principles
- Attachments
- Comments

---

## 6.4 Pain Point lifecycle

Suggested lifecycle:

```text
Submitted
   ↓
Triaged
   ├── Rejected
   ├── Duplicate
   └── Accepted
          ↓
       Addressed
          ↓
        Closed
```

---

## 6.5 Pain Point permissions

All project members should generally be able to:

- Create/submit Pain Points
- Comment
- Add evidence
- Suggest links

A designated Pain Point Manager / Project Manager should be able to:

- Triage
- Change classification
- Set priority
- Assign owner
- Merge duplicates
- Reject
- Accept
- Close

This broad creation model is intentional: restricting creation to administrators would prevent the system from capturing problems discovered by ordinary users and operators.

---

## 6.6 Pain Point relationships

Important relationships include:

- Drives → Strategy
- Motivates → Requirement
- Raises → Open Question
- Addresses → Decision
- Related to → Future State

The relationship type should distinguish causation/rationale from generic association.

---

# 7. Future State

Future State may be represented as part of Strategy rather than as a separate top-level artefact initially.

It should describe the desired state that the organisation or project is attempting to reach.

It may include:

- Current state
- Desired state
- Target date
- Outcomes
- Success measures
- Constraints
- Assumptions

Future State should be linkable to:

- Strategy
- Pain Points
- Requirements
- Decisions
- Guiding Principles

If implementation shows that Future State requires more complex lifecycle management, it can later become a first-class artefact without changing the conceptual model.

---

# 8. Guiding Principles

## 8.1 Purpose

Guiding Principles provide enduring guidance that should influence decisions and design.

Examples:

- Prefer open standards over proprietary interfaces.
- Minimise operational complexity.
- Security should be considered by default rather than retrofitted.
- Prefer automated verification over manual verification where practical.

---

## 8.2 Scope

Guiding Principles should support:

- Organisation scope
- Project scope

Organisation principles can be referenced by projects.

Projects can add project-specific principles.

---

## 8.3 Data

A Guiding Principle should contain:

- Name
- Principle statement
- Rationale
- Scope
- Priority
- Status
- Owner
- Version/revision
- Related strategy
- Related decisions
- Related requirements
- Related compliance items where appropriate

---

## 8.4 Permissions

Project members:

- View
- Propose

Principle Owner:

- Create
- Edit
- Manage
- Retire

Approver:

- Approve / activate

Once active, principles should be revision-controlled rather than silently rewritten.

This protects historical Decision rationale.

---

## 8.5 Relationships

Particularly important:

- Strategy → supported by → Guiding Principle
- Decision → guided by → Guiding Principle
- Requirement → informed by → Guiding Principle

---

# 9. Open Questions

## 9.1 Purpose

Open Questions capture unresolved issues that require investigation, discussion or evidence before a decision can be made.

They prevent unresolved issues from being lost in meeting notes, email or chat.

---

## 9.2 Data

Support:

- Question
- Context
- Owner
- Priority
- Status
- Due/review date
- Evidence
- Related Pain Points
- Related Strategy
- Related Requirements
- Related Decisions
- Comments
- Attachments

---

## 9.3 Lifecycle

Suggested:

```text
Open
  ↓
Investigating
  ↓
Ready for Decision
  ↓
Resolved / Withdrawn
```

---

## 9.4 Permissions

Project members:

- Create
- Comment
- Add evidence
- Suggest resolution

Question Owner / Project Manager:

- Assign
- Prioritise
- Change status
- Close

Decision Maker:

- Resolve through a Decision

---

## 9.5 Create Decision from Question

The system should provide a workflow:

> Create Decision from Open Question

The resulting Decision should automatically retain a link to the original question and optionally copy:

- Question
- Context
- Existing evidence
- Relevant links

Relationship:

**Open Question → resolved by → Decision**

---

# 10. Module 2 — Stakeholders & Personas

## 10.1 Purpose

The Stakeholders & Personas module captures the people, groups, organisations and representative user types that have an interest in, are affected by, operate, maintain, regulate or otherwise influence the project. It provides an explicit source for stakeholder needs and requirements rather than requiring requirements to stand alone without context.

A **stakeholder** represents an actual person, group, organisation or stakeholder class. A **persona** represents a representative user or role used to describe expected behaviour, needs and interactions. Personas should normally be modelled as a specialised stakeholder type rather than as an unrelated concept.

The module should support a chain such as:

```text
Stakeholder / Persona
        ↓
Stakeholder Need
        ↓
Stakeholder Requirement
        ↓
Project Requirement
```

It should also support direct contextual relationships such as:

```text
Stakeholder / Persona → experiences → Pain Point
Stakeholder / Persona → has need → Requirement
Stakeholder / Persona → participates in → Decision / Review
```

## 10.2 Stakeholder and Persona Types

Stakeholder types should be configurable per organisation/project, with useful defaults such as:

- Customer
- End user
- Operator
- Maintainer
- Service engineer
- Business owner
- Project sponsor
- Regulator
- Supplier
- Internal engineering team
- Support organisation

Persona examples might include:

- Field Technician
- Safety Officer
- Control Room Operator
- Service Engineer
- Product Administrator
- End Customer

## 10.3 Stakeholder Data

A stakeholder/persona should support:

- Identifier
- Name
- Type
- Description
- Role
- Organisation/group
- Interests
- Responsibilities
- Goals and needs
- Priorities
- Constraints
- Relevant workflows/use scenarios
- Contact/reference information where appropriate
- Project/organisation scope
- Owner
- Status
- Revision/history
- Relationships to other artefacts

## 10.4 Stakeholder Needs

Stakeholder needs should be first-class records where the project requires a distinction between the stakeholder's need and the formal requirement derived from it.

For example:

> Persona: Field Technician

> Need: Diagnose equipment faults quickly while working remotely.

> Requirement: The system shall provide remote diagnostic information within 30 seconds of request.

This distinction allows ReqTrackManager to preserve the original intent while requirements can be written in precise, testable terms.

## 10.5 Relationships

Potential relationships include:

- Has Need
- Experiences Pain Point
- Provides Requirement
- Affected by Requirement
- Consulted on Decision
- Approves / Reviews
- Uses Design / System Element
- Represents Persona

Stakeholder relationships should participate in Traceability when a project chooses to require them.

# 11. Module 3 — Risk Management

## 11.1 Purpose

Risk Management captures uncertainty that could adversely affect project, product, system, safety, performance, cost, schedule, compliance or operational outcomes. Risks are first-class engineering artefacts because requirements and designs may exist specifically to mitigate them.

A risk should not be reduced to a free-text field on a requirement. A first-class risk allows the project to determine whether mitigation is complete, whether residual risk is acceptable and which requirements/design elements exist because of the risk.

## 11.2 Risk Model

The model should support, where appropriate:

- Risk statement
- Cause
- Risk event
- Consequence
- Risk category/type
- Likelihood
- Consequence/severity
- Inherent risk rating
- Risk owner
- Treatment strategy
- Mitigation actions
- Residual likelihood
- Residual consequence/severity
- Residual risk rating
- Acceptance criteria
- Risk status
- Review date
- Evidence and comments
- Revision/history

The exact scoring model should be configurable rather than hard-coded to one organisation's risk matrix.

## 11.3 Risk Types

Risk types should be configurable. Useful defaults may include:

- Safety
- Technical
- Reliability
- Performance
- Security
- Compliance
- Operational
- Schedule
- Cost
- Supply chain
- Integration
- Environmental

## 11.4 Risk Lifecycle

A default lifecycle could be:

```text
Identified
    ↓
Assessed
    ↓
Treatment Planned
    ↓
Treatment in Progress
    ↓
Mitigated / Accepted
    ↓
Closed
```

Alternative outcomes such as Transferred, Avoided, Realised or Rejected may be useful depending on the project's risk process.

## 11.5 Risk-to-Engineering Traceability

Risks should be linkable to the engineering artefacts that address them:

```text
Risk
 ↓
Requirement
 ↓
Design
 ↓
Verification
```

Other useful relationships include:

- Risk → Mitigated by → Requirement
- Risk → Mitigated by → Design
- Risk → Addressed by → Decision
- Risk → Treated by → Action
- Risk → Verified by → Verification
- Risk → Affects → Requirement
- Risk → Affects → Design
- Risk → Related to → Compliance obligation

The system should distinguish between a risk being **linked to** an artefact and the project demonstrating that the artefact provides an effective treatment.

## 11.6 Risk Reviews

Risk reviews should support scheduled reassessment, ownership, status changes, evidence and history. A risk should be able to trigger notifications when it is overdue for review or when a linked requirement/design changes in a way that may invalidate its mitigation.

## 11.7 Risk Permissions

Projects should be able to assign specialist Risk Managers/Owners without requiring Organisation Administrator privileges. Users should be able to propose risks while specialist roles manage assessment, treatment and acceptance.

# 13. Module 4 — Decision Management

## 10.1 Purpose

Decision Management provides a formal record of decisions made during a project's lifecycle.

Decisions may concern:

- Architecture
- Design
- Engineering
- Strategy
- Operations
- Other project-specific areas

A Decision is not restricted to architecture decisions.

---

## 10.2 Decision types

Default types may include:

- Architecture
- Design
- Engineering
- Strategy
- Operational

Types should be configurable per project.

Projects should be able to:

- Add
- Rename
- Reorder
- Disable
- Remove types where appropriate

---

## 10.3 Decision data

A Decision should contain:

- Title
- Decision statement
- Decision type
- Status
- Date
- Decision maker
- Owner
- Context
- Options considered
- Chosen option
- Rationale
- Consequences
- Assumptions
- Constraints
- Related Open Questions
- Related Pain Points
- Related Strategy
- Related Guiding Principles
- Related Requirements
- Related Compliance requirements
- Related Decisions
- Evidence
- Attachments
- Comments

Decision rationale and consequences should be separate structured fields rather than a single free-text description.

---

## 10.4 Decision lifecycle

```text
Draft
  ↓
Proposed
  ↓
Under Review
  ↓
Approved
  ↓
Superseded
```

Rejected decisions should remain available for historical purposes.

---

## 10.5 Decision permissions

### Project Member

- Propose
- Comment
- Provide evidence

### Decision Owner

- Edit
- Manage
- Maintain options
- Prepare for approval

### Decision Maker / Approver

- Approve
- Reject
- Supersede

Decision approval should be role-based but should allow the responsible Decision Maker to vary by Decision.

An architecture Decision might be approved by a technical authority, while a commercial or strategic Decision might be approved by the Project Manager.

---

## 10.6 Decision history

Approved Decisions should not normally be edited in-place in a way that destroys historical meaning.

A later Decision should be able to supersede an earlier Decision.

Example:

```text
Decision D-102
Use REST API
      ↓ superseded by
Decision D-247
Use gRPC
```

The original remains intact.

---

## 10.7 Decision relationships

Supported relationships should include:

- Resolves → Open Question
- Addresses → Pain Point
- Supports / Implements → Strategy
- Guided by / Constrained by → Guiding Principle
- Implements / Affects → Requirement
- Addresses / Constrained by → Compliance
- Depends on → Decision
- Supersedes → Decision
- Conflicts with → Decision

---

# 14. Module 5 — Requirements & Requirement Libraries

## 11.1 Requirement Types

Requirements should support configurable types.

Default:

1. Business Requirement
2. Stakeholder Requirement
3. Project Requirement

The types should be:

- Configurable per project
- Nameable
- Reorderable
- Enable/disable-able

The order is significant.

For example:

```text
Business Requirement
        ↓
Stakeholder Requirement
        ↓
Project Requirement
```

The configured order should also control the default order in reports.

---

# 15. Organisation Requirement Libraries

## 12.1 Purpose

Organisations should be able to maintain reusable collections of requirements that can be adopted by multiple projects.

Examples:

- Environmental requirements
- Corporate engineering requirements
- Cybersecurity requirements
- Safety requirements
- Manufacturing requirements
- Regulatory requirements
- Organisational standards

These should be represented as **Requirement Sets**.

---

## 12.2 Requirement Set

A Requirement Set should contain:

- Name
- Description
- Owner
- Category/type
- Status
- Version
- Effective date
- Review date
- Requirements
- Change history

---

## 12.3 Versioning

Requirement Sets must be explicitly versioned.

For example:

```text
Environmental Requirements
    v1.0
    v1.1
    v2.0
```

A project should target an exact version.

It should not simply state:

> Uses Environmental Requirements.

It should state:

> Targets Environmental Requirements v2.0.

---

## 12.4 Project usage

The organisation should be able to answer:

> Which projects use Environmental Requirements?

and:

> Which version does each project use?

Example:

| Project | Requirement Set | Version |
|---|---|---|
| Project A | Environmental Requirements | 2.0 |
| Project B | Environmental Requirements | 1.1 |
| Project C | Environmental Requirements | 2.0 |

This enables audit and migration analysis.

---

## 12.5 Requirement Set version changes

The system should identify differences between versions:

- Added requirements
- Removed requirements
- Modified requirements
- Retired requirements
- Applicability changes

Projects should not automatically change target versions merely because a new version is published.

The project should explicitly adopt a new version.

---

## 12.6 Requirement Set permissions

Organisation members:

- View published sets

Requirement Set Managers:

- Create
- Edit
- Create versions
- Manage requirements

Requirement Set Approvers:

- Approve
- Publish

This should not require Organisation Administrator permissions.

---

# 16. Project Adoption and Baselining

A project should be able to adopt a specific version of an organisational Requirement Set.

Suggested permissions:

### Project Member

- View adopted sets

### Requirements Manager / Project Manager

- Request adoption
- Request version changes

### Project Approver

- Approve adoption
- Approve version changes
- Baseline adoption

The project should retain the relationship to the exact version adopted.

---

# 17. Module 7 — Traceability

## 14.1 Purpose

Traceability provides a configurable governance framework around relationships between project artefacts.

It should be an **optional project module**.

When disabled:

- Normal relationships remain available.
- No traceability rules are enforced.
- Traceability matrices are unavailable.
- Traceability completeness does not affect baselining.
- Projects can remain lightweight.

When enabled:

- Projects can configure traceability models.
- Mandatory links can be defined.
- Traceability validation is available.
- Traceability matrices are available.
- Coverage reports are available.
- Traceability can participate in governance and baseline checks.

---

# 18. Traceability Rules

A Traceability Rule defines what relationships are expected between artefacts.

Example:

```text
Source:
Project Requirement

Relationship:
Derived From

Target:
Stakeholder Requirement

Minimum Links:
1

Mandatory:
Yes
```

---

## 15.1 Example rules

### Project requirements

Every Project Requirement must derive from at least one Stakeholder Requirement.

### Stakeholder requirements

Every Stakeholder Requirement must trace to either a Business Requirement or an applicable Compliance Requirement.

### Verification

Every Project Requirement must have at least one Verification Action.

---

# 19. Traceability Rule options

The user-facing configuration should support at least:

### No linking required

No upstream traceability is required.

### Type linking required

A link to a specified requirement type is required.

### Type and/or Compliance linking required

A requirement must link to either a specified higher-level requirement type or an applicable Compliance requirement.

The underlying model should be more generic than these labels so future rules can support:

- Required one of several target types
- Required all target types
- Minimum number of links
- Maximum number of links
- Specific relationship types
- Conditional rules

Example:

```text
Project Requirement
    MUST have >= 1
    relationship "Derived From"
    to:
        Business Requirement
        OR
        Compliance Requirement
```

Another:

```text
Project Requirement
    MUST have >= 1
    Business Requirement
    AND
    MUST have >= 1
    Verification Action
```

---

# 20. Traceability enforcement

Traceability should support configurable enforcement levels.

## Informational

A missing relationship is reported but does not prevent lifecycle transitions.

## Warning

A missing relationship is prominently highlighted.

## Required for approval/baseline

The artefact cannot be approved or baselined until the required relationship is satisfied.

The preferred implementation is generally **not to block creation**.

A user should be able to create an incomplete draft.

However, a project can prevent formal approval/baselining until the required relationships exist.

---

# 21. Traceability status

Traceability should become visible as a quality property of an artefact.

Example:

> PR-104 — Implement high-speed data interface
>
> Traceability: Incomplete
>
> Required:
> - Stakeholder Requirement: ✓
> - Business Requirement: ✗
> - Verification Action: ✓
> - Compliance justification: ✓

When the user attempts to baseline:

> Cannot baseline requirement: mandatory traceability is incomplete.

---

# 22. Traceability Exceptions

Legitimate exceptions should be supported without weakening the project's general rules.

A Traceability Exception should contain:

- Requirement/artefact
- Rule being excepted
- Reason
- Requested by
- Approved by
- Expiry/review date
- Evidence
- Comments

The system should report the distinction between:

> Requirement satisfies traceability rule

and:

> Requirement has an approved traceability exception.

This is especially important for audits.

---

# 23. Requirement Type Traceability

Projects should be able to configure expected hierarchy.

Example:

```text
Business Requirement
        ↓
Stakeholder Requirement
        ↓
Project Requirement
```

The project may configure:

> Project Requirement → Derived From → Stakeholder Requirement

as mandatory.

It may also configure:

> Stakeholder Requirement → Derived From → Business Requirement

as optional.

The hierarchy should not be hard-coded globally.

---

# 24. Cross-project Traceability

Traceability should support relationships between nested or related projects.

Example:

```text
Product Project
    Business Requirements
        ↓
Hardware Project
    Project Requirements

Product Project
    Business Requirements
        ↓
Software Project
    Project Requirements
```

This allows a lower-level project requirement to trace back to a higher-level requirement in a parent or related project.

Permissions must still be respected.

A user should only see or create links to artefacts they are authorised to access.

---

# 25. Traceability Matrices

A Traceability Matrix should be a **view generated from the underlying relationship graph**, rather than a separate manually maintained data structure.

Example:

| Business Requirement | Stakeholder Requirement | Project Requirement | Verification |
|---|---|---|---|
| BR-001 | SR-004 | PR-012 | TEST-034 |
| BR-001 | SR-005 | PR-013 | TEST-035 |
| BR-002 | — | PR-017 | — |

Matrices should be able to highlight:

- Missing upstream links
- Orphan requirements
- Requirements without verification
- Requirements without compliance justification
- Uncovered business requirements
- Many-to-one relationships
- One-to-many relationships

---

# 26. Configurable Traceability Matrices

Matrices should not be limited to Business → Stakeholder → Project Requirements.

Users should be able to configure a matrix using artefact types and relationship types.

Examples:

```text
Business Requirements
        ↓
Project Requirements
```

or:

```text
Project Requirements
        ↓
Verification Actions
```

or:

```text
Project Requirements
        ↓
Compliance Requirements
```

or:

```text
Strategy
        ↓
Requirements
        ↓
Decisions
        ↓
Verification
```

---

# 27. Traceability Coverage

The system should provide coverage metrics such as:

- Percentage of requirements with required upstream links
- Percentage with verification
- Percentage with compliance justification
- Number of orphan requirements
- Number of uncovered business requirements
- Number of requirements covered by approved exceptions

Example:

> Requirements Traceability: 91% complete

Traceability coverage should be calculated according to the project's configured rules.

---

# 28. Traceability Configuration Permissions

Organisation:

- May define templates/defaults if desired

Project Administrator / Traceability Manager:

- Enable/disable Traceability
- Configure traceability rules
- Configure matrices
- Configure enforcement levels

Requirements Manager:

- Manage requirement links
- Resolve traceability issues

Project Member:

- Create permitted relationships
- Suggest relationships

Approver:

- Approve/baseline subject to traceability rules

Ordinary users should not be able to remove a mandatory relationship simply because they disagree with the requirement.

Changes to the rule itself should be a governed project configuration action.

---

# 29. Module 8 — Governance / Policies

## 26.1 Purpose

Governance defines **how a project operates**, rather than storing the project's engineering artefacts.

It governs:

- Lifecycle
- Approval
- Review
- Baselining
- Governance checks
- Role responsibilities

Governance should be an **optional project capability**.

---

# 30. Governance versus Traceability

The distinction should be:

### Traceability

Defines:

> Which relationships should exist?

### Governance

Defines:

> What happens if they don't?

For example:

Traceability rule:

> Every Project Requirement must derive from a Stakeholder Requirement.

Governance policy:

> A Project Requirement cannot be baselined until all mandatory traceability requirements are satisfied.

This separation avoids making Traceability responsible for the entire project lifecycle.

---

# 31. Lifecycle Policies

Governance should allow projects to define lifecycle states and transitions.

Example:

### Requirements

```text
Draft
  ↓
Proposed
  ↓
Approved
  ↓
Baselined
  ↓
Retired
```

### Decisions

```text
Draft
  ↓
Proposed
  ↓
Under Review
  ↓
Approved
  ↓
Superseded
```

### Pain Points

```text
Submitted
  ↓
Triaged
  ↓
Accepted
  ↓
Addressed
  ↓
Closed
```

The exact lifecycle should be configurable where appropriate.

---

# 32. Approval Policies

Governance should define which roles can approve different artefact types.

Examples:

> Architecture Decisions require approval by an Architecture Approver.

> Requirements require approval by a Requirements Approver.

> Compliance approval requires a Compliance Approver.

> Strategy changes require Strategy Approver approval.

Policies should reference roles rather than individual people.

---

# 33. Review Policies

Governance should support review schedules.

Examples:

- Requirements reviewed every 12 months
- Strategy reviewed annually
- Compliance evidence reviewed before expiry
- Architecture Decisions reviewed after major architecture changes

Review requirements should support:

- Review interval
- Review owner
- Due date
- Reminder
- Review outcome
- Next review date

---

# 34. Baseline Policies

Governance should be able to define what must be true before an artefact can be baselined.

Example:

```text
Requirement Baseline
    │
    ├── Required fields ✓
    ├── Required approvals ✓
    ├── Traceability ✓
    ├── Verification ✓
    └── Compliance ✓
```

Not all checks need to be enabled for every project.

---

# 35. Governance Health

The system should eventually be able to present project governance health.

Example:

```text
Project Governance Health

Requirements             94%
Traceability              91%
Verification               87%
Compliance                 98%
Decisions                 100%
Open Questions              7 outstanding
```

The exact presentation can evolve, but governance should provide a unified view of whether the project meets its own configured policies.

---

# 36. Governance Permissions

Project Administrator / Governance Manager:

- Enable/disable Governance
- Configure policies
- Configure lifecycle
- Configure approval requirements
- Configure review requirements
- Configure baseline checks
- Assign governance roles

Project members:

- View applicable policies
- Complete assigned actions
- Participate in reviews

Approvers:

- Perform assigned approvals

---

# 37. Module 9 — Compliance Integration

The existing Compliance module should remain independently enabled/disabled.

The new architecture should allow Compliance to participate in Traceability.

For example:

```text
Business Requirement
        ↓
Stakeholder Requirement
        ↓
Project Requirement
        ├── Verified By → Verification Action
        └── Satisfies → Compliance Requirement
```

Traceability rules may require:

> Project Requirement must link to a Business Requirement OR applicable Compliance Requirement.

Governance may then specify:

> The requirement cannot be baselined until the traceability requirement is satisfied.

Compliance approval and evidence validity remain managed by the Compliance module.

---

# 38. Overall Relationship Model

The system should support a common typed relationship model across the new artefacts.

Conceptually:

```text
                         Pain Point
                             │
                             ├── drives ──────────────→ Strategy
                             │
                             ├── motivates ───────────→ Requirement
                             │
                             └── raises ──────────────→ Open Question

Organisation Strategy
          │
          ↓
    Project Strategy
          │
          ├── drives ─────────→ Requirement
          │
          └── informs ────────→ Decision

Guiding Principle
          │
          └── guides ─────────→ Decision

Open Question
          │
          └── resolved by ─────→ Decision

Business Requirement
          │
          └── derives to ──────→ Stakeholder Requirement
                                      │
                                      └── derives to ───→ Project Requirement
                                                               │
                                      ┌────────────────────────┼───────────────┐
                                      ↓                        ↓               ↓
                                  Decision                Compliance      Verification
```

The relationship graph should be extensible so future artefact types can participate without redesigning the entire relationship subsystem.

---

# 39. Relationship Types

Existing typed requirement relationships should be extended/reused where appropriate.

Potential relationships include:

### General

- Related to
- Depends on
- Conflicts with
- Equivalent to

### Requirements

- Derives from
- Refines
- Satisfies
- Implements
- Allocated to
- Verified by
- Validated by

### Context

- Drives
- Motivates
- Addresses
- Informs
- Supports
- Constrains
- Raises

### Decisions

- Resolves
- Supersedes
- Guided by
- Implements
- Affects

The final list should be configurable by organisation/project where appropriate.

---

# 40. Relationship Direction

Relationships should have explicit direction.

For example:

> Project Requirement **derives from** Stakeholder Requirement

is different from:

> Stakeholder Requirement **has derived requirement** Project Requirement

The system should support direction-specific display names.

This is consistent with the existing requirement-link approach and allows users to understand both sides naturally.

---

# 41. Traceability and Relationships

The architectural distinction should be explicit:

```text
Relationship
------------------------------
PR-123
  -- derives from -->
SR-42


Traceability Rule
------------------------------
Project Requirement
  MUST
derive from
  Stakeholder Requirement
```

The first is project data.

The second is project governance/configuration.

This allows normal relationships to remain lightweight while enabling formal traceability when needed.

---

# 42. Example Project Configurations

## 39.1 Simple project

```text
Requirements       ON
Decisions          ON
Context & Strategy ON
Compliance         OFF
Traceability       OFF
Governance         OFF
```

Users can freely create requirements and decisions with optional relationships.

---

## 39.2 Managed project

```text
Requirements       ON
Decisions          ON
Context & Strategy ON
Compliance         OFF
Traceability       OFF
Governance         ON
```

The project may require approvals and reviews but does not require formal requirement hierarchy.

---

## 39.3 Engineering project

```text
Requirements       ON
Decisions          ON
Context & Strategy ON
Compliance         ON
Traceability       ON
Governance         ON
```

The project may require:

- Business → Stakeholder → Project hierarchy
- Verification for Project Requirements
- Compliance links
- Formal approvals
- Baselines
- Periodic reviews

---

# 43. Example End-to-End Traceability

A mature project could represent:

```text
Organisation Strategy
        │
        ↓
Project Strategy
        │
        ↓
Pain Point
        │
        ↓
Business Requirement
        │
        ↓
Stakeholder Requirement
        │
        ↓
Project Requirement
        │
        ├────────→ Compliance Requirement
        │
        ├────────→ Design Decision
        │
        └────────→ Verification Action
```

A separate Open Question might feed the Decision:

```text
Open Question
      │
      ↓
Decision
      │
      ↓
Design / Architecture
```

A Guiding Principle may constrain that Decision:

```text
Guiding Principle
      │
      ↓
Decision
```

This gives ReqTrackManager the ability to answer:

- Why does this requirement exist?
- Which business objective supports it?
- Which problem motivated it?
- Which stakeholder need led to it?
- Which decision implemented it?
- Why was that decision made?
- Which principle influenced the decision?
- Which compliance obligation does it satisfy?
- How is it verified?
- What other artefacts would be affected if it changed?

---

# 44. Baseline and Change Impact

The combined model should support future impact analysis.

If a Decision changes, the system should eventually be able to identify:

```text
Decision
   ↓
Requirements
   ↓
Compliance
   ↓
Verification
```

If an organisation Requirement Set version changes:

```text
Requirement Set v2.0
       ↓
Projects using v2.0
       ↓
Affected requirements
       ↓
Affected verification/compliance
```

If a Pain Point is closed or invalidated:

```text
Pain Point
       ↓
Strategy
       ↓
Requirements
```

This should be considered when designing relationship storage even if full impact-analysis UI is implemented later.

---

# 45. Auditing and History

All governance-sensitive artefacts should retain sufficient history to establish:

- Who created the item
- Who modified it
- When it changed
- What changed
- Who approved it
- When it was approved
- Which version/baseline was active
- Which relationships existed at the relevant point in time
- Which exceptions were approved

This is especially important for:

- Decisions
- Strategy
- Guiding Principles
- Requirement Set versions
- Compliance
- Traceability exceptions
- Baselines

---

# 47. Module 10 — Reporting & Analysis

## 47.1 Purpose

Reporting & Analysis provides generated documentation, analysis and management views from ReqTrackManager's structured engineering data. Reports should be derived from authoritative artefacts, relationships, baselines and configuration rather than requiring users to maintain duplicate documents manually.

The same underlying project information should therefore be usable to produce different views for different audiences.

## 47.2 Authoritative Data Principle

Generated documents are **derived outputs**, not the authoritative source of project information. A generated document should record enough provenance to identify the source state from which it was produced.

At minimum, provenance should include:

- Project
- Generation timestamp
- Baseline/version where applicable
- Included artefact versions
- Report/template definition
- Generator/report version
- Relevant filters and configuration

## 47.3 Business Requirements Document

The Business Requirements Document should present the business rationale and intended outcomes in a form suitable for business stakeholders, customers and project sponsors.

Potential content:

- Purpose and scope
- Business problems and Pain Points
- Stakeholders and Personas
- Stakeholder Needs
- Business objectives and Strategy
- Future State
- Business Requirements
- Relevant constraints and assumptions
- Key Decisions
- Risks and business impacts
- Traceability summary
- Open Questions
- Approval/baseline information

The report should be generated from the structured model rather than requiring a separate business requirements document to be manually maintained.

## 47.4 Engineering Specification

The Engineering Specification should provide a technical description of what the system/product must do and the engineering context in which it will be realised.

Potential content:

- Scope and system context
- Requirement hierarchy
- Requirement types
- Stakeholder and system needs where relevant
- Constraints and assumptions
- Applicable compliance obligations
- Decisions affecting the specification
- Engineering Design relationships
- Interfaces
- Verification/Validation relationships
- Traceability coverage
- Requirement baselines and revision information

The report should be configurable so that different engineering disciplines or project types can define appropriate sections and ordering.

## 47.5 Executive Gap Analysis

Executive Gap Analysis should compare a defined current state against a desired future state and present the significant gaps without requiring executives to navigate the complete engineering model.

Potential analysis dimensions:

- Current capability vs required capability
- Current state vs Future State
- Existing requirements vs target requirements
- Requirement coverage gaps
- Design maturity gaps
- Compliance gaps
- High risks and residual risks
- Open Decisions / Questions
- Major dependencies
- Areas requiring investment or action

The analysis should identify the underlying artefacts supporting each reported gap so that management findings remain traceable to engineering evidence.

## 47.6 Engineering Change Impact

Engineering Change Impact should analyse the consequences of changing an authoritative artefact or baseline. It should use the existing Change Management capability rather than introducing a separate change-control system.

Potential impact traversal:

```text
Changed Requirement
       ↓
Upstream / downstream Requirements
       ↓
Stakeholders / Personas
       ↓
Decisions
       ↓
Designs
       ↓
Interfaces / Child Projects
       ↓
Verification / Validation
       ↓
Compliance
       ↓
Risks and Risk Mitigations
       ↓
Generated Documents / Baselines
```

The report should distinguish:

- Directly linked artefacts
- Transitive/derived impacts
- Potential impacts inferred from relationships or configured rules
- Artefacts requiring review
- Baselines potentially invalidated
- Reports requiring regeneration

This should support both human-authored impact assessment and future AI-assisted impact analysis.

## 47.7 Other Generated Reports

The same reporting infrastructure should support:

- Traceability matrices
- Requirement coverage reports
- Compliance assessments
- Risk registers and risk treatment reports
- Decision registers
- Design descriptions
- Review packages
- Baseline comparison reports
- Requirement-set adoption reports
- Audit/history reports

## 47.8 Configurable Report Templates

Report templates should allow authorised users to configure:

- Included artefact types
- Filters
- Ordering
- Grouping
- Fields
- Relationship traversal
- Matrices
- Summary metrics
- Charts where useful
- Approval/sign-off sections
- Output format

Templates should themselves be versioned so historical generated documents can identify the definition used to create them.

## 47.9 AI-Assisted Analysis

Future AI capabilities should operate on the structured project model and produce proposed analysis rather than silently changing authoritative records. Potential analyses include:

- Missing or weak traceability
- Requirement conflicts
- Orphaned requirements, decisions or designs
- Designs lacking supporting requirements or rationale
- Risks without effective mitigation
- Stale decisions
- Evidence requiring review
- Potentially affected artefacts after a change
- Potential relationships for user confirmation
- Draft report content
- Gaps between current and desired states

AI-generated findings should identify their source artefacts and remain distinguishable from formally approved project information.

# 46. Recommended Implementation Order

The following order reflects both user value and architectural dependencies. Existing Change Management is treated as foundational functionality rather than a future module.

## Phase 1 — Context & Strategy

Implement/complete:

- Strategy
- Future State
- Pain Points
- Guiding Principles
- Open Questions

## Phase 2 — Stakeholders & Personas

Implement:

- Stakeholders
- Personas
- Stakeholder Needs
- Stakeholder relationships

## Phase 3 — Decision Management

Implement:

- Decision Records
- Decision types
- Decision lifecycle
- Approval
- Supersession
- Open Question → Decision creation

## Phase 4 — Requirements & Requirement Libraries

Implement/refine:

- Requirement Types
- Reusable Requirement Sets
- Requirement Set versions
- Project adoption
- Baselines
- Stakeholder/Context/Risk relationships

## Phase 5 — Risk Management and Engineering Design

Implement:

- Risk model and assessment
- Risk treatment/mitigation
- Risk review
- Engineering Design artefacts
- Hierarchical designs
- Design options
- Design baselines
- Requirement/Decision/Risk-to-Design relationships

## Phase 6 — Governance

Implement:

- Lifecycle policies
- Approval policies
- Review policies
- Baseline policies
- Governance health

## Phase 7 — Traceability

Implement:

- Traceability configuration
- Rules
- Enforcement
- Exceptions
- Cross-project relationships
- Matrices
- Coverage

Traceability should depend on Governance and the configured artefact types/rules.

## Phase 8 — Compliance Integration

Integrate the existing Compliance module with:

- Stakeholders/Needs where appropriate
- Risks
- Requirements
- Decisions
- Design
- Traceability
- Governance
- Verification/actions

## Phase 9 — Reporting & Analysis

Implement the common reporting engine and initial reports:

1. Business Requirements Document
2. Engineering Specification
3. Executive Gap Analysis
4. Engineering Change Impact

Then extend the same infrastructure to traceability, compliance, risk, decisions, baselines and other reports.

## Phase 10 — Future Engineering Capabilities

Potential later additions include:

- Verification & Validation Management
- Interfaces as first-class artefacts
- Assumptions & Constraints
- External References / Evidence
- Product variants
- Enhanced system decomposition through nested projects and cross-project traceability
- Semantic search
- AI-assisted analysis

# 48. Key Acceptance Criteria

The overall feature set should satisfy the following high-level requirements.

## Context & Strategy

- Users can record Pain Points.
- Pain Points have configurable project-specific types.
- Default Pain Point types include Market, User and Operator.
- Users can record organisation and project strategy.
- Projects can reference organisation strategy.
- Users can record Guiding Principles.
- Guiding Principles can be organisation- or project-scoped.
- Users can record Open Questions.
- Open Questions can become Decisions.
- All artefacts support appropriate typed relationships.

## Decisions

- Decisions support architecture, design, engineering and strategy use cases.
- Decision types are configurable.
- Decisions have formal lifecycle states.
- Decisions can be approved.
- Approved Decisions retain historical integrity.
- Decisions can supersede previous Decisions.
- Decisions can resolve Open Questions.
- Decisions can record rationale, options and consequences.

## Requirements & Libraries

- Requirement Types are configurable per project.
- Requirement Types can be ordered.
- Organisation Requirement Sets can be created.
- Requirement Sets are versioned.
- Projects target an explicit Requirement Set version.
- Organisations can see which projects use which versions.
- Requirement Set changes can be compared.
- Project adoption is auditable.

## Traceability

- Traceability can be enabled/disabled per project.
- Disabling Traceability does not disable normal relationships.
- Projects can define Traceability Rules.
- Rules can require relationships.
- Rules can target requirement types.
- Rules can target Compliance Requirements.
- Rules can require one or multiple relationships.
- Rules have configurable enforcement.
- Missing mandatory relationships are clearly identified.
- Traceability can prevent approval/baselining where configured.
- Exceptions can be formally approved.
- Traceability Matrices are generated from actual relationships.
- Traceability supports cross-project relationships subject to permissions.

## Governance

- Governance can be enabled/disabled per project.
- Projects can configure lifecycle policies.
- Projects can configure approval policies.
- Projects can configure review policies.
- Projects can configure baseline policies.
- Policies reference roles rather than requiring specific individuals.
- Governance can use Traceability results.
- Governance can use Compliance results.
- Governance checks can provide an overall project health view.

## Compliance Integration

- Compliance remains independently configurable.
- Compliance Requirements can participate in Traceability.
- Compliance evidence and approvals remain managed by Compliance.
- Traceability can require Compliance relationships.
- Governance can require Compliance completion before baseline.

---

## Reporting & Analysis

- Business Requirements Documents can be generated from authoritative project data.
- Engineering Specifications can be generated from requirements, design and related engineering data.
- Executive Gap Analyses can compare defined current and future states.
- Engineering Change Impact reports can identify direct and transitive impacts of an existing change.
- Generated reports record source baseline/version and report/template provenance.
- Report templates are versioned.
- Reports do not silently become a second source of truth.
- AI-assisted analysis is distinguishable from approved project information.

## Stakeholders & Personas

- Stakeholders and Personas can be defined at appropriate organisation/project scope.
- Stakeholder Needs can be linked to Stakeholders/Personas and Requirements.
- Stakeholder relationships are available independently of formal Traceability.
- Stakeholder/Persona changes can participate in Change Impact analysis.

## Risk Management

- Risks can be created, assessed, owned, treated, reviewed and closed.
- Risk scoring is configurable.
- Risks can be linked to requirements, decisions, designs, actions and verification.
- Risk mitigation status can be distinguished from simple relationship existence.
- Risk reviews and history are retained.
- Risk changes can participate in Change Impact analysis.

# 49. Final Architectural Principle

The overall ReqTrackManager model should be thought of as:

```text
                    CONTEXT
                       │
          ┌────────────┼────────────┐
          ↓            ↓            ↓
      Pain Points    Strategy   Principles
          │            │            │
          └────────────┼────────────┘
                       ↓
                  REQUIREMENTS
                       │
                ┌──────┼──────┐
                ↓      ↓      ↓
             Decisions Compliance Verification
                │
                ↓
             Outcomes
```

with:

```text
TRACEABILITY
```

providing the configurable rules describing which relationships are required, and:

```text
GOVERNANCE
```

defining how those requirements affect the lifecycle, approvals, reviews and baselines.

This produces a system that can remain simple when a project does not need formal governance, while supporting sophisticated engineering and compliance programmes when required.

The key architectural separation is:

**Context explains why.**

**Strategy explains where.**

**Principles explain how decisions should generally be made.**

**Open Questions identify what is unresolved.**

**Decisions record what was decided and why.**

**Requirements record what must be achieved.**

**Compliance records external/organisational obligations.**

**Verification records how achievement is demonstrated.**

**Traceability defines which relationships are required.**

**Governance defines how those requirements are enforced.**
