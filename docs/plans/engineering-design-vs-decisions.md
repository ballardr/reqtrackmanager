# ReqTrackManager — Engineering Design vs Decisions

## Purpose

This document clarifies the proposed **Engineering Design** module and, in particular, why engineering designs should be distinct from **Decisions**.

The distinction is important because an architectural design can initially look exactly like an architectural decision. For example:

> "The system will use a three-node active/active architecture."

That could reasonably be called an architectural decision.

The proposed model therefore needs to avoid creating two different objects for the same information merely because one is called "Design" and the other "Decision".

The key distinction is:

- **Decision = the choice and its rationale.**
- **Design = the resulting engineering definition of what was chosen and how it is structured.**

A decision answers:

> **Why did we choose this approach?**

A design answers:

> **What is the engineering solution we are defining, and how is it structured?**

They are related, but they are not necessarily the same thing.

---

# 1. Why Not Just Store Everything as a Decision?

Consider designing a product with a processor, power supply, communications interface and enclosure.

The team may make decisions such as:

- Use an ARM processor rather than x86.
- Use Ethernet rather than Wi-Fi.
- Use a 24 V input rather than 12 V.
- Use aluminium rather than steel for the enclosure.
- Use a particular power architecture.
- Use a particular software architecture.

Those are **choices**.

But after those choices have been made, there is still a substantial amount of engineering definition:

```text
Product
├── Power Architecture
│   ├── 24 V Input
│   ├── Input Protection
│   ├── DC/DC Converter
│   ├── 5 V Rail
│   └── 3.3 V Rail
│
├── Communications Architecture
│   ├── Ethernet Interface
│   ├── CAN Interface
│   └── Internal SPI Bus
│
├── Processing Architecture
│   ├── Main Processor
│   ├── RAM
│   └── Non-volatile Storage
│
└── Mechanical Design
    ├── Enclosure
    ├── Mounting
    └── Thermal Management
```

This hierarchy is not primarily a record of decisions.

It is the **engineering definition of the product**.

The decisions explain why the architecture ended up this way.

---

# 2. A Simple Test

A useful test is:

### Could the information be phrased as "we chose X instead of Y"?

If yes, it is probably a **Decision**.

Examples:

> We chose Ethernet instead of Wi-Fi.

> We chose an ARM processor instead of an x86 processor.

> We chose active/active redundancy instead of active/passive redundancy.

> We chose aluminium instead of steel.

These are decisions because they describe a selection between alternatives.

### Could the information instead be phrased as "the product/system shall be structured like this"?

If yes, it is probably a **Design**.

Examples:

> The product contains two independent Ethernet interfaces.

> The power architecture accepts a 24 V nominal input and provides isolated 5 V and 3.3 V rails.

> The system consists of three compute nodes connected through the internal network.

> The enclosure uses a removable front panel and four mounting points.

These describe the solution itself rather than the act of selecting it.

---

# 3. Decision and Design Are Often Created Together

The distinction does **not** mean every design needs a preceding decision.

In real engineering, they are often intertwined.

### Decision

> Use a three-node active/active compute architecture because the system requires continued operation following a single node failure while avoiding the performance limitations of an active/passive architecture.

### Design

> The compute subsystem consists of three equivalent compute nodes. Each node runs the application services and communicates with the other nodes over the redundant internal network. Service state is replicated between nodes and workload ownership is distributed across the cluster.

The decision explains **why**.

The design defines **what was chosen as the engineering solution**.

---

# 4. Why Not Just Make the Architectural Decision the Design?

This is the strongest argument for simply using Decisions.

It is entirely reasonable to model:

> "Use a three-node active/active architecture"

as an Architectural Decision.

For small projects, that may be sufficient.

The problem appears when the engineering definition becomes more detailed.

Suppose the project has:

```text
Decision:
Use active/active architecture.

Decision:
Use Ethernet between compute nodes.

Decision:
Use redundant power supplies.

Decision:
Use a particular processor family.
```

You now have a collection of decisions, but still need to answer:

> **What exactly is the architecture?**

