"""
Module: modules.decisions

The Decision Management module: a formal record of project decisions with
configurable types, an approval lifecycle, supersession and org-managed
Decision Templates (seeded ADR packs). Self-contained: this package owns its
enums, models (including comment and attachment tables) and `ModuleDefinition`
(`module`); `service` seeds types and templates. `default_enabled=False`.
"""
