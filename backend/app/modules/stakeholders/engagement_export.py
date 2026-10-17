"""
Module: modules.stakeholders.engagement_export

The Engagement part of this module's project bundle export/import;
`module.py` composes it with the Persona, Stakeholder, Need and relationship
halves, and runs it last because an engagement links to all of them. An
Engagement is project-scoped, so there is no org-level half.

Design decisions:
- Same carry-over rules as the other halves: current content only, no comments;
  cross-references use portable keys, never database ids: a Stakeholder or
  Persona is its name and scope, an audience group is its name path, a user is an
  email, and a Pain Point / Need / Open Question is the label its owning module's
  summary provider gives it. A reference the target lacks, or that is ambiguous,
  is skipped with a warning rather than guessed at.
- The research extras (prompts, anonymous participants, findings with their
  outcomes) travel whenever rows exist, whatever the sub-component state, so a
  bundle stays a full backup.
- Notes and quotes make the bundle Confidential, like the Stakeholder half.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import engagements as eng
from app.modules.stakeholders import groups as grp
from app.modules.stakeholders import relationships as rel
from app.modules.stakeholders.engagements import (
    ENGAGEMENT_ARTEFACT_TYPE,
    FINDING_ARTEFACT_TYPE,
    get_outcome_kind,
)
from app.modules.stakeholders.enums import EngagementChannel, PersonaScope, StakeholderScope
from app.modules.stakeholders.models import (
    Engagement,
    EngagementAnonymousParticipant,
    EngagementFile,
    EngagementPrompt,
    Persona,
    Stakeholder,
)
from app.modules.stakeholders.service import (
    get_current_persona_version,
    get_current_stakeholder_version,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver, import_bundled_file
from app.services.principals import principal_from_bundle, principal_to_bundle

_KEY = "project_engagements"
_TEXT_FIELDS = ("title", "purpose", "summary", "notes")


def _j(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _outcomes_json(db: Session, project: Project, holder_type: str, holder_id: UUID) -> list[dict[str, str]]:
    out = []
    for link, kind in eng.list_outcome_links(db, holder_type, holder_id, project.organization_id):
        summary = rel.resolve_target(db, project, link.target_type, link.target_id)
        if summary is not None:
            out.append({"kind": kind.key, "target_type": link.target_type, "target_ref": summary.label})
    return out


def _group_path(universe: dict[UUID, Any], group_id: UUID) -> list[dict[str, str]]:
    group = universe[group_id]
    return [{"name": n.name, "scope": n.scope.value} for n in [*grp.ancestor_chain(universe, group_id)][::-1] + [group]]


def _engagement_json(
    db: Session, engagement: Engagement, project: Project, universe: dict[UUID, Any], emails: dict[UUID, str]
) -> dict[str, Any]:
    organization_id = project.organization_id
    participants = []
    for link in eng.list_participant_links(db, engagement, organization_id):
        s = db.get(Stakeholder, link.target_id)
        if s is not None:
            participants.append({"name": get_current_stakeholder_version(db, s.id).name, "scope": s.scope.value})
    personas = []
    for link in eng.list_persona_links(db, engagement, organization_id):
        p = db.get(Persona, link.target_id)
        if p is not None:
            personas.append({"name": get_current_persona_version(db, p.id).name, "scope": p.scope.value})
    audiences = [
        _group_path(universe, link.target_id) for link in eng.list_audience_links(db, engagement, organization_id)
        if link.target_id in universe
    ]
    findings = [
        {
            "unique_code": f.unique_code, "title": f.title, "description": f.description, "created_by_email": emails.get(f.creator_id),
            "created_at": _j(f.created_at), "outcomes": _outcomes_json(db, project, FINDING_ARTEFACT_TYPE, f.id),
        }
        for f in eng.list_findings(db, engagement.id)
    ]
    anonymous = []
    for a in eng.list_anonymous_participants(db, engagement.id):
        persona = db.get(Persona, a.persona_id) if a.persona_id else None
        anonymous.append({
            "label": a.label,
            "persona_name": get_current_persona_version(db, persona.id).name if persona else None,
            "persona_scope": persona.scope.value if persona else None,
        })
    return {
        "unique_code": engagement.unique_code,
        **{f: getattr(engagement, f) for f in _TEXT_FIELDS}, "channel": engagement.channel.value,
        "engagement_date": _j(engagement.engagement_date), "retain_until": _j(engagement.retain_until),
        "consent_recorded": engagement.consent_recorded,
        "facilitators": [
            entry for ref in eng.list_facilitators(db, [engagement.id]).get(engagement.id, [])
            if (entry := principal_to_bundle(db, ref.type.value, ref.id)) is not None
        ],
        "created_by_email": emails.get(engagement.creator_id), "created_at": _j(engagement.created_at),
        "participants": participants, "personas": personas, "audiences": audiences,
        "outcomes": _outcomes_json(db, project, ENGAGEMENT_ARTEFACT_TYPE, engagement.id),
        "prompts": [
            {"prompt": p.prompt, "response_notes": p.response_notes} for p in eng.list_prompts(db, engagement.id)
        ],
        "anonymous_participants": anonymous, "findings": findings,
    }


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """The project's engagements with their participants, outcomes, extras and attachments."""
    engagements = eng.list_project_engagements(db, project.id)
    findings = [f for e in engagements for f in eng.list_findings(db, e.id)]
    user_ids = {e.creator_id for e in engagements} | {f.creator_id for f in findings}
    emails = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    universe = grp.load_groups(db, project.organization_id, project.id)
    assets: dict[UUID, FileAsset] = {}
    out = []
    for engagement in engagements:
        entry = _engagement_json(db, engagement, project, universe, emails)
        attachments = []
        for asset, linked_by in db.execute(
            select(FileAsset, User).join(EngagementFile, EngagementFile.file_id == FileAsset.id)
            .join(User, User.id == EngagementFile.linked_by).where(EngagementFile.engagement_id == engagement.id)
        ).all():
            assets[asset.id] = asset
            attachments.append({
                "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
                "content_type": asset.content_type, "linked_by_email": linked_by.email,
            })
        entry["attachments"] = attachments
        out.append(entry)
    return {_KEY: out}, assets


