---
sidebar_position: 48
---

# Known limitations

## Not built yet

- **No search within a request's requesters.** The Demand section pages through them, heaviest first. A name search would have to resolve which requesters you may see, or it would reveal that a hidden one exists.
- **The Links panel is not paged.** A request asked for by a very large number of parties lists every link in the shared Links panel, grouped and collapsible. The Demand section is the paged view.
- **The Grid view is for project requests.** The bulk-edit grid does not cover organisation-owned records, so inbox requests are scored one at a time, or after they are moved into a project.
- **No References column or filter on the list.** References are on the request page, in the export and searchable by key.
- **No channel on the create form's quick link.** Set a requester's channel from the Demand section after adding them.
- **Chosen score models are not in the page address.** A shared link shows the recipient their own columns. Filters are in the address.
- **Report F3 names no one.** Open the request to see who to tell.

## By design

- **No delivery tracking.** Sprints, assignees and boards stay in Jira, ServiceNow or similar. A request carries [references](./external-references-and-channels.md) to the work.
- **No public submission portal.** Requests are made by people with accounts. A portal would be a large abuse and privacy surface.
- **Nothing is sent to requesters.** [Closing the loop](./relationships-and-closing-the-loop.md#closing-the-loop) records who was told; it does not email anyone.
- **No free-text requester.** A requester is a Stakeholder, Persona or Engagement, so erasing a person is done in one place. Someone without a record is added as a Stakeholder, or as a participant of an Engagement, first.
- **No request types.** Use tags. A request's channel and external system are the only lists.
- **Delivered is set manually.** A complete Requirement only prompts **Ready to deliver?**.
- **A merge joins requests of the same owner.** Two requests in one project, or two in the inbox, never one of each. A merge is not a status you can set directly.
- **Moving from the inbox is one-way.** A moved request cannot go back, and a request that already has links or is in a merge cannot be moved.
- **An organisation triager is a triager in every project.** A project's "triagers only" setting cannot exclude one.
- **Scores of different models are not comparable.** The organisation inbox ranks on organisation models only.

## Where this fits

See [Overview](./overview.md) for what the module does support.
