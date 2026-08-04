# Roles and permissions

## Organisation roles

- **Org admin** — manages the organisation itself: branding, SSO settings, shared resource files, report templates, membership, and organisation groups. Does not automatically get access to any project's requirements or change requests.
- **Project creator** — can create new projects inside the organisation.
- **Member** — a plain member of the organisation, with no administrative capability at that level.

## Project roles

- **Project manager** — full control of a project, including everything a project administrator can do, plus approving change requests and project stages.
- **Project administrator** — manages a project's settings, components, categories, custom fields, groups, and report configuration, and can create/edit/archive requirements.
- **Stakeholder** — can create and edit requirements and change requests, vote on change requests, and take part in discussions, but can't change project-level settings.
- **Member** — baseline view access to a project's content.

A role higher up the list includes everything the roles below it can do on that same project.

## A quick way to think about it

If you can see a project at all, you have at least **member** access to it. Whether you can *edit* something usually comes down to whether you're a stakeholder or above on that specific project — being an org admin of the organisation that owns the project isn't enough on its own for requirement/change-request content, by design.