You could put the complete architecture into one giant decision record, but then the Decision object starts becoming a design document.

Alternatively, you could have dozens or hundreds of decisions that collectively describe the design. That makes it difficult to represent:

- design hierarchy
- components
- interfaces
- allocations
- design parameters
- design revisions
- design baselines
- design reviews
- design-to-requirement coverage
- design-to-design relationships
- engineering specifications

At that point, "Decision" is being used as a generic container for engineering definition.

That is probably not the right abstraction.

---

# 5. Another Important Difference: Decisions Are About Choices, Designs Can Evolve

A design can change without there being a fundamental new decision.

For example:

### Decision

> Use Ethernet as the primary communications technology.

Later the design changes:

```text
Ethernet Interface
├── 1000BASE-T
├── Port A
├── Port B
├── Isolation
├── ESD Protection
└── Connector
```

The physical implementation may change substantially while the original decision remains valid.

For example, the team might change:

- connector type
- PHY
- isolation device
- PCB implementation
- port arrangement

None necessarily requires a new architectural decision.

The **design revision** captures the engineering evolution.

A new decision may be required only if the fundamental choice changes.

---

# 6. Decisions Can Exist Without Designs

The relationship also works in the other direction.

Consider:

> "The product shall target the European market first."

That is a strategy/business decision. There may be no engineering design associated with it yet.

Similarly:

> "The project will use the existing corporate authentication service."

That can be a decision even if the detailed implementation design has not yet been produced.

Therefore:

**Decision should not require Design.**

---

# 7. Designs Can Exist Without a Specific Decision

Likewise, not every design element needs a decision.

Some engineering details are simply implementation of requirements, standards, conventions or established engineering practice.

For example:

> The PCB uses four mounting holes.

There may be no meaningful decision record behind that.

Or:

> The software contains a logging service.

That may simply be part of the design.

Requiring a Decision for every design element would create enormous administrative overhead.

Therefore:

**Design should not require a Decision for every element.**

---

# 8. The Relationship Between the Two

The useful relationship is:

```text
Decision
   │
   ├── Selected
   ├── Constrained
   └── Influences
          │
          ▼
       Design
```

For example:

```text
Decision D-023
"Use active/active compute architecture"
          │
          │ selected
          ▼
Design D-ARCH-004
"Compute Architecture"
          │
          ├── Compute Node 1
          ├── Compute Node 2
          ├── Compute Node 3
          ├── Cluster Network
          └── State Replication
```

The design can then have its own relationships:

```text
Requirement R-101
    │
    │ satisfied by
    ▼
Design D-ARCH-004

Design D-ARCH-004
    │
    ├── refines → System Design
    ├── depends on → Network Design
    ├── interfaces with → Power Design
    └── verified by → Verification V-044

Decision D-023
    │
    │ selected
    ▼
Design D-ARCH-004
```

This produces a richer engineering model.

---

# 9. The Key Concept: Decision = Choice, Design = State

A useful mental model is:

> **A Decision records a transition in thinking. A Design records the resulting engineering state.**

For example:

```text
Options
   │
   ▼
Decision
"Choose active/active"
   │
   ▼
Design
"Three-node active/active architecture"
   │
   ▼
Detailed Design
"Node specifications, network topology,
interfaces, redundancy mechanisms..."
```

The Decision captures the **choice**.

The Design captures the **thing that now exists as a result of that choice**.

---

# 10. Design Is Not the Same as CAD/ECAD/Source Code

The Engineering Design module should **not** attempt to replace:

- CAD
- ECAD
- PCB design software
- simulation tools
- source-control systems
- IDEs
- detailed mechanical drawings
- detailed electrical schematics
- detailed software implementation

Those tools remain the authoritative source for detailed engineering artefacts.

ReqTrackManager instead captures the **engineering definition and relationships around those artefacts**.

For example:

```text
ReqTrackManager

System Design
    │
    ├── Power Architecture
    ├── Communications Architecture
    ├── Mechanical Design
    └── Software Architecture
             │
             └── External artefact:
                 architecture repository/document

Specialist tools

CAD
ECAD
Git
Simulation
PCB CAD
etc.
```

