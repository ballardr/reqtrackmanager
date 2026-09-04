"""
Module: modules

Package root for the modular feature system's first-party module packages
(compliance-module-plan.md Phase 1 onward). Each first-party module lives
in its own subpackage here (e.g. `app.modules.compliance`, added in Phase
5) exposing a `module.py` with a `ModuleDefinition` — see
`app.modules.registry` for the merged registry those definitions feed
into, and how third-party modules (entry points / `EXTRA_MODULES_PATH`)
are discovered alongside them.
"""
