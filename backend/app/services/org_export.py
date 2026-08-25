"""
Module: services.org_export

Exports an entire organisation — its settings, members/groups, report
templates, org-owned files (logo, login background), and every one of its
projects (full structure and history, reusing `services.project_export`) —
as a single self-describing zip bundle, and imports such a bundle back in
one of two ways:

- `import_org_bundle`: creates a brand-new organisation. For backup,
  offboarding, and cross-instance migration (as opposed to
  `services.project_export`, which moves a single project).
- `merge_org_bundle`: imports the bundle's users, groups, projects, and
  report templates into an *existing* organisation the caller already
  administers — never the organisation's own profile (branding, SMTP,
  SSO/OIDC, logo, default template). See `merge_org_bundle`'s own
  docstring for why this is a deliberately narrower, separate path rather
  than a flag on `import_org_bundle`.

Both import paths share the bundle-parsing and per-entity-kind import logic
below (`_parse_org_bundle`, `_import_members`, `_import_org_groups`,
`_import_report_templates`, `_import_projects`) rather than duplicating it —
`import_org_bundle` always calls them with "no conflicts possible" arguments
(a freshly created organisation has nothing to collide with), while
`merge_org_bundle` passes real conflict resolutions into the same helpers.

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
  `merge_org_bundle` never touches these fields at all (see its own
  docstring) — this bullet applies to `import_org_bundle` only.
- `members`/`org_groups` grant real access on import (org roles, org group
  membership) in both `import_org_bundle` and `merge_org_bundle` — unlike a
  project bundle's `ProjectGroupMember` rows (see `services.project_export`'s
  module docstring). For `import_org_bundle` this is safe because an org
  import always creates a brand-new organisation from scratch; there is no
  existing tenant boundary being crossed by populating its own initial
  membership, the same way `services.bootstrap` creates the very first
  server-admin org membership on deployment. For `merge_org_bundle` an
  existing tenant boundary *is* being crossed, which is exactly why that
  path is gated behind the target organisation's own `org_admin` (never a
  server-admin bypass) and is purely additive — see its docstring. An
  unmatched member email is invited (`services.invites.
  create_pending_invite`) rather than granted their original org role
  directly — invite acceptance only ever grants base membership, so a
  warning notes any such member's original role (e.g. `org_admin`) needs a
  manual re-grant once they sign up. An existing account with `User.
  is_banned` set is matched but granted neither an org role nor org group
  membership (skipped with a warning instead) — a bundle is
  caller-controlled data, not a trusted grant request, and must not become
  a way around the same ban `assign_org_role`/`assign_project_role_by_email`
  already enforce; this applies to `import_org_bundle` too; a banned
  account should not quietly regain access via a brand-new organisation
  either.
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
from collections.abc import Callable
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
from app.services.bundle_common import (
    BundleImportWarnings,
    UserResolver,
    enforce_upload_size_limit,
    enforce_zip_uncompressed_size_limit,
    import_bundled_file,
)
from app.services.definitions import seed_link_types, seed_project_statuses
from app.services.files import read_file
from app.services.invites import create_pending_invite
from app.services.project_export import (
    PROJECT_BUNDLE_FORMAT_VERSION,
    apply_project_data,
    collect_project_data,
    new_project_from_bundle_data,
)
from app.services.rbac import would_create_org_group_cycle

ORG_BUNDLE_KIND = "org-export"
ORG_BUNDLE_FORMAT_VERSION = 1

# Valid `resolutions` values `merge_org_bundle` accepts for each conflict
# kind `detect_merge_conflicts` can report — see both functions' docstrings.
_PROJECT_RESOLUTIONS = {"skip", "import_as_copy"}
_REPORT_TEMPLATE_RESOLUTIONS = {"keep_existing", "use_import"}


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
                select(User.email).join(OrgGroupMember, OrgGroupMember.user_id == User.id).where(
                    OrgGroupMember.org_group_id == g.id, OrgGroupMember.user_id.is_not(None)
                )
            ).scalars()
        )
        # Nested org groups (`OrgGroupMember.member_org_group_id`) — the
        # groups directly nested inside this one, by name (re-linked on
        # import in a second pass, since a group can reference another one
        # appearing later in this same list — see `_import_org_groups`).
        nested_group_names = list(
            db.execute(
                select(OrgGroup.name)
                .join(OrgGroupMember, OrgGroupMember.member_org_group_id == OrgGroup.id)
                .where(OrgGroupMember.org_group_id == g.id)
            ).scalars()
        )
        org_groups_json.append({
            "name": g.name, "member_emails": members, "nested_group_names": nested_group_names,
            "idp_synced_group_name": g.idp_synced_group_name,
            "granted_org_role": g.granted_org_role.value if g.granted_org_role else None,
        })

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
        "smtp_use_tls": org.smtp_use_tls,
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


def _parse_org_bundle(zip_bytes: bytes) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes], dict[str, dict[str, Any]]]:
    """Validates and parses an uploaded org bundle's raw bytes, shared by
    `import_org_bundle` and `merge_org_bundle`.

    Returns:
        `(manifest, org_data, file_bytes_by_ref, project_data_by_ref)`.

    Raises:
        HTTPException: 400/413 for a malformed, wrong-kind, too-large, or
            too-new bundle.
    """
    enforce_upload_size_limit(zip_bytes, what="Bundle upload")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        enforce_zip_uncompressed_size_limit(zf)
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
    # Each project is its own `projects/<ref>/project.json` zip entry (see
    # `build_org_bundle`), not nested inside org.json — this discovers them
    # by path rather than assuming a `data["projects"]` key that doesn't exist.
    file_bytes_by_ref = {n.removeprefix("files/"): zf.read(n) for n in zf.namelist() if n.startswith("files/")}
    project_data_by_ref: dict[str, dict[str, Any]] = {}
    for entry in zf.namelist():
        if entry.startswith("projects/") and entry.endswith("/project.json"):
            ref = entry.removeprefix("projects/").removesuffix("/project.json")
            project_data_by_ref[ref] = json.loads(zf.read(entry))
    return manifest, data, file_bytes_by_ref, project_data_by_ref


def _import_members(
    db: Session, org: Organization, data: dict[str, Any], current_user: User, warnings: BundleImportWarnings,
    *, reassign_acting_user: bool,
) -> tuple[User, Callable[[str], User | None]]:
    """Grants org membership for every bundle member matched by email
    (`import_org_bundle`) or adds it alongside whatever roles the target
    org's existing members already hold (`merge_org_bundle`) — the
    already-a-member check below is a no-op for a freshly created org (it
    can never already have the row) and the additive guard `merge_org_bundle`
    needs to avoid a duplicate-role unique-constraint violation.

    Args:
        reassign_acting_user: Whether a bundle member matched to an
            existing `org_admin` account should become `acting_user`
            instead of `current_user` — see the inline comment above
            `acting_user`'s assignment. `True` for `import_org_bundle`;
            `False` for `merge_org_bundle`, where `current_user` (the
            target organisation's own admin, performing the merge) is
            already the legitimate acting user for a project fallback —
            reassigning to some *other* org's admin who merely happens to
            also be a member of the bundle being imported would be wrong
            here, unlike in a brand-new org with no established admin yet.

    Returns:
        `(acting_user, find_user)` — see the inline comment above
        `acting_user`'s assignment for what it's for; `find_user` is reused
        by `_import_org_groups` for the same email-to-account resolution.
    """
    email_cache: dict[str, User | None] = {}

    def find_user(email: str) -> User | None:
        normalized = email.strip().lower()
        if normalized not in email_cache:
            email_cache[normalized] = db.scalar(select(User).where(User.email == normalized))
        return email_cache[normalized]

    # Whoever ends up as the org's first real org_admin (matched by email to
    # an existing account) — not `current_user`, the admin performing this
    # bulk import — is who project-level fallbacks below should attribute
    # to. Project group *membership* is never recreated on import (see
    # services.project_export's module docstring), so every project's
    # "guarantee at least one manager" safety net fires on every import;
    # attributing that (and every other unresolved-reference fallback) to
    # the operator running the import would leave them as a standing
    # manager of every project in an org they otherwise have no
    # relationship to. Falls back to `current_user` only if no org_admin
    # member could be matched at all (e.g. every member needed an invite) —
    # or, for a merge, always (see `reassign_acting_user` above).
    acting_user = current_user
    for m in data.get("members", []):
        existing = find_user(m["email"])
        if existing is not None:
            if existing.is_banned:
                # Same invariant `assign_org_role`/`assign_project_role_by_email`
                # enforce (see `User.is_banned`'s docstring: a ban "survives"
                # a different org's admin trying to let the account back in).
                # A bundle is attacker-controllable data, not a trusted grant
                # request, so it must not become another unguarded way to
                # hand a banned account a role.
                warnings.add(
                    f"Member '{m['email']}' has been banned by a server admin and was not granted the "
                    f"'{m['org_role']}' role."
                )
                continue
            already_has_role = db.scalar(
                select(UserOrgRole).where(
                    UserOrgRole.user_id == existing.id,
                    UserOrgRole.organization_id == org.id,
                    UserOrgRole.role == OrgRole(m["org_role"]),
                )
            )
            if already_has_role is None:
                db.add(UserOrgRole(user_id=existing.id, organization_id=org.id, role=OrgRole(m["org_role"])))
            if reassign_acting_user and acting_user is current_user and m["org_role"] == OrgRole.ORG_ADMIN.value:
                acting_user = existing
        else:
            create_pending_invite(db, email=m["email"].strip().lower(), organization=org, project=None, project_role=None, invited_by=current_user.id)
            warnings.add(
                f"Member '{m['email']}' has no existing account — invited instead; their original role "
                f"({m['org_role']}) must be granted manually once they sign up (invites only grant base membership)."
            )
    return acting_user, find_user


def _import_org_groups(
    db: Session, org: Organization, data: dict[str, Any], find_user: Callable[[str], User | None],
    warnings: BundleImportWarnings, *, merge_by_name: bool,
) -> None:
    """Creates org groups from a bundle. `merge_by_name=False`
    (`import_org_bundle`): always creates a fresh `OrgGroup` — a brand-new
    organisation can't already have one with the same name. `merge_by_name
    =True` (`merge_org_bundle`): reuses an existing group with the same
    name if the target org already has one, adding the bundle's members
    into it (a union — never removes an existing member), rather than
    creating a duplicate; purely additive either way, so unlike projects
    and report templates this never needs a conflict resolution.

    A banned member is skipped, same as `_import_members` — org group
    membership isn't just a label here: `rbac.get_effective_project_roles`
    grants a project role to any member of an org group nested into that
    project's `ProjectGroup`, with no separate `UserOrgRole` check at all,
    so this is an independent way a bundle could otherwise hand a banned
    account real access.

    Nested-group edges (`nested_group_names`) are wired up in a second pass,
    after every group in the bundle has been created/resolved, since a
    group can reference another group appearing later in the same bundle.
    An edge that would create a cycle (a malformed or adversarial bundle —
    real exports can never produce one, since `add_org_group_member`
    already rejects cycles at write time) is skipped with a warning, the
    same as a banned member above."""
    existing_by_name: dict[str, OrgGroup] = {}
    existing_idp_synced_names: set[str] = set()
    if merge_by_name:
        existing_groups = db.scalars(select(OrgGroup).where(OrgGroup.organization_id == org.id)).all()
        existing_by_name = {g.name.strip().lower(): g for g in existing_groups}
        existing_idp_synced_names = {g.idp_synced_group_name for g in existing_groups if g.idp_synced_group_name}
    groups_by_bundle_name: dict[str, OrgGroup] = {}
    for g in data.get("org_groups", []):
        group = existing_by_name.get(g["name"].strip().lower()) if merge_by_name else None
        existing_member_ids: set[UUID] = set()
        if group is None:
            # `idp_synced_group_name` is unique per org (partial index) —
            # on a merge into an existing org, a bundle group claiming a
            # name another group there already owns is skipped with a
            # warning (same pattern this function already uses for a
            # banned member or a cycle-forming nested edge) rather than
            # letting the INSERT below fail on the constraint. On a
            # fresh-org import (`merge_by_name=False`) this can never
            # conflict, since the target org has no groups yet.
            idp_synced_group_name = g.get("idp_synced_group_name")
            if idp_synced_group_name and idp_synced_group_name in existing_idp_synced_names:
                warnings.add(
                    f"Group '{g['name']}' was imported without its IdP-sync target — "
                    f"'{idp_synced_group_name}' is already used by another group in this organisation."
                )
                idp_synced_group_name = None
            granted_org_role = g.get("granted_org_role")
            group = OrgGroup(
                organization_id=org.id, name=g["name"], idp_synced_group_name=idp_synced_group_name,
                # Meaningless (and, on merge, unenforced) without a synced
                # name — dropped alongside it rather than left dangling.
                granted_org_role=OrgRole(granted_org_role) if granted_org_role and idp_synced_group_name else None,
            )
            db.add(group)
            db.flush()
            if idp_synced_group_name:
                existing_idp_synced_names.add(idp_synced_group_name)
        elif merge_by_name:
            existing_member_ids = set(
                db.scalars(
                    select(OrgGroupMember.user_id).where(
                        OrgGroupMember.org_group_id == group.id, OrgGroupMember.user_id.is_not(None)
                    )
                ).all()
            )
        for email in g.get("member_emails", []):
            existing = find_user(email)
            if existing is not None and existing.is_banned:
                warnings.add(f"Member '{email}' has been banned by a server admin and was not added to group '{g['name']}'.")
            elif existing is not None and existing.id not in existing_member_ids:
                db.add(OrgGroupMember(org_group_id=group.id, user_id=existing.id))
        groups_by_bundle_name[g["name"].strip().lower()] = group
    db.flush()

    for g in data.get("org_groups", []):
        group = groups_by_bundle_name[g["name"].strip().lower()]
        existing_nested_ids: set[UUID] = set(
            db.scalars(
                select(OrgGroupMember.member_org_group_id).where(
                    OrgGroupMember.org_group_id == group.id, OrgGroupMember.member_org_group_id.is_not(None)
                )
            ).all()
        )
        for nested_name in g.get("nested_group_names", []):
            child = groups_by_bundle_name.get(nested_name.strip().lower())
            if child is None or child.id in existing_nested_ids:
                continue
            if would_create_org_group_cycle(db, group.id, child.id):
                warnings.add(f"Nesting '{child.name}' inside '{group.name}' would create a cycle — skipped.")
                continue
            db.add(OrgGroupMember(org_group_id=group.id, member_org_group_id=child.id))


def _import_report_templates(
    db: Session, org: Organization, data: dict[str, Any], current_user: User, *, resolutions: dict[str, str] | None,
) -> None:
    """Creates report templates from a bundle. `resolutions=None`
    (`import_org_bundle`): always creates fresh — a brand-new organisation
    can't already have a same-named template. Otherwise (`merge_org_bundle`):
    a bundle template whose name matches one `target_org` already has (`
    ReportTemplate` is unique per `organization_id`+`name`) is skipped
    (`"keep_existing"`) or overwrites the existing row's fields in place
    (`"use_import"`) per `resolutions[f"report_template:{name}"]` — an
    in-place overwrite is safe here (unlike a project, never done silently
    for one — see `_import_projects`) because a report template is pure
    presentation config with no history or sub-content to lose."""
    existing_by_name: dict[str, ReportTemplate] = {}
    if resolutions is not None:
        existing_by_name = {
            t.name.strip().lower(): t for t in db.scalars(select(ReportTemplate).where(ReportTemplate.organization_id == org.id))
        }
    for t in data.get("report_templates", []):
        existing = existing_by_name.get(t["name"].strip().lower()) if resolutions is not None else None
        if existing is not None:
            if resolutions[f"report_template:{t['name']}"] == "keep_existing":
                continue
            existing.accent_color_hex = t.get("accent_color_hex", "#475569")
            existing.include_cover_page = t.get("include_cover_page", True)
            existing.include_logo = t.get("include_logo", True)
            existing.footer_text = t.get("footer_text")
            existing.intro = t.get("intro", "")
            existing.chapters = t.get("chapters") or []
            existing.appendices = t.get("appendices") or []
            existing.chapters_per_component = t.get("chapters_per_component", True)
            continue
        db.add(ReportTemplate(
            organization_id=org.id, name=t["name"], accent_color_hex=t.get("accent_color_hex", "#475569"),
            include_cover_page=t.get("include_cover_page", True), include_logo=t.get("include_logo", True),
            footer_text=t.get("footer_text"), intro=t.get("intro", ""), chapters=t.get("chapters") or [],
            appendices=t.get("appendices") or [], chapters_per_component=t.get("chapters_per_component", True),
            created_by=current_user.id,
        ))


def _import_projects(
    db: Session, org: Organization, project_data_by_ref: dict[str, dict[str, Any]], file_bytes_by_ref: dict[str, bytes],
    acting_user: User, users: UserResolver, warnings: BundleImportWarnings, *, resolutions: dict[str, str] | None,
) -> dict[str, UUID]:
    """Creates projects from a bundle's `projects/<ref>/project.json`
    entries. `resolutions=None` (`import_org_bundle`): every project is new
    — a brand-new organisation can't already have a same-named one.
    Otherwise (`merge_org_bundle`): a bundle project whose `source_name`
    matches an existing project in `org` is skipped (`"skip"`) or imported
    as a distinct copy renamed `"<name> (imported)"` (`"import_as_copy"`)
    per `resolutions[f"project:{ref}"]` — never overwritten in place, unlike
    a report template (`_import_report_templates`): a project carries real
    requirement/change-request history that an in-place replace would
    destroy, which is a materially bigger and more destructive operation
    than this merge feature covers.

    Returns:
        Bundle project ref -> the new `Project.id`, for callers that also
        need to resolve `default_template_project_ref` (only relevant to
        `import_org_bundle` — a merge never touches the target org's
        default template).
    """
    existing_by_name: dict[str, Project] = {}
    if resolutions is not None:
        existing_by_name = {
            p.name.strip().lower(): p for p in db.scalars(select(Project).where(Project.organization_id == org.id))
        }
    project_id_by_ref: dict[str, UUID] = {}
    for ref, project_data in project_data_by_ref.items():
        source_name = project_data.get("source_name", "Imported Project")
        name = source_name
        if resolutions is not None and source_name.strip().lower() in existing_by_name:
            if resolutions[f"project:{ref}"] == "skip":
                continue
            name = f"{source_name} (imported)"
        project = new_project_from_bundle_data(db, org.id, name, None, project_data)
        db.add(project)
        db.flush()
        project_id_by_ref[ref] = project.id
        apply_project_data(db, project, project_data, file_bytes_by_ref, acting_user, users, warnings)
    return project_id_by_ref


def import_org_bundle(db: Session, *, name: str | None, zip_bytes: bytes, current_user: User) -> tuple[Organization, list[str]]:
    """Creates a brand-new organisation from an exported org bundle,
    including every project it contains. Never merges into an existing
    organisation — see the module docstring for why (mirrors
    `import_project_bundle`'s same "always fresh" design; the merge
    equivalent is `merge_org_bundle`).

    Args:
        db: An active database session.
        name: Overrides the bundle's own org name if given.
        zip_bytes: The uploaded bundle's raw bytes.
        current_user: The server admin performing the import.

    Returns:
        The new Organization and a list of human-readable import warnings.
    """
    _manifest, data, file_bytes_by_ref, project_data_by_ref = _parse_org_bundle(zip_bytes)
    warnings = BundleImportWarnings()

    org = Organization(
        name=name if name else data.get("name", "Imported Organisation"),
        accent_color_hex=data.get("accent_color_hex"), header_title=data.get("header_title"),
        require_2fa=data.get("require_2fa", False), allow_self_signup=data.get("allow_self_signup", False),
        auto_accept_email_domain=data.get("auto_accept_email_domain"),
        external_user_policy=data.get("external_user_policy", "disabled"),
        smtp_host=data.get("smtp_host"), smtp_port=data.get("smtp_port"), smtp_username=data.get("smtp_username"),
        smtp_use_tls=data.get("smtp_use_tls", True),
        # Deliberately not carried over from the bundle — see module docstring.
        sso_enabled=False, sso_only=False,
        oidc_issuer_url=data.get("oidc_issuer_url"), oidc_client_id=data.get("oidc_client_id"),
        oidc_required_group=data.get("oidc_required_group"), pat_max_lifetime_days=data.get("pat_max_lifetime_days"),
        default_report_intro=data.get("default_report_intro"), default_report_chapters=data.get("default_report_chapters"),
        default_report_appendices=data.get("default_report_appendices"),
    )
    db.add(org)
    db.flush()
    # Default project statuses/link types, same as any other new
    # organisation (`routers/orgs.py::create_organization`) — a bundle
    # doesn't currently carry its source organisation's status/link-type
    # customisations across, so the new organisation simply starts with the
    # standard defaults. `_import_projects` (below, via
    # `new_project_from_bundle_data`) needs at least a default status to
    # exist before it creates this org's first imported project.
    seed_project_statuses(db, org.id)
    seed_link_types(db, org.id)
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

    _import_report_templates(db, org, data, current_user, resolutions=None)
    acting_user, find_user = _import_members(db, org, data, current_user, warnings, reassign_acting_user=True)
    users = UserResolver(db, acting_user, warnings)
    _import_org_groups(db, org, data, find_user, warnings, merge_by_name=False)
    project_id_by_ref = _import_projects(db, org, project_data_by_ref, file_bytes_by_ref, acting_user, users, warnings, resolutions=None)

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


def _compute_merge_conflicts(
    db: Session, target_org: Organization, data: dict[str, Any], project_data_by_ref: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Shared by `detect_merge_conflicts` (which parses the bundle first)
    and `merge_org_bundle` (which has already parsed it) so the bundle's
    zip is only ever read once per request."""
    existing_projects_by_name = {
        p.name.strip().lower(): p for p in db.scalars(select(Project).where(Project.organization_id == target_org.id))
    }
    existing_templates_by_name = {
        t.name.strip().lower(): t for t in db.scalars(select(ReportTemplate).where(ReportTemplate.organization_id == target_org.id))
    }

    conflicts: list[dict[str, Any]] = []
    for ref, project_data in project_data_by_ref.items():
        name = project_data.get("source_name", "Imported Project")
        existing = existing_projects_by_name.get(name.strip().lower())
        if existing is not None:
            conflicts.append({"id": f"project:{ref}", "kind": "project", "name": name, "existing_id": str(existing.id)})
    for t in data.get("report_templates", []):
        existing = existing_templates_by_name.get(t["name"].strip().lower())
        if existing is not None:
            conflicts.append({"id": f"report_template:{t['name']}", "kind": "report_template", "name": t["name"], "existing_id": str(existing.id)})
    return conflicts


def detect_merge_conflicts(db: Session, target_org: Organization, zip_bytes: bytes) -> list[dict[str, Any]]:
    """Parses an org bundle and reports which of its projects and report
    templates collide by name with something `target_org` already has,
    without writing anything — the preview step before `merge_org_bundle`.

    Users and org groups are never a conflict (see `_import_members`/
    `_import_org_groups`'s docstrings: both are purely additive), so they
    never appear here.

    Returns:
        A list of `{"id", "kind", "name", "existing_id"}` dicts. `id` is
        the exact key `merge_org_bundle`'s `resolutions` argument must
        supply a resolution for; `kind` is `"project"` or
        `"report_template"`.
    """
    _, data, _, project_data_by_ref = _parse_org_bundle(zip_bytes)
    return _compute_merge_conflicts(db, target_org, data, project_data_by_ref)


def merge_org_bundle(
    db: Session, *, target_org: Organization, zip_bytes: bytes, resolutions: dict[str, str], current_user: User,
) -> tuple[list[str], dict[str, int]]:
    """Imports an org bundle's users, groups, projects, and report
    templates into `target_org` — an organisation that already exists,
    unlike `import_org_bundle` which always creates a brand-new one.

    Deliberately narrower than `import_org_bundle` in what it touches:
    `target_org`'s own profile — branding, SMTP, SSO/OIDC config, logo,
    login background, default template project, `slug`, `is_active`,
    `pat_max_lifetime_days` — is never read from the bundle or modified.
    Those fields carry real security/tenancy meaning for an organisation
    that's already configured and in active use, unlike a fresh import
    where they start from nothing; silently overwriting an admin's live
    SSO/SMTP configuration or branding as a side effect of importing some
    projects would be a surprising, security-relevant regression this
    feature has no need to risk. This is also why this path requires the
    caller to be an `org_admin` of `target_org` itself (see
    `routers/orgs.py`'s endpoint), never a server-admin bypass — an
    existing tenant boundary is being crossed here, unlike
    `import_org_bundle`'s brand-new organisation (see module docstring).

    `resolutions` must have exactly one entry per conflict
    `detect_merge_conflicts` would report for this same bundle/`target_org`
    pair — a project or report template that collides by name and has no
    supplied resolution is refused outright (400) rather than silently
    defaulted either way, so an import can never partially apply an
    unreviewed conflict.

    Args:
        db: An active database session.
        target_org: The organisation being imported into.
        zip_bytes: The uploaded bundle's raw bytes.
        resolutions: Conflict id (`detect_merge_conflicts`'s `"id"` field)
            -> `"skip"`/`"import_as_copy"` for a `"project"` conflict, or
            `"keep_existing"`/`"use_import"` for a `"report_template"` one.
        current_user: The org admin performing the import.

    Returns:
        Human-readable warnings (same shape as `import_org_bundle`'s), and
        a summary of what happened: `projects_imported`,
        `projects_skipped`, `report_templates_imported`,
        `report_templates_overwritten`.

    Raises:
        HTTPException: 400 if the bundle is invalid or newer than this
            deployment supports, if `resolutions` is missing an entry for
            a conflict this bundle/org pair actually has, or if a supplied
            resolution's value isn't valid for its conflict's kind.
    """
    manifest, data, file_bytes_by_ref, project_data_by_ref = _parse_org_bundle(zip_bytes)
    conflicts = _compute_merge_conflicts(db, target_org, data, project_data_by_ref)

    missing = [c["id"] for c in conflicts if c["id"] not in resolutions]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing a resolution for: {', '.join(missing)}.")
    invalid = [
        c["id"] for c in conflicts
        if resolutions[c["id"]] not in (_PROJECT_RESOLUTIONS if c["kind"] == "project" else _REPORT_TEMPLATE_RESOLUTIONS)
    ]
    if invalid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid resolution value for: {', '.join(invalid)}.")

    warnings = BundleImportWarnings()
    acting_user, find_user = _import_members(db, target_org, data, current_user, warnings, reassign_acting_user=False)
    users = UserResolver(db, acting_user, warnings)
    _import_org_groups(db, target_org, data, find_user, warnings, merge_by_name=True)
    _import_report_templates(db, target_org, data, current_user, resolutions=resolutions)
    project_id_by_ref = _import_projects(
        db, target_org, project_data_by_ref, file_bytes_by_ref, acting_user, users, warnings, resolutions=resolutions,
    )

    project_conflicts = [c for c in conflicts if c["kind"] == "project"]
    template_conflicts = [c for c in conflicts if c["kind"] == "report_template"]
    summary = {
        "projects_imported": len(project_id_by_ref),
        "projects_skipped": sum(1 for c in project_conflicts if resolutions[c["id"]] == "skip"),
        "report_templates_imported": len(data.get("report_templates", [])) - len(template_conflicts) + sum(
            1 for c in template_conflicts if resolutions[c["id"]] == "use_import"
        ),
        "report_templates_overwritten": sum(1 for c in template_conflicts if resolutions[c["id"]] == "use_import"),
    }
    log_event(
        db, entity_type="organization", entity_id=target_org.id, action="merged_from_bundle", actor_id=current_user.id,
        organization_id=target_org.id,
        detail={
            "warning_count": len(warnings.messages), **summary,
            # Provenance of the merged-in data — unlike `import_org_bundle`
            # (which only ever creates a brand-new organisation from a
            # bundle), this action writes into an org's real, live data, so
            # "who did this" alone isn't enough for an incident review to
            # trace *where the data came from* without this. `manifest`'s
            # fields are the bundle's own self-reported metadata (written
            # by `build_org_bundle` at export time), not independently
            # verified — same trust level as the rest of the bundle's
            # contents, which the target org_admin already chose to import.
            "source_org_name": manifest.get("org_name"),
            "source_exported_by_email": manifest.get("exported_by_email"),
            "source_exported_at": manifest.get("exported_at"),
        },
    )
    db.commit()
    db.refresh(target_org)
    return warnings.messages, summary