This lets ReqTrackManager answer questions about the engineering system without becoming a CAD/PLM system.

---

# 11. What Should Actually Be a Design?

The Engineering Design module could contain several types of design.

## 11.1 System / Architecture Design

Defines the overall structure.

Examples:

- System architecture
- Product architecture
- Hardware architecture
- Software architecture
- Deployment architecture
- Operational architecture

## 11.2 Component Design

Defines how a subsystem or component is structured.

Examples:

- Power subsystem design
- Motor controller design
- Sensor subsystem design
- Database design
- Communications subsystem design

## 11.3 Interface Design

Defines how things interact.

Examples:

- Electrical interface
- Mechanical interface
- Software API
- Network interface
- Data interface
- Communications protocol

Interfaces are important because they often become some of the most valuable traceability objects in an engineering system.

## 11.4 Detailed Engineering Definition

Examples:

- Component selection
- Electrical characteristics
- Mechanical dimensions
- Thermal characteristics
- Network topology
- Data structures
- Timing characteristics
- Performance parameters
- Environmental characteristics

These may be represented using the existing custom-field mechanism rather than inventing a completely separate arbitrary attribute system.

---

# 12. Design Hierarchy

Designs should be hierarchical.

For example:

```text
Product Design
│
├── System Architecture
│
├── Hardware Architecture
│   ├── Processing Subsystem
│   ├── Power Subsystem
│   └── Communications Subsystem
│
├── Software Architecture
│   ├── Application
│   ├── Data
│   └── Communications
│
└── Mechanical Design
    ├── Enclosure
    ├── Mounting
    └── Thermal Management
```

This hierarchy is different from the project hierarchy.

A project hierarchy describes **how the work/product is organised**.

A design hierarchy describes **how the engineered solution is structured**.

The two can be related but should not be forced to be identical.

---

# 13. Design Alternatives Are Not the Same as Decisions

A Design may have alternatives:

```text
Communications Design

Options:
A. Ethernet
B. Wi-Fi
C. CAN
```

The Decision then records the selection:

```text
Decision:
Select Ethernet.

Rationale:
Required bandwidth and deterministic behaviour
outweigh the installation flexibility of Wi-Fi.
```

After the decision:

```text
Communications Design
    └── Ethernet
```

The alternatives are inputs to the decision, while the resulting Design represents the selected engineering solution.

---

# 14. Design Revisions

Designs should be revision-controlled.

For example:

```text
Power Design
Revision 1
24 V → 5 V + 3.3 V

Revision 2
24 V → isolated 5 V
      │ 3.3 V derived from 5 V
```

The design can therefore have:

- revision
- status
- owner
- reviewer
- approver
- baseline
- change history
- effective date
- superseded-by relationship

The Decision does not need to be rewritten every time implementation detail changes.

If the fundamental architectural choice changes, a new Decision can be created and linked to the new design revision.

---

# 15. Design Reviews

Engineering Design also gives a natural home for design reviews.

A design review could ask:

- Are all applicable requirements addressed?
- Are interfaces defined?
- Are design constraints satisfied?
- Are relevant risks treated?
- Are applicable compliance obligations addressed?
- Are required decisions recorded?
- Are verification methods possible?
- Are external design artefacts available?
- Has the design been approved?

This is substantially different from reviewing whether a Decision was correctly recorded.

---

# 16. Design and Requirements

A particularly important relationship is:

```text
Requirement
     │
     │ satisfied/implemented by
     ▼
Design
```

For example:

### Requirement

> The product shall continue operating following failure of any single compute node.

### Design

> Three compute nodes operate as an active/active cluster with state replication and automatic workload redistribution.

### Decision

> Active/active was selected instead of active/passive because the system requires continued processing capacity following a node failure.

### Verification

> Demonstrate continued operation after intentionally removing one compute node.

This gives four distinct pieces of information:

| Artefact | Question answered |
|---|---|
| Requirement | What must be true? |
| Decision | Why was this approach chosen? |
| Design | What solution are we defining? |
| Verification | How will we prove it? |

