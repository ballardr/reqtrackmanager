"""
Module: services.org_export

Exports an entire organisation — its settings, members/groups, report
templates, org-owned files (logo, login background), and every one of its
projects (full structure and history, reusing `services.project_export`) —
as a single self-describing zip bundle, and imports such a bundle back as a
brand-new organisation. For backup, offboarding, and cross-instance
migration (as opposed to `services.project_export`, which moves a single
project).

Security decisions (see `docs/decisions.md` and
`docs/soc2/policies/data-classification-and-confidentiality-policy.md`):

- `Organization.smtp_password`/`oidc_client_secret` are Restricted-classified
  secrets and are never exported, per that policy's rule 2 ("Restricted
  data is never returned in API responses or logs"). Non-secret SMTP/OIDC
  *configuration* (host, client id, issuer URL) is exported for reference,
  but the secrets themselves must be re-entered manually after import.
- The imported organisation's `sso_enabled`/`sso_only` are always forced to
  `False` regardless of the source bundle's values, precisely because the
  OIDC secret above is never carried over — importing `sso_only=True`
  verbatim with no working secret configured would leave the freshly
  imported org's login page completely unusable (no working SSO, and the
  native login form hidden) except via the narrow server-admin
  join-as-admin carve-out. The source values are still included in the
  export for the operator's reference when manually reconfiguring SSO.
- `members`/`org_groups` grant real access on import (org roles, org group
  membership) — unlike a project bundle's `ProjectGroupMember` rows (see
  `services.project_export`'s module docstring), because an org import
  always creates a brand-new organisation from scratch; there is no
  existing tenant boundary being crossed by populating its own initial
  membership, the same way `services.bootstrap` creates the very first
  server-admin org membership on deployment. An unmatched member email is
  invited (`services.invites.create_pending_invite`) rather than granted
  their original org role directly — invite acceptance only ever grants
  base membership, so a warning notes any such member's original role
  (e.g. `org_admin`) needs a manual re-grant once they sign up.
- `is_active`/`disabled_at`/`disabled_by` are never imported — a freshly
  imported organisation always starts active, regardless of whether the
  source was disabled at export time.
- `slug` is never imported (left null) — it's globally unique across the
  whole deployment, and blindly reusing the source's slug risks a
  collision on a second import of the same bundle, or with an unrelated
  organisation that happens to already use it.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole
from app.models.file import FileAsset
from app.models.organization import Organization, OrgGroup, OrgGroupMember, ReportTemplate, UserOrgRole
from app.models.project import Project
from app.models.user import User
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings, UserResolver, import_bundled_file
from app.services.files import read_file
from app.services.invites import create_pending_invite
from app.services.project_export import (
    PROJECT_BUNDLE_FORMAT_VERSION,
    apply_project_data,
    collect_project_data,
    new_project_from_bundle_data,
)

ORG_BUNDLE_KIND = "org-export"
ORG_BUNDLE_FORMAT_VERSION = 1


def build_org_bundle(db: Session, org: Organization, exported_by: User) -> bytes:
    """Builds an organisation export bundle: `manifest.json`, `org.json`
    (settings/members/groups/report templates), `projects/<ref>/project.json`
    per project (same shape `services.project_export` produces standalone),
    and one shared `files/` directory (org resources + every project's
    attachments).

    Args:
        db: An active database session.
        org: The organisation to export.
        exported_by: The user performing the export (recorded in the manifest).

    Returns:
        The zip file's bytes.
    """
    file_assets_by_id: dict[UUID, FileAsset] = {}

    projects = list(db.scalars(select(Project).where(Project.organization_id == org.id).order_by(Project.created_at)))
    project_ref_by_id = {p.id: f"P-{i + 1}" for i, p in enumerate(projects)}
    projects_json: dict[str, dict[str, Any]] = {}
    for p in projects:
        project_json, project_files = collect_project_data(db, p)
        projects_json[project_ref_by_id[p.id]] = project_json
        file_assets_by_id.update(project_files)

    report_templates = list(db.scalars(select(ReportTemplate).where(ReportTemplate.organization_id == org.id)))
    report_templates_json = [
        {
            "name": t.name, "accent_color_hex": t.accent_color_hex, "include_cover_page": t.include_cover_page,
            "include_logo": t.include_logo, "footer_text": t.footer_text, "intro": t.intro, "chapters": t.chapters,
            "appendices": t.appendices, "chapters_per_component": t.chapters_per_component,
        }
        for t in report_templates
    ]

    member_rows = list(
        db.execute(select(UserOrgRole.role, User).join(User, User.id == UserOrgRole.user_id).where(UserOrgRole.organization_id == org.id))
        .all()
    )
    members_json = [
        {"email": user.email, "display_name": user.display_name, "org_role": role.value} for role, user in member_rows
    ]

    org_groups = list(db.scalars(select(OrgGroup).where(OrgGroup.organization_id == org.id)))
    org_groups_json = []
    for g in org_groups:
        members = list(
            db.execute(
                select(User.email).join(OrgGroupMember, OrgGroupMember.user_id == User.id).where(OrgGroupMember.org_group_id == g.id)
            ).scalars()
        )
        org_groups_json.append({"name": g.name, "member_emails": members})

    logo_asset = db.get(FileAsset, org.logo_file_id) if org.logo_file_id else None
    if logo_asset:
        file_assets_by_id[logo_asset.id] = logo_asset
    background_asset = db.get(FileAsset, org.login_background_file_id) if org.login_background_file_id else None
    if background_asset:
        file_assets_by_id[background_asset.id] = background_asset

    org_json = {
        "name": org.name, "accent_color_hex": org.accent_color_hex, "header_title": org.header_title,
        "require_2fa": org.require_2fa, "allow_self_signup": org.allow_self_signup,
        "auto_accept_email_domain": org.auto_accept_email_domain, "external_user_policy": org.external_user_policy.value,
        "smtp_host": org.smtp_host, "smtp_port": org.smtp_port, "smtp_username": org.smtp_username,
        "smtp_use_tls": org.smtp_use_tls, "sso_group_mappings": org.sso_group_mappings,
        # Reference only — never re-applied on import (see module docstring).
        "source_sso_enabled": org.sso_enabled, "source_sso_only": org.sso_only,
        "oidc_issuer_url": org.oidc_issuer_url, "oidc_client_id": org.oidc_client_id,
        "oidc_required_group": org.oidc_required_group, "pat_max_lifetime_days": org.pat_max_lifetime_days,
        "default_report_intro": org.default_report_intro, "default_report_chapters": org.default_report_chapters,
        "default_report_appendices": org.default_report_appendices,
        "logo_file_ref": f"{logo_asset.id}_{logo_asset.filename}" if logo_asset else None,
        "logo_content_type": logo_asset.content_type if logo_asset else None,
        "login_background_file_ref": f"{background_asset.id}_{background_asset.filename}" if background_asset else None,
        "login_background_content_type": background_asset.content_type if background_asset else None,
        "default_template_project_ref": project_ref_by_id.get(org.default_template_project_id),
        "report_templates": report_templates_json, "members": members_json, "org_groups": org_groups_json,
    }

    manifest = {
        "kind": ORG_BUNDLE_KIND, "format_version": ORG_BUNDLE_FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(), "exported_by_email": exported_by.email, "org_name": org.name,
        "project_bundle_format_version": PROJECT_BUNDLE_FORMAT_VERSION,
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("org.json", json.dumps(org_json, indent=2))
        for ref, project_json in projects_json.items():
            zf.writestr(f"projects/{ref}/project.json", json.dumps(project_json, indent=2))
        for asset in file_assets_by_id.values():
            zf.writestr(f"files/{asset.id}_{asset.filename}", read_file(asset))
    return buffer.getvalue()


def import_org_bundle(db: Session, *, name: str | None, zip_bytes: bytes, current_user: User) -> tuple[Organization, list[str]]:
    """Creates a brand-new organisation from an exported org bundle,
    including every project it contains. Never merges into an existing
    organisation — see the module docstring for why (mirrors
    `import_project_bundle`'s same "always fresh" design).

    Args:
        db: An active database session.
        name: Overrides the bundle's own org name if given.
        zip_bytes: The uploaded bundle's raw bytes.
        current_user: The server admin performing the import.

    Returns:
        The new Organization and a list of human-readable import warnings.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        manifest = json.loads(zf.read("manifest.json"))
        data = json.loads(zf.read("org.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a valid export bundle.") from None
    if manifest.get("kind") != ORG_BUNDLE_KIND:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Expected an {ORG_BUNDLE_KIND!r} bundle, got {manifest.get('kind')!r}.")
    if manifest.get("format_version", 0) > ORG_BUNDLE_FORMAT_VERSION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This bundle was exported by a newer version of the application and can't be imported here.",
        )
    file_bytes_by_ref = {n.removeprefix("files/"): zf.read(n) for n in zf.namelist() if n.startswith("files/")}
    # Each project is its own `projects/<ref>/project.json` zip entry (see
    # `build_org_bundle`), not nested inside org.json — this discovers them
    # by path rather than assuming a `data["projects"]` key that doesn't exist.
    project_data_by_ref: dict[str, dict[str, Any]] = {}
    for entry in zf.namelist():
        if entry.startswith("projects/") and entry.endswith("/project.json"):
            ref = entry.removeprefix("projects/").removesuffix("/project.json")
            project_data_by_ref[ref] = json.loads(zf.read(entry))

    warnings = BundleImportWarnings()

    org = Organization(
        name=name if name else data.get("name", "Imported Organisation"),
        accent_color_hex=data.get("accent_color_hex"), header_title=data.get("header_title"),
        require_2fa=data.get("require_2fa", False), allow_self_signup=data.get("allow_self_signup", False),
        auto_accept_email_domain=data.get("auto_accept_email_domain"),
        external_user_policy=data.get("external_user_policy", "disabled"),
        smtp_host=data.get("smtp_host"), smtp_port=data.get("smtp_port"), smtp_username=data.get("smtp_username"),
        smtp_use_tls=data.get("smtp_use_tls", True), sso_group_mappings=data.get("sso_group_mappings") or [],
        # Deliberately not carried over from the bundle — see module docstring.
        sso_enabled=False, sso_only=False,
        oidc_issuer_url=data.get("oidc_issuer_url"), oidc_client_id=data.get("oidc_client_id"),
        oidc_required_group=data.get("oidc_required_group"), pat_max_lifetime_days=data.get("pat_max_lifetime_days"),
        default_report_intro=data.get("default_report_intro"), default_report_chapters=data.get("default_report_chapters"),
        default_report_appendices=data.get("default_report_appendices"),
    )
    db.add(org)
    db.flush()
    if data.get("source_sso_only"):
        warnings.add(
            "The source organisation had sso_only enabled; this was not carried over (no working OIDC secret is "
            "included in the export) — reconfigure SSO manually if needed."
        )

    if data.get("logo_file_ref") and data["logo_file_ref"] in file_bytes_by_ref:
        asset = import_bundled_file(
            db, organization_id=org.id, uploaded_by=current_user.id,
            filename=data["logo_file_ref"].split("_", 1)[1], content_type=data.get("logo_content_type") or "application/octet-stream",
            data=file_bytes_by_ref[data["logo_file_ref"]],
        )
        org.logo_file_id = asset.id
    if data.get("login_background_file_ref") and data["login_background_file_ref"] in file_bytes_by_ref:
        asset = import_bundled_file(
            db, organization_id=org.id, uploaded_by=current_user.id,
            filename=data["login_background_file_ref"].split("_", 1)[1],
            content_type=data.get("login_background_content_type") or "application/octet-stream",
            data=file_bytes_by_ref[data["login_background_file_ref"]],
        )
        org.login_background_file_id = asset.id

    for t in data.get("report_templates", []):
        db.add(ReportTemplate(
            organization_id=org.id, name=t["name"], accent_color_hex=t.get("accent_color_hex", "#475569"),
            include_cover_page=t.get("include_cover_page", True), include_logo=t.get("include_logo", True),
            footer_text=t.get("footer_text"), intro=t.get("intro", ""), chapters=t.get("chapters") or [],
            appendices=t.get("appendices") or [], chapters_per_component=t.get("chapters_per_component", True),
            created_by=current_user.id,
        ))

    email_cache: dict[str, User | None] = {}

    def find_user(email: str) -> User | None:
        normalized = email.strip().lower()
        if normalized not in email_cache:
            email_cache[normalized] = db.scalar(select(User).where(User.email == normalized))
        return email_cache[normalized]

    # Whoever ends up as the org's first real org_admin (matched by email to
    # an existing account) — not `current_user`, the server admin performing
    # this bulk import — is who project-level fallbacks below should
    # attribute to. Project group *membership* is never recreated on import
    # (see services.project_export's module docstring), so every project's
    # "guarantee at least one manager" safety net fires on every import;
    # attributing that (and every other unresolved-reference fallback) to
    # the platform operator running the import would leave them as a
    # standing manager of every project in an org they otherwise have no
    # relationship to. Falls back to `current_user` only if no org_admin
    # member could be matched at all (e.g. every member needed an invite).
    acting_user = current_user
    for m in data.get("members", []):
        existing = find_user(m["email"])
        if existing is not None:
            db.add(UserOrgRole(user_id=existing.id, organization_id=org.id, role=OrgRole(m["org_role"])))
            if acting_user is current_user and m["org_role"] == OrgRole.ORG_ADMIN.value:
                acting_user = existing
        else:
            create_pending_invite(db, email=m["email"].strip().lower(), organization=org, project=None, project_role=None, invited_by=current_user.id)
            warnings.add(
                f"Member '{m['email']}' has no existing account — invited instead; their original role "
                f"({m['org_role']}) must be granted manually once they sign up (invites only grant base membership)."
            )

    users = UserResolver(db, acting_user, warnings)

    for g in data.get("org_groups", []):
        group = OrgGroup(organization_id=org.id, name=g["name"])
        db.add(group)
        db.flush()
        for email in g.get("member_emails", []):
            existing = find_user(email)
            if existing is not None:
                db.add(OrgGroupMember(org_group_id=group.id, user_id=existing.id))

    project_id_by_ref: dict[str, UUID] = {}
    for ref, project_data in project_data_by_ref.items():
        project = new_project_from_bundle_data(org.id, project_data.get("source_name", "Imported Project"), None, project_data)
        db.add(project)
        db.flush()
        project_id_by_ref[ref] = project.id
        apply_project_data(db, project, project_data, file_bytes_by_ref, acting_user, users, warnings)

    template_ref = data.get("default_template_project_ref")
    if template_ref and template_ref in project_id_by_ref:
        org.default_template_project_id = project_id_by_ref[template_ref]

    log_event(
        db, entity_type="organization", entity_id=org.id, action="imported_from_bundle", actor_id=current_user.id,
        organization_id=org.id, detail={"warning_count": len(warnings.messages), "project_count": len(project_id_by_ref)},
    )
    db.commit()
    db.refresh(org)
    return org, warnings.messages
