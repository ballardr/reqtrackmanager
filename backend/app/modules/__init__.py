"""
Module: modules

Package root for the modular feature system's first-party module packages. Each first-party module lives in
its own subpackage (for example `app.modules.compliance`) exposing a `module.py` with a `ModuleDefinition`;
`app.modules.registry` merges those definitions and discovers third-party modules (entry points,
`EXTRA_MODULES_PATH`) alongside them.

This file is the composition root that appends each first-party module's `MODULE_DEFINITION` to
`app.modules.registry.INSTALLED_MODULES`, instead of `registry.py` importing them. A module's `module.py`
imports `ModuleDefinition`/`ModuleRoleDefinition` from `app.modules.registry`, so a module-scope import of
the module back into `registry.py` would be a circular import whose result depends on which was imported
first. A package `__init__` finishes before any submodule can be imported, so wiring here, after
`app.modules.registry` is fully imported and before any first-party `module.py`, makes the order
deterministic.
"""

from app.modules import registry as _registry
from app.modules.architecture.module import MODULE_DEFINITION as _ARCHITECTURE_MODULE
from app.modules.compliance.module import MODULE_DEFINITION as _COMPLIANCE_MODULE
from app.modules.context_strategy.module import MODULE_DEFINITION as _CONTEXT_STRATEGY_MODULE
from app.modules.decisions.module import MODULE_DEFINITION as _DECISIONS_MODULE
from app.modules.product_feedback.module import MODULE_DEFINITION as _PRODUCT_FEEDBACK_MODULE
from app.modules.risk_management.module import MODULE_DEFINITION as _RISK_MANAGEMENT_MODULE
from app.modules.stakeholders.module import MODULE_DEFINITION as _STAKEHOLDERS_MODULE
from app.modules.traceability.module import MODULE_DEFINITION as _TRACEABILITY_MODULE

_registry.INSTALLED_MODULES.append(_COMPLIANCE_MODULE)
_registry.INSTALLED_MODULES.append(_DECISIONS_MODULE)
_registry.INSTALLED_MODULES.append(_CONTEXT_STRATEGY_MODULE)
_registry.INSTALLED_MODULES.append(_STAKEHOLDERS_MODULE)
_registry.INSTALLED_MODULES.append(_RISK_MANAGEMENT_MODULE)
_registry.INSTALLED_MODULES.append(_PRODUCT_FEEDBACK_MODULE)
_registry.INSTALLED_MODULES.append(_ARCHITECTURE_MODULE)
_registry.INSTALLED_MODULES.append(_TRACEABILITY_MODULE)