This separation is the main justification for having Design as its own artefact type.

---

# 17. Design and Risk

Designs should also be directly connected to risks.

For example:

```text
Risk R-17
Loss of primary power may interrupt operation.

       │
       │ mitigated by
       ▼

Power Design
Dual redundant power supplies
```

A Decision might then explain why dual independent power supplies were selected rather than a single higher-rated supply.

The Design records:

> Two independent supplies feed an OR-ing stage with fault isolation and monitoring.

Again:

- Risk = what could go wrong
- Decision = what treatment was selected
- Design = what the treatment looks like technically

---

# 18. Design and Compliance

Compliance can similarly connect directly to Design.

Example:

```text
Compliance Requirement
EMC emissions limit
       │
       │ addressed by
       ▼
Electrical Design
       │
       ├── filtering
       ├── shielding
       ├── grounding
       └── PCB layout constraints
```

A Decision may explain why one EMC approach was selected over another.

The Design records the actual engineering approach.

---

# 19. Design and Change Management

This distinction becomes particularly valuable for change impact analysis.

Suppose a processor is replaced.

A change analysis could traverse:

```text
Processor Design
   │
   ├── selected by → Decision
   ├── satisfies → Requirements
   ├── interfaces with → Power Design
   ├── interfaces with → Software Architecture
   ├── affects → Compliance
   ├── mitigates → Risk
   └── verified by → Verification
```

This is much more useful than simply knowing that several Decisions mention the processor.

The Design becomes the central engineering object through which the impact graph can be traversed.

---

# 20. Proposed Engineering Design Module

The module should therefore probably contain:

## 20.1 Design Records

A first-class Design object with:

- identifier
- title
- design type
- description
- purpose
- scope
- owner
- status
- revision
- parent design
- assumptions
- constraints
- engineering attributes
- interfaces
- external artefact references
- attachments
- comments
- review history
- approval history
- baseline history

## 20.2 Design Types

Configurable types such as:

- System Architecture
- Hardware Architecture
- Software Architecture
- Mechanical Design
- Electrical Design
- Communications Design
- Network Design
- Data Design
- Interface Design
- Deployment Design
- Operational Design
- Component Design

Projects should be able to configure which types they use.

## 20.3 Design Hierarchy

Designs can contain child designs.

## 20.4 Design Options

A Design may record alternative approaches before selection. These options can be linked to the Decision that ultimately selects one.

## 20.5 Interfaces

Interfaces should initially be a first-class concept within Engineering Design.

An interface could describe:

- source
- destination
- interface type
- protocol
- physical characteristics
- data characteristics
- constraints
- associated requirements
- verification method

This may eventually justify promotion to its own module if it becomes sufficiently substantial.

## 20.6 Engineering Attributes

Designs should support structured engineering properties, potentially reusing the existing custom-field mechanism.

Examples:

```text
Nominal voltage: 24 V
Input range: 18→32 V
Operating temperature: -20 to +60 °C
Mass: 4.2 kg
Network speed: 1 Gbit/s
Ingress protection: IP65
```

## 20.7 Design Traceability

Designs should participate in the common relationship system.

Useful relationships include:

- Implements Requirement
- Satisfies Requirement
- Derived from Requirement
- Selected by Decision
- Constrained by Decision
- Mitigates Risk
- Satisfies Compliance Requirement
- Refines Design
- Depends on Design
- Interfaces with Design
- Supersedes Design
- Verified by
- Validated by

## 20.8 Design Reviews, Approval and Baselines

Designs should support:

- review
- approval
- revision
- baseline
- supersession
- audit history

Governance can determine when approval or baseline is required.

---

# 21. The Proposed Overall Engineering Model

The resulting model becomes:

```text
                    Context
                       │
             ───────────┴──────────
             ▼                   ▼
         Strategy           Pain Point
             │                   │
             ───────────┬──────────
                       ▼
              Stakeholder Need
                       │
                       ▼
                  Requirement
                       │
                       ▼
                    Design
                       ▲
                       │
                    Decision
                       │
                explains why
              ──────────

Risk ────────────────► Requirement
  │
  ────────────────────► Design

Compliance ──────────► Requirement
Compliance ──────────► Design

Design ──────────────► Verification
```

