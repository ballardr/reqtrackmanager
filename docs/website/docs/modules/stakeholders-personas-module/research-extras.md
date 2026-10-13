---
sidebar_position: 26.7
---

# Research extras

The research extras add structure for sessions where you ask set questions and learn something from the answers, such as an interview, a focus group or a usability test. They are a sub-component of the module, **off by default**, because the plain [Engagement](./engagement.md) log is enough for most projects.

| Extra | Use it to record |
| --- | --- |
| **Session prompts** | The questions or tasks you put to participants, in order, each with response notes. |
| **Anonymous participants** | People who took part but should not be named: a label such as "Participant 2", and optionally the Persona they represent. |
| **Findings** | What the session taught you, each linkable to the Pain Points, Needs and Open Questions it raised or answered. |

```mermaid
flowchart LR
    E["Engagement<br/>(focus group)"] --> P["Session prompts<br/>+ response notes"]
    E --> A["Anonymous participants<br/>label + Persona"]
    E --> F["Findings"]
    F -->|raised| PP["Pain Point · Need"]
    F -->|answered| OQ["Open Question"]
```

## Turning it on

An organisation admin switches **Research extras** on or off from the organisation's Modules settings, and a project can switch it for itself, the same as the module's other [sub-components](../overview.md#sub-component-enablement-finer-grained-than-a-whole-module). While it is off, the extras are hidden everywhere and the Engagement log still works. Switching it off deletes nothing.

## On an Engagement's page

With the extras on, three more blocks appear on an [Engagement](./engagement.md):

- **Anonymous participants.** Enter a label and, optionally, the **Persona represented**. They count towards the participant total and towards the Persona's evidence in [Persona validation](./reports.md#persona-validation-s2). Use a label, not a name: the record is anonymous only if you keep it so.
- **Session prompts.** Add a prompt, then edit it to record **response notes**. Use the arrows to reorder.
- **Findings.** Add a finding with a title and description, then link what it **raised** or **answered** exactly as for an Engagement. A finding can quote participants.

## Findings are deleted with their Engagement

Findings, prompts and response notes can contain what people said, possibly with names. They therefore have no comments or files of their own and are **permanently deleted with their Engagement**, so erasing an Engagement cannot leave its quotes behind. See [Retention and deletion](./engagement.md#retention-and-deletion).

## Who can do what

The same roles as for Engagements: the **Engagement Owner**, Project Manager, organisation admin or server admin. A finding can also be managed through a fine-grained access grant on findings, which does not allow managing the Engagement it belongs to.

## Where this fits

Findings feed [Engagement & research yield](./reports.md#engagement--research-yield-s5), which counts them against the backlog they produced.