def _outcome_lookup(db: Session, project: Project) -> Any:
    """A callable resolving an exported `(target_type, label)` to one summary, or `None` when absent or ambiguous."""
    cache: dict[str, dict[str, list[Any]]] = {}

    def resolve(target_type: str, label: str) -> Any:
        if target_type not in cache:
            by_label: dict[str, list[Any]] = {}
            if rel.target_type_available(target_type):
                for s in rel.list_targets(db, project, target_type):
                    by_label.setdefault(s.label, []).append(s)
            cache[target_type] = by_label
        matches = cache[target_type].get(label, [])
        return matches[0] if len(matches) == 1 else None

    return resolve


def _import_outcomes(
    db: Session, engagement: Engagement, holder_type: str, holder_id: UUID, entries: list[dict[str, str]],
    resolve: Any, current_user: User, organization_id: UUID, warnings: BundleImportWarnings, context: str,
) -> None:
    for entry in entries:
        kind = get_outcome_kind(entry["kind"])
        target = resolve(entry["target_type"], entry["target_ref"])
        if kind is None or target is None:
            warnings.add(f"{context}: {entry['target_type']} {entry['target_ref']!r} not found or ambiguous — skipped.")
            continue
        try:
            eng.add_outcome(
                db, engagement, holder_type, holder_id, kind, entry["target_type"], target.id, current_user,
                organization_id=organization_id,
            )
        except ValueError as exc:
            warnings.add(f"{context}: {exc}")


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """Recreates the project's engagements, their links, extras and attachments. Runs after every other half."""
    organization_id = project.organization_id
    stakeholders = {
        (get_current_stakeholder_version(db, s.id).name, s.scope.value): s.id
        for s in db.scalars(select(Stakeholder).where(
            ((Stakeholder.organization_id == organization_id) & (Stakeholder.scope == StakeholderScope.ORGANIZATION))
            | ((Stakeholder.project_id == project.id) & (Stakeholder.scope == StakeholderScope.PROJECT))
        ))
    }
    personas = {
        (get_current_persona_version(db, p.id).name, p.scope.value): p.id
        for p in db.scalars(select(Persona).where(
            ((Persona.organization_id == organization_id) & (Persona.scope == PersonaScope.ORGANIZATION))
            | ((Persona.project_id == project.id) & (Persona.scope == PersonaScope.PROJECT))
        ))
    }
    universe = grp.load_groups(db, organization_id, project.id)
    groups_by_path = {
        tuple((n["scope"], n["name"].lower()) for n in _group_path(universe, gid)): gid for gid in universe
    }
    resolve = _outcome_lookup(db, project)
    # Numbered in their original order, so a new project's ENG-nnn follow the exported ones.
    for e in sorted(data.get(_KEY, []), key=lambda entry: entry.get("unique_code", "")):
        context = f"Engagement {e['title']!r}"
        creator_id = users.resolve(e.get("created_by_email"), required=True, context=f"{context} creator")
        engagement = eng.create_engagement(
            db, project=project, creator=db.get(User, creator_id),
            channel=EngagementChannel(e["channel"]), engagement_date=_d(e["engagement_date"]),
            consent_recorded=bool(e.get("consent_recorded")), retain_until=_d(e.get("retain_until")),
            **{f: e.get(f, "") for f in _TEXT_FIELDS},
        )
        # A bundle written before an engagement could have several facilitators carries one `facilitator`.
        entries = e.get("facilitators") if "facilitators" in e else ([e["facilitator"]] if e.get("facilitator") else [])
        facilitators = []
        for entry in entries:
            ref, warning = principal_from_bundle(
                db, entry, organization_id=organization_id, project_id=project.id,
                fallback_user_id=users.importing_user_id, required=False,
            )
            if warning:
                warnings.add(f"{context} facilitator: {warning}")
            if ref is not None:
                facilitators.append(ref)
        eng.set_facilitators(db, engagement, facilitators)
        for participant in e.get("participants", []):
            stakeholder_id = stakeholders.get((participant["name"], participant["scope"]))
            if stakeholder_id is None:
                warnings.add(f"{context}: participant {participant['name']!r} not found — skipped.")
                continue
            try:
                eng.add_participant(db, engagement, stakeholder_id, current_user, organization_id=organization_id)
            except ValueError as exc:
                warnings.add(f"{context}: {exc}")
        for persona in e.get("personas", []):
            persona_id = personas.get((persona["name"], persona["scope"]))
            if persona_id is None:
                warnings.add(f"{context}: persona {persona['name']!r} not found — skipped.")
                continue
            try:
                eng.add_covered_persona(db, engagement, persona_id, current_user, organization_id=organization_id)
            except ValueError as exc:
                warnings.add(f"{context}: {exc}")
        for path in e.get("audiences", []):
            group_id = groups_by_path.get(tuple((n["scope"], n["name"].lower()) for n in path))
            if group_id is None:
                warnings.add(f"{context}: audience group {' / '.join(n['name'] for n in path)!r} not found — skipped.")
                continue
            try:
                eng.add_audience_group(db, engagement, group_id, current_user, organization_id=organization_id)
            except ValueError as exc:
                warnings.add(f"{context}: {exc}")
        _import_outcomes(
            db, engagement, ENGAGEMENT_ARTEFACT_TYPE, engagement.id, e.get("outcomes", []), resolve, current_user,
            organization_id, warnings, context,
        )
        for order, prompt in enumerate(e.get("prompts", [])):
            db.add(EngagementPrompt(
                engagement_id=engagement.id, sort_order=order, prompt=prompt["prompt"],
                response_notes=prompt.get("response_notes", ""),
            ))
        for anon in e.get("anonymous_participants", []):
            persona_id = personas.get((anon["persona_name"], anon["persona_scope"])) if anon.get("persona_name") else None
            if anon.get("persona_name") and persona_id is None:
                warnings.add(f"{context}: persona {anon['persona_name']!r} for {anon['label']!r} not found — left blank.")
            db.add(EngagementAnonymousParticipant(engagement_id=engagement.id, label=anon["label"], persona_id=persona_id))
        db.flush()
        for f in e.get("findings", []):
            finding_creator = users.resolve(f.get("created_by_email"), required=True, context=f"{context} finding creator")
            # A new project numbers its findings afresh, so the bundled code is informational only.
            finding = eng.create_finding(
                db, project, engagement, creator_id=finding_creator, actor=current_user, title=f["title"],
                description=f.get("description", ""),
            )
            _import_outcomes(
                db, engagement, FINDING_ARTEFACT_TYPE, finding.id, f.get("outcomes", []), resolve, current_user,
                organization_id, warnings, f"{context} finding {f['title']!r}",
            )
        for att in e.get("attachments", []):
            att_bytes = file_bytes_by_ref.get(att["file_ref"])
            if att_bytes is None:
                continue
            uploader_id = (
                users.resolve(att.get("linked_by_email"), required=False, context="Engagement attachment uploader")
                or current_user.id
            )
            asset = import_bundled_file(
                db, organization_id=organization_id, uploaded_by=uploader_id, filename=att["filename"],
                content_type=att.get("content_type") or "application/octet-stream", data=att_bytes,
            )
            db.add(EngagementFile(
                engagement_id=engagement.id, file_id=asset.id, linked_by=uploader_id, created_at=datetime.now(UTC)
            ))
    db.flush()
