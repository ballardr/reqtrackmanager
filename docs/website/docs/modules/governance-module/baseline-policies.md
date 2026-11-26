---
sidebar_position: 54
---

# Baseline policies

A **baseline policy** is a set of checks that must pass before a baseline is taken. Without a policy no check runs and a baseline is taken as before.

| Project admin: Baseline policy |
| --- |
| Checks and required fields in force for the Falcon-3 Inspection Drone project, each naming the profile that supplies it |
| ![Baseline policy page with the Checks in force table (Required approvals and Required fields, running before stage baselines, from Regulated programmes), the Required fields in force table and the project's own policy form](../../../static/img/screenshots/governance-baseline-policy.png) |

## When the checks run

A check runs before either kind of baseline, as the policy chooses:

| Kind | When | Default |
| --- | --- | --- |
| **Stage baseline** | A stage enters a locked phase | On |
| **Manual baseline** | A person takes a baseline without a stage | Off, because a manual baseline approves and locks nothing |

A failing check refuses the **whole** baseline. The refusal lists every record and check at fault, and nothing is approved, locked or stored.

```mermaid
flowchart TD
    B["Stage enters a locked phase, or a manual baseline is taken"] --> P{"Does the policy enable checks for this kind?"}
    P -->|no| W["Write the baseline as before"]
    P -->|yes| C["Capture the records once"]
    C --> K["Run each enabled check over the records the baseline would hold"]
    K --> F{"Any failure?"}
    F -->|no| W
    F -->|yes| R["Refuse the whole baseline, listing every failure<br/>Nothing is approved, locked or stored"]
```

## The checks

| Check | Passes when |
| --- | --- |
| **Required fields** | Every record of a chosen type has each chosen field filled. A field is any column of the type's list, so a project's custom fields are included. |
| **Required approvals** | A stage baseline: the person taking it may approve Requirements, and approval separation lets them approve each draft they created, because the stage baseline is itself the approval. A manual baseline: the Requirements are already approved. |

A module can register further checks, which then appear in the same list with no change to Governance. A check that names record types applies only to them.

```mermaid
flowchart LR
    RF["Required fields"] --> POL
    RA["Required approvals"] --> POL
    MOD["A check registered by another module"] --> POL
    POL["Baseline policy of the project<br/>chooses which checks run"] --> DEC{"Every enabled check passes?"}
    DEC -->|yes| OK["Baseline is taken"]
    DEC -->|no| NO["Baseline is refused with every failure"]
```

## Settings

| Setting | Effect |
| --- | --- |
| **Baselines the checks run before** | Stage baseline, Manual baseline or both. At least one is required. |
| **Notify project managers** | Tells the project managers when a failing check stops the automatic approval of a stage at its review deadline. On by default. |
| **Checks** | Which checks run. |
| **Required fields** | The record type and field each requirement names. A profile accepts any field, and offers a project's fields when a project is chosen. A project accepts only its own. |

A stage that the review-deadline sweep cannot approve because a check fails stays in review and is retried daily. The managers are notified once for each distinct set of failures.

## Preview a baseline

**Preview a baseline** at the foot of the page lists the failures that a baseline taken now would be refused over, for a chosen kind of baseline and stage. It writes nothing. It needs **Manage project governance**, because it names the failing records.

## How policies combine

Checks unite across the profiles that apply and the project's own policy; each keeps its own *kinds*. The page lists every check in force with its source. A project that has no policy of its own uses its nearest ancestor project's.

| Action | Permission |
| --- | --- |
| Set a profile's baseline policy | **Manage organisation governance** |
| Set a project's baseline policy, preview a baseline | **Manage project governance** |
| Read the policy in force | Any project member |

See [Stages and baselining](../../core-features/stages-and-baselining.md) for the baseline itself.
