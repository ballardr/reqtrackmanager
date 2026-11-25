"""
Module: services.governance_seams

Resolves, for one project, which module registrations take part in the core engine seams: the policy that applies at a
lifecycle move, approval, review or baseline check, the review schedule of a type and the checks run before a baseline.

Responsibilities:
- Filter the registry's registrations (`modules.registry.get_policy_resolvers`, `get_baseline_check_providers`,
  `get_review_adapters`) to those active in the project: the owning module is on and, when the registration names a
  sub-component, that sub-component is in effect.
- Answer "which policy applies" (`resolve_policy` for one type, `resolve_project_policy` for a seam that reads every
  type at once): the first active resolver that returns one, else `None` so the caller applies the built-in default.

Design decisions:
- A seam never depends on a module being present: with no active registration every function here returns nothing
  and the caller keeps today's behaviour.
- Resolvers and checks only read. Callers decide whether a result blocks anything.

Dependencies: `modules.registry` (registrations and availability), `modules.seams` (contracts).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.modules import registry
from app.modules.seams import BaselineCheckProvider, GovernanceSeam, ReviewAdapter


def registration_active(db: Session, project_id: uuid.UUID, module_key: str, sub_component: str | None) -> bool:
    """Whether a registration of `module_key` applies in the project.

    Args:
        db: An active database session.
        project_id: The project.
        module_key: The module that registered it.
        sub_component: The module's sub-component it depends on, or `None` for the whole module.

    Returns:
        `True` when the module is on for the project and the named sub-component, if any, is in effect.
    """
    if sub_component is None:
        return registry.is_module_enabled_for_project(db, project_id, module_key)
    return registry.is_module_subcomponent_enabled(db, project_id, module_key, sub_component)


def resolve_policy(db: Session, project_id: uuid.UUID, seam: GovernanceSeam, artefact_type: str) -> Any | None:
    """The policy that applies to `artefact_type` in the project at `seam`.

    Args:
        db: An active database session.
        project_id: The project.
        seam: The engine seam asking.
        artefact_type: The registered artefact type being governed.

    Returns:
        The first active resolver's non-`None` answer, in registry order; `None` when no resolver answers, which means
        the type's built-in default applies.
    """
    for module_key, resolver in registry.get_policy_resolvers(seam):
        if resolver.resolve is None or not registration_active(db, project_id, module_key, resolver.sub_component):
            continue
        policy = resolver.resolve(db, project_id, artefact_type)
        if policy is not None:
            return policy
    return None


def resolve_project_policy(db: Session, project_id: uuid.UUID, seam: GovernanceSeam) -> Any | None:
    """The policy that applies to the whole project at `seam`, for a seam that reads every type in one pass.

    Args:
        db: An active database session.
        project_id: The project.
        seam: The engine seam asking.

    Returns:
        The first active project-level resolver's non-`None` answer, in registry order; `None` when no resolver
        answers, which means the built-in default applies.
    """
    for module_key, resolver in registry.get_policy_resolvers(seam):
        if resolver.resolve_project is None or not registration_active(db, project_id, module_key, resolver.sub_component):
            continue
        policy = resolver.resolve_project(db, project_id)
        if policy is not None:
            return policy
    return None


def baseline_checks_for_project(db: Session, project_id: uuid.UUID) -> list[tuple[str, BaselineCheckProvider]]:
    """The baseline checks active in the project, as `("<module_key>:<check key>", provider)` in registry order."""
    return [
        (f"{module_key}:{provider.key}", provider)
        for module_key, provider in registry.get_baseline_check_providers()
        if registration_active(db, project_id, module_key, provider.sub_component)
    ]


def review_adapter_for_project(db: Session, project_id: uuid.UUID, artefact_type: str) -> ReviewAdapter | None:
    """The review adapter of `artefact_type` when its owning module is on in the project, else `None`."""
    entry = registry.get_review_adapters().get(artefact_type)
    if entry is None:
        return None
    module_key, adapter = entry
    return adapter if registration_active(db, project_id, module_key, None) else None
