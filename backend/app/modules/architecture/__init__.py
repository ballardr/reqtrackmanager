"""
Module: modules.architecture

The System Architecture module: the structure of the product (elements, their
connections and diagrams of them) alongside the requirements.

Responsibilities (this package, as built so far):
- `models`: the element type and connection type vocabularies.
- `service`: the vocabulary resolution, seeding and editing rules.
- `router` / `project_router`: the organisation-scoped and project-scoped
  vocabulary APIs.
- `export`: the organisation and project bundle sections.
- `module`: this module's `MODULE_DEFINITION`.

Design decisions: a vocabulary is one table with an owner that is either a
project or an organisation (`models.OwnedVocabularyMixin`), so an organisation
default carries the same columns as a project's own row and a project hides a
default instead of overriding it.

External dependencies: core `services.definition_suppression`,
`services.ordering` and `services.audit`; no other module.
"""
