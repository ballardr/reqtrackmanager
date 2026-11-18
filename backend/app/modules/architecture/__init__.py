"""
Module: modules.architecture

The System Architecture module: the structure of the product (elements, their
connections and diagrams of them) alongside the requirements.

Responsibilities (this package, as built so far):
- `models`: the element type and connection type vocabularies, and the element,
  port and connection records.
- `service`: the vocabulary resolution, seeding and editing rules.
- `records` / `record_routes`: the rules and the project API for elements, ports and
  connections.
- `router` / `project_router`: the organisation-scoped and project-scoped APIs.
- `summaries`, `search`, `report_fields`, `record_tables`, `scaling_probes`,
  `perf_dataset`, `record_attachments`, `labels`: this module's registrations with
  the shared mechanisms for links, search, reports, export and import, and profiling.
- `export`: the organisation and project bundle sections.
- `module`: this module's `MODULE_DEFINITION`.

Design decisions: a vocabulary is one table with an owner that is either a
project or an organisation (`models.OwnedVocabularyMixin`), so an organisation
default carries the same columns as a project's own row and a project hides a
default instead of overriding it.

External dependencies: core `services.definition_suppression`,
`services.ordering` and `services.audit`; no other module.
"""
