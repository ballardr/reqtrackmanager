"""
Module: modules

Package root for the modular feature system's first-party module packages
(compliance-module-plan.md Phase 1 onward). Each first-party module lives
in its own subpackage here (e.g. `app.modules.compliance`, added in Phase
5) exposing a `module.py` with a `ModuleDefinition` — see
`app.modules.registry` for the merged registry those definitions feed
into, and how third-party modules (entry points / `EXTRA_MODULES_PATH`)
are discovered alongside them.

This file is also the composition root that appends each first-party
module's `MODULE_DEFINITION` into `app.modules.registry.INSTALLED_MODULES`,
rather than `registry.py` importing them itself. A first-party module's own
`module.py` necessarily imports `ModuleDefinition`/`ModuleRoleDefinition`
*from* `app.modules.registry` to construct its definition — if `registry.py`
also imported that module back (e.g. `from app.modules.compliance.module
import MODULE_DEFINITION`) at its own module scope, the import order would
matter: whichever of the two modules some caller happened to import first
would find the other only partially initialized, a classic circular import.
A package `__init__` is guaranteed by Python's import system to finish
running before any of its submodules can be imported by anyone (importing
`app.modules.registry` or `app.modules.compliance.module` from anywhere
always executes this file first) — so doing the wiring here, importing
`app.modules.registry` to completion *before* importing any first-party
module's own `module.py`, makes the order deterministic regardless of which
submodule some other piece of code imports first.
"""

from app.modules import registry as _registry
from app.modules.compliance.module import MODULE_DEFINITION as _COMPLIANCE_MODULE

_registry.INSTALLED_MODULES.append(_COMPLIANCE_MODULE)