The exact graph will be more complex in the real application, but the important point is that the artefacts answer different questions.

---

# 22. The Important Caveat

There is a genuine argument for **not** making Engineering Design a separate module initially.

If ReqTrackManager's primary purpose is lightweight requirements management, introducing Design as a first-class artefact may be unnecessary complexity.

A simpler system could use:

```text
Requirement
Decision
Evidence
```

and allow Decisions to contain architectural/design information.

That is a perfectly defensible product direction.

The separate Design module becomes justified when ReqTrackManager is intended to manage **engineering definition and traceability**, rather than just requirements and their rationale.

The strongest indicators that Design deserves to be separate are:

1. Designs have their own hierarchy.
2. Designs have their own revisions/baselines.
3. Designs have substantial engineering attributes.
4. Designs have interfaces.
5. Designs can satisfy multiple requirements.
6. Designs depend on other designs.
7. Designs are reviewed and approved independently.
8. Designs participate heavily in change impact analysis.
9. Projects need generated Engineering Specifications.
10. The system needs to represent the current engineering solution, not merely the historical reasoning behind it.

If these are important goals, Design is a meaningful first-class concept.

If they are not, keeping architectural choices inside Decisions would be simpler.

---

# 23. Recommended Boundary for ReqTrackManager

### Decision

A **record of a choice**.

It should capture:

- question/problem
- context
- options considered
- selected option
- rationale
- consequences
- assumptions
- constraints
- who decided
- when
- approval
- supersession

### Design

A **record of the engineering solution/state**.

It should capture:

- what is being designed
- structure
- components/subsystems
- interfaces
- engineering characteristics
- constraints
- relationships
- external engineering artefacts
- revision
- review
- approval
- baseline

A Decision can create or influence a Design, but the Design should not merely be a copy of the Decision.

---

# 24. A Practical Example

Consider a battery-powered industrial controller.

## Requirement

> The controller shall operate for at least 12 hours from the specified battery under the defined operating profile.

## Decisions

**Decision 1**

> Select lithium-ion battery technology rather than lead-acid.

**Decision 2**

> Use a 4S battery configuration.

**Decision 3**

> Use a buck-boost converter for the main regulated supply.

Each of these explains a choice.

## Design

**Battery Power Architecture**

```text
Battery
  │
  ├── Protection
  │
  ├── 4S Battery Management System
  │
  └── Buck-Boost Converter
          │
          ├── 12 V Rail
          ├── 5 V Rail
          └── 3.3 V Rail
```

The Design then contains the engineering definition:

- voltage ranges
- current capability
- connector
- protection
- battery interface
- converter characteristics
- thermal requirements
- interfaces to other subsystems
- applicable requirements
- applicable risks
- verification methods
- external schematic/design files

The Decisions explain why the architecture took this form.

The Design defines what the architecture actually is.

---

# 25. Final Mental Model

The simplest way to think about the distinction is:

```text
Context
   │
Question / Problem
   │
Options
   │
DECISION
"Which way are we going, and why?"
   │
DESIGN
"What does the chosen solution actually look like?"
   │
IMPLEMENTATION
"How is it realised?"
   │
VERIFICATION
"Did we build what was required?"
```

The important refinement is that this is **not necessarily a strict workflow**.

A Design can lead to new Decisions.

A Decision can exist without a Design.

A Design can evolve without a new Decision.

Multiple Decisions can influence one Design.

One Decision can influence multiple Designs.

The value of separating them is therefore not workflow sequencing. It is giving **choice/rationale** and **engineering definition** different semantic meanings.

For ReqTrackManager, I would only keep Engineering Design as a first-class module if the product is intended to capture this latter engineering definition. If the goal remains primarily requirements + rationale + traceability, then architectural Decisions may be enough and the separate module could be unnecessary.
