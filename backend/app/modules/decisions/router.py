"""
Module: modules.decisions.router

Decision Management's Phase 4 org-scoped API
(docs/plans/module-04-decision-management-plan.md Phase 4) — CRUD for
`DecisionTemplateDefinition`, the org-managed, opt-in-seeded ADR template
packs (Phase 0 addendum items 1/6/7). Mounted at `/api/v1/orgs/
{organization_id}/modules/decisions`.

RBAC: reads are gated by `require_org_module_enabled("decisions")`
(`_require_view`) — any org member with the module enabled may browse the
template picker. Mutations additionally require `OrgRole.ORG_ADMIN`
(`_require_template_manage`): Decision Management declares no org-scoped
module role of its own (`module.py`'s two roles, `decision_owner`/
`decision_approver`, are both `scope="project"` — there is no natural
"org-scoped Decision Owner" concept the way Compliance's `compliance_
manager` is, since a Decision itself is always project-scoped and only its
*templates* live at the org level). Rather than inventing a new org-scoped
module role solely to gate a small, low-traffic CRUD surface, this reuses
the plain `OrgRole.ORG_ADMIN` check the same way `routers.orgs`' own
org-scoped project-status/link-type definition endpoints do (no module
role there either). **Decided by: Agent** — see Phase 4 notes in the plan
for the fuller reasoning and the alternative considered (a new org-scoped
role) and why it was rejected as premature.

A `DecisionTemplateDefinition` has no persistent FK from `Decision`
(Phase 0 addendum item 6 — a template is a creation-time convenience, not
a relationship), so `delete_template` is a plain delete: no `reassign_
to_id`/`delete_definition_with_reassignment` machinery, and an organisation
may have zero templates without issue, unlike the org's project-statuses/
link-types (which must always retain at least one).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.user import User
from app.modules.decisions.models import DecisionTemplateDefinition
from app.modules.decisions.schemas import DecisionTemplateCreate, DecisionTemplateOut, DecisionTemplateUpdate
from app.services.audit import log_event
from app.services.rbac import get_effective_org_roles, require_org_module_enabled

router = APIRouter(prefix="/api/v1/orgs/{organization_id}/modules/decisions", tags=["decisions"])

_require_view = require_org_module_enabled("decisions")


def _require_template_manage(db: Session, current_user: User, organization_id: UUID) -> None:
    if OrgRole.ORG_ADMIN not in get_effective_org_roles(db, current_user.id, organization_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an organisation admin may manage Decision Templates.")


def _get_template_in_org(db: Session, organization_id: UUID, template_id: UUID) -> DecisionTemplateDefinition:
    template = db.get(DecisionTemplateDefinition, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision Template not found.")
    return template


@router.get("/templates", response_model=list[DecisionTemplateOut])
def list_decision_templates(
    organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return db.scalars(
        select(DecisionTemplateDefinition)
        .where(DecisionTemplateDefinition.organization_id == organization_id)
        .order_by(DecisionTemplateDefinition.sort_order)
    ).all()


@router.post("/templates", response_model=DecisionTemplateOut, status_code=status.HTTP_201_CREATED)
def create_decision_template(
    organization_id: UUID, payload: DecisionTemplateCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    _require_template_manage(db, current_user, organization_id)
    existing = db.scalar(
        select(DecisionTemplateDefinition.id).where(
            DecisionTemplateDefinition.organization_id == organization_id,
            DecisionTemplateDefinition.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A Decision Template with this name already exists.")
    count = len(
        db.scalars(
            select(DecisionTemplateDefinition.id).where(DecisionTemplateDefinition.organization_id == organization_id)
        ).all()
    )
    template = DecisionTemplateDefinition(
        organization_id=organization_id, name=payload.name, description=payload.description,
        context_prompt=payload.context_prompt, options_considered_prompt=payload.options_considered_prompt,
        chosen_option_prompt=payload.chosen_option_prompt, rationale_prompt=payload.rationale_prompt,
        consequences_prompt=payload.consequences_prompt, assumptions_prompt=payload.assumptions_prompt,
        constraints_prompt=payload.constraints_prompt, sort_order=count,
    )
    db.add(template)
    db.flush()
    log_event(db, entity_type="decision_template_definition", entity_id=template.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.commit()
    db.refresh(template)
    return template


@router.patch("/templates/{template_id}", response_model=DecisionTemplateOut)
def update_decision_template(
    organization_id: UUID, template_id: UUID, payload: DecisionTemplateUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _require_template_manage(db, current_user, organization_id)
    template = _get_template_in_org(db, organization_id, template_id)
    existing = db.scalar(
        select(DecisionTemplateDefinition.id).where(
            DecisionTemplateDefinition.organization_id == organization_id,
            DecisionTemplateDefinition.name == payload.name,
            DecisionTemplateDefinition.id != template_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A Decision Template with this name already exists.")
    template.name = payload.name
    template.description = payload.description
    template.context_prompt = payload.context_prompt
    template.options_considered_prompt = payload.options_considered_prompt
    template.chosen_option_prompt = payload.chosen_option_prompt
    template.rationale_prompt = payload.rationale_prompt
    template.consequences_prompt = payload.consequences_prompt
    template.assumptions_prompt = payload.assumptions_prompt
    template.constraints_prompt = payload.constraints_prompt
    log_event(db, entity_type="decision_template_definition", entity_id=template.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_decision_template(
    organization_id: UUID, template_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """A plain delete — no reassignment machinery needed (see this module's
    own docstring)."""
    _require_template_manage(db, current_user, organization_id)
    template = _get_template_in_org(db, organization_id, template_id)
    log_event(db, entity_type="decision_template_definition", entity_id=template.id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.delete(template)
    db.commit()
