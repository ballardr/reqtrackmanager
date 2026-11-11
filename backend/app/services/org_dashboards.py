"""
Module: services.org_dashboards

An organisation's dashboard pages: the widget pages on its overview, who may see each, and who may change them.

Responsibilities:
- List, read, create, rename, reorder, restrict, lay out and delete pages, with one visibility rule
  (`can_view`) used by the list, the page read and the metrics request, so a restricted page cannot be fetched or its
  figures requested by URL.
- Validate a page's layout with the shared widget rules (`overview_widgets.WidgetRules`) against the organisation
  catalogue (`org_dashboard_metrics`) and the organisation widgets modules contribute.
- Provide the built-in first page ("Overview"), which exists before anyone stores it and is stored on the first edit.

Design decisions:
- An organisation administrator always sees and changes every page. A page with no viewer rows is shown to every
  member; otherwise only to the viewers (a user, or an organisation group by effective membership) and administrators.
- A page the caller may not see is a 404, never a 403, so its existence is not revealed.
- A viewer must be a member or a group of this organisation (`principals.validate_principal`; a project group cannot
  name an organisation page), so a foreign group is refused.
- The viewer reference is mandatory (`principals.CORE_PRINCIPAL_REFERENCES`): deleting a group that restricts a page
  needs a replacement, so removing a group never widens who may see a page.
- Every change is audited with counts and names only, never widget content.
- A bundle carries the pages with their viewers by email or group name. An import never widens a page: a viewer
  that cannot be matched stands as the importing user, so a restricted page stays restricted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole, PrincipalType
from app.models.org_dashboard import MAX_DASHBOARD_NAME_LENGTH, OrganizationDashboard, OrganizationDashboardViewer
from app.models.user import User
from app.modules.registry import OverviewMetric, get_org_overview_widget_types, is_module_enabled
from app.schemas.principal import PrincipalRef
from app.services import org_dashboard_metrics
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings
from app.services.overview_widgets import CORE_WIDGET_TYPES, WidgetRules, WidgetTypeInfo, validate_layout
from app.services.principals import is_principal_member, principal_from_bundle, principal_to_bundle, validate_principal
from app.services.rbac import get_effective_org_roles

#: The id the built-in first page answers to before it has been stored.
OVERVIEW_ID = "overview"
OVERVIEW_NAME = "Overview"

#: Most pages an organisation may have and most viewers one page may name.
MAX_DASHBOARDS = 20
MAX_VIEWERS = 50

#: The core widget types an organisation dashboard offers (the others read one project).
CORE_DASHBOARD_TYPES = frozenset({"metric_tile", "gauge", "status_chart", "text"})


@dataclass
class DashboardView:
    """A page as the service hands it on.

    Attributes:
        id: The row id as text, or `OVERVIEW_ID` for the built-in page (whether or not it has been stored yet).
        row: The stored row, `None` for the built-in page that has not been stored.
        viewers: The principals the page is limited to (empty: every member).
    """

    id: str
    name: str
    position: int
    is_default: bool
    row: OrganizationDashboard | None
    viewers: list[PrincipalRef]


def _refuse(code: int, message: str) -> HTTPException:
    """An HTTP error with `message`."""
    return HTTPException(code, message)


# --- widget catalogue and validation ----------------------------------------------------------------


def widget_types(db: Session, organization_id: uuid.UUID) -> list[WidgetTypeInfo]:
    """The widget types an organisation dashboard can add: the core types that read an organisation and those of each
    module the organisation has enabled."""
    found = [info for info in CORE_WIDGET_TYPES if info.key in CORE_DASHBOARD_TYPES]
    for key, (module_key, widget) in get_org_overview_widget_types().items():
        if is_module_enabled(db, organization_id, module_key):
            found.append(WidgetTypeInfo(key, widget.label, widget.description, module_key, widget.width, widget.height, widget.in_default_layout))
    return found


def rules(db: Session, organization_id: uuid.UUID) -> WidgetRules:
    """The validation rules for a dashboard layout of `organization_id`."""

    def metric(raw_metric: Any, raw_params: Any) -> tuple[str, dict[str, Any], OverviewMetric]:
        key, params = org_dashboard_metrics.validate_reference(db, organization_id, raw_metric, raw_params)
        return key, params, org_dashboard_metrics.catalogue_for(db, organization_id)[key][1]

    return WidgetRules(core_types=CORE_DASHBOARD_TYPES, module_types=get_org_overview_widget_types, metric=metric, scoped=False)


def _widget(widget_id: str, widget_type: str, width: int, height: int, config: dict[str, Any]) -> dict[str, Any]:
    """A built-in widget."""
    return {
        "id": widget_id, "type": widget_type, "title": None, "width": width, "height": height, "scope": None, "visible": True,
        "config": config,
    }


def default_layout(db: Session, organization_id: uuid.UUID) -> dict[str, Any]:
    """The built-in Overview layout: the four headline figures, then the widgets the enabled modules ask to be in it."""
    contributed = [
        _widget(info.key.replace(":", "-"), info.key, info.width, info.height, {})
        for info in widget_types(db, organization_id) if info.module_key is not None and info.in_default_layout
    ]
    return {"scope": "this", "widgets": [
        _widget("projects", "metric_tile", 3, 2, {"metric": "org_project_count"}),
        _widget("requirements", "metric_tile", 3, 2, {"metric": "org_requirement_count"}),
        _widget("members", "metric_tile", 3, 2, {"metric": "org_member_count"}),
        _widget("storage", "metric_tile", 3, 2, {"metric": "org_file_storage"}),
        *contributed,
    ]}


# --- visibility -------------------------------------------------------------------------------------


def is_manager(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    """True when `user` may change dashboards: an organisation administrator (a server administrator with no role in the
    organisation does not count, as for every organisation-scoped route)."""
    return OrgRole.ORG_ADMIN in get_effective_org_roles(db, user.id, organization_id)


def can_view(db: Session, user: User, organization_id: uuid.UUID, viewers: list[PrincipalRef]) -> bool:
    """Whether `user` may see a page limited to `viewers`.

    An organisation administrator always may; another member may when the page has no viewers or they are one of them
    (a user directly, a group by effective membership); a person with no role in the organisation never may.
    """
    roles = get_effective_org_roles(db, user.id, organization_id)
    if OrgRole.ORG_ADMIN in roles:
        return True
    if not roles:
        return False
    return not viewers or any(is_principal_member(db, viewer, user.id) for viewer in viewers)


def _viewers_of(db: Session, dashboard_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PrincipalRef]]:
    """The viewers of each page, read once."""
    found: dict[uuid.UUID, list[PrincipalRef]] = {dashboard_id: [] for dashboard_id in dashboard_ids}
    if dashboard_ids:
        rows = db.scalars(select(OrganizationDashboardViewer).where(OrganizationDashboardViewer.dashboard_id.in_(dashboard_ids)))
        for row in rows:
            found[row.dashboard_id].append(PrincipalRef(type=PrincipalType(row.viewer_type), id=row.viewer_id))
    return found


def _view(row: OrganizationDashboard, viewers: list[PrincipalRef]) -> DashboardView:
    """A stored page as a view."""
    return DashboardView(OVERVIEW_ID if row.is_default else str(row.id), row.name, row.position, row.is_default, row, viewers)


def _builtin_view() -> DashboardView:
    """The built-in page before it is stored."""
    return DashboardView(OVERVIEW_ID, OVERVIEW_NAME, -1, True, None, [])


def all_pages(db: Session, organization_id: uuid.UUID) -> list[DashboardView]:
    """Every page of the organisation in order, the built-in one first, regardless of who may see it."""
    rows = list(db.scalars(
        select(OrganizationDashboard).where(OrganizationDashboard.organization_id == organization_id)
        .order_by(OrganizationDashboard.is_default.desc(), OrganizationDashboard.position, OrganizationDashboard.name)
    ))
    viewers = _viewers_of(db, [row.id for row in rows])
    pages = [_view(row, viewers[row.id]) for row in rows]
    if not any(page.is_default for page in pages):
        pages.insert(0, _builtin_view())
    return pages


def visible_pages(db: Session, user: User, organization_id: uuid.UUID) -> list[DashboardView]:
    """The pages `user` may see, in order."""
    return [page for page in all_pages(db, organization_id) if can_view(db, user, organization_id, page.viewers)]


def get_page(db: Session, user: User, organization_id: uuid.UUID, dashboard_id: str) -> DashboardView:
    """The page `dashboard_id` as `user` may see it.

    Raises:
        HTTPException: 404 when there is no such page in the organisation or the caller may not see it (the two are
            indistinguishable on purpose).
    """
    for page in all_pages(db, organization_id):
        if page.id == dashboard_id and can_view(db, user, organization_id, page.viewers):
            return page
    raise _refuse(status.HTTP_404_NOT_FOUND, "Dashboard not found.")


def layout_of(db: Session, organization_id: uuid.UUID, page: DashboardView) -> dict[str, Any]:
    """The layout in force for `page`: its stored one, else the built-in layout for the first page, else an empty one."""
    stored = page.row.layout if page.row is not None else {}
    if stored and "widgets" in stored:
        return {"scope": "this", "widgets": list(stored["widgets"])}
    if page.is_default:
        return default_layout(db, organization_id)
    return {"scope": "this", "widgets": []}


# --- changes ----------------------------------------------------------------------------------------


def _clean_name(db: Session, organization_id: uuid.UUID, raw: str, *, exclude: uuid.UUID | None = None) -> str:
    """A page name trimmed and checked.

    Raises:
        HTTPException: 422 for an empty, too long or non-text name; 409 for one the organisation already uses.
    """
    name = " ".join(raw.split())
    if not name or len(name) > MAX_DASHBOARD_NAME_LENGTH or any(not ch.isprintable() for ch in name):
        raise _refuse(status.HTTP_422_UNPROCESSABLE_CONTENT, f"A dashboard name has 1 to {MAX_DASHBOARD_NAME_LENGTH} plain characters.")
    taken = [page for page in all_pages(db, organization_id) if page.name.lower() == name.lower() and (exclude is None or page.id != str(exclude))]
    if taken:
        raise _refuse(status.HTTP_409_CONFLICT, "The organisation already has a dashboard with this name.")
    return name


def _set_viewers(db: Session, organization_id: uuid.UUID, row: OrganizationDashboard, viewers: list[PrincipalRef]) -> None:
    """Replaces the page's viewers.

    Raises:
        HTTPException: 422 for too many or repeated viewers; 400 for a user outside the organisation or a group of another one.
    """
    if len(viewers) > MAX_VIEWERS:
        raise _refuse(status.HTTP_422_UNPROCESSABLE_CONTENT, f"A dashboard may be limited to at most {MAX_VIEWERS} people or groups.")
    if len({(v.type, v.id) for v in viewers}) != len(viewers):
        raise _refuse(status.HTTP_422_UNPROCESSABLE_CONTENT, "A person or group may be listed once.")
    for viewer in viewers:
        validate_principal(db, viewer, organization_id=organization_id, project_id=None, field="viewer")
    db.execute(delete(OrganizationDashboardViewer).where(OrganizationDashboardViewer.dashboard_id == row.id))
    for viewer in viewers:
        db.add(OrganizationDashboardViewer(dashboard_id=row.id, viewer_type=viewer.type.value, viewer_id=viewer.id))


def _materialise_default(db: Session, organization_id: uuid.UUID) -> OrganizationDashboard:
    """The stored row of the built-in page, created (empty layout, so the built-in layout still applies) when absent."""
    existing = db.scalar(select(OrganizationDashboard).where(
        OrganizationDashboard.organization_id == organization_id, OrganizationDashboard.is_default.is_(True),
    ))
    if existing is not None:
        return existing
    row = OrganizationDashboard(organization_id=organization_id, name=OVERVIEW_NAME, position=-1, is_default=True, layout={})
    db.add(row)
    db.flush()
    return row


def _row_for_write(db: Session, organization_id: uuid.UUID, dashboard_id: str) -> OrganizationDashboard:
    """The stored row to change, the built-in page's row being created on demand.

    Raises:
        HTTPException: 404 when the page does not exist in the organisation.
    """
    if dashboard_id == OVERVIEW_ID:
        return _materialise_default(db, organization_id)
    try:
        key = uuid.UUID(dashboard_id)
    except ValueError:
        raise _refuse(status.HTTP_404_NOT_FOUND, "Dashboard not found.") from None
    row = db.get(OrganizationDashboard, key)
    if row is None or row.organization_id != organization_id:
        raise _refuse(status.HTTP_404_NOT_FOUND, "Dashboard not found.")
    return row


def create_page(
    db: Session, organization_id: uuid.UUID, name: str, viewers: list[PrincipalRef], actor_id: uuid.UUID,
) -> OrganizationDashboard:
    """Adds an empty page at the end.

    Raises:
        HTTPException: 409 at `MAX_DASHBOARDS` pages or for a repeated name; 422/400 as `_clean_name` and `_set_viewers`.
    """
    held = db.scalar(select(func.count()).select_from(OrganizationDashboard).where(OrganizationDashboard.organization_id == organization_id)) or 0
    if held >= MAX_DASHBOARDS:
        raise _refuse(status.HTTP_409_CONFLICT, f"An organisation may have at most {MAX_DASHBOARDS} dashboards.")
    cleaned = _clean_name(db, organization_id, name)
    last = db.scalar(select(func.max(OrganizationDashboard.position)).where(OrganizationDashboard.organization_id == organization_id))
    row = OrganizationDashboard(
        organization_id=organization_id, name=cleaned, position=(last if last is not None else 0) + 1,
        layout={"scope": "this", "widgets": []},
    )
    db.add(row)
    db.flush()
    _set_viewers(db, organization_id, row, viewers)
    log_event(
        db, entity_type="organization_dashboard", entity_id=row.id, action="created", actor_id=actor_id,
        organization_id=organization_id, detail={"name": cleaned, "viewers": len(viewers)},
    )
    return row


def copy_page(db: Session, organization_id: uuid.UUID, dashboard_id: str, name: str | None, actor_id: uuid.UUID) -> OrganizationDashboard:
    """Adds a page that starts as a copy of another: its layout in force and the same viewers.

    The viewers are copied so a copy of a restricted page is as restricted as the page it came from (its widgets may hold notes
    only those people were meant to read). Without a `name` the copy is "Copy of <name>", made unique with a number.

    Raises:
        HTTPException: 404 for an unknown page; 409 at `MAX_DASHBOARDS` pages or for a `name` the organisation already uses.
    """
    source = next((p for p in all_pages(db, organization_id) if p.id == dashboard_id), None)
    if source is None:
        raise _refuse(status.HTTP_404_NOT_FOUND, "Dashboard not found.")
    if name is not None:
        chosen = name
    else:
        taken = {p.name.lower() for p in all_pages(db, organization_id)}
        base = f"Copy of {source.name}"[:MAX_DASHBOARD_NAME_LENGTH - 4]
        chosen, number = base, 1
        while chosen.lower() in taken:
            number += 1
            chosen = f"{base} ({number})"
    row = create_page(db, organization_id, chosen, source.viewers, actor_id)
    row.layout = layout_of(db, organization_id, source)
    log_event(
        db, entity_type="organization_dashboard", entity_id=row.id, action="copied", actor_id=actor_id,
        organization_id=organization_id, detail={"from": source.name, "widgets": len(row.layout.get("widgets", []))},
    )
    return row


def update_page(
    db: Session, organization_id: uuid.UUID, dashboard_id: str, name: str | None, viewers: list[PrincipalRef] | None, actor_id: uuid.UUID,
) -> OrganizationDashboard:
    """Renames a page and/or replaces its viewers (`None` leaves each unchanged; an empty list shows the page to every member).

    Raises:
        HTTPException: 409 when renaming the built-in page or reusing a name; 404 for an unknown page; 422/400 as above.
    """
    row = _row_for_write(db, organization_id, dashboard_id)
    detail: dict[str, Any] = {}
    if name is not None and name != row.name:
        if row.is_default:
            raise _refuse(status.HTTP_409_CONFLICT, "The built-in Overview page cannot be renamed.")
        detail["from"], detail["to"] = row.name, _clean_name(db, organization_id, name, exclude=row.id)
        row.name = detail["to"]
    if viewers is not None:
        _set_viewers(db, organization_id, row, viewers)
        detail["viewers"] = len(viewers)
    if detail:
        log_event(
            db, entity_type="organization_dashboard", entity_id=row.id, action="updated", actor_id=actor_id,
            organization_id=organization_id, detail=detail,
        )
    return row


def set_layout(db: Session, organization_id: uuid.UUID, dashboard_id: str, raw: Any, actor_id: uuid.UUID) -> dict[str, Any]:
    """Validates and stores a page's layout; `raw` of `None` restores it (the built-in layout for the first page, empty otherwise).

    Returns:
        The layout now in force.
    """
    row = _row_for_write(db, organization_id, dashboard_id)
    cleaned = validate_layout(raw, rules(db, organization_id)) if raw is not None else {}
    row.layout = cleaned
    log_event(
        db, entity_type="organization_dashboard", entity_id=row.id, action="layout_changed" if raw is not None else "layout_restored",
        actor_id=actor_id, organization_id=organization_id, detail={"widgets": len(cleaned.get("widgets", []))},
    )
    db.flush()
    return layout_of(db, organization_id, _view(row, []))


def delete_page(db: Session, organization_id: uuid.UUID, dashboard_id: str, actor_id: uuid.UUID) -> None:
    """Deletes a page.

    Raises:
        HTTPException: 409 for the built-in page; 404 for an unknown page.
    """
    row = _row_for_write(db, organization_id, dashboard_id) if dashboard_id != OVERVIEW_ID else None
    if row is None or row.is_default:
        raise _refuse(status.HTTP_409_CONFLICT, "The built-in Overview page cannot be deleted.")
    log_event(
        db, entity_type="organization_dashboard", entity_id=row.id, action="deleted", actor_id=actor_id,
        organization_id=organization_id, detail={"name": row.name},
    )
    db.delete(row)


def reorder_pages(db: Session, organization_id: uuid.UUID, ordered_ids: list[str], actor_id: uuid.UUID) -> None:
    """Orders the pages after the built-in one as `ordered_ids` says.

    Raises:
        HTTPException: 422 when the ids are not exactly the organisation's other pages.
    """
    others = [page for page in all_pages(db, organization_id) if not page.is_default]
    if sorted(ordered_ids) != sorted(page.id for page in others):
        raise _refuse(status.HTTP_422_UNPROCESSABLE_CONTENT, "List every dashboard once to reorder them.")
    by_id = {page.id: page.row for page in others}
    for position, dashboard_id in enumerate(ordered_ids, start=1):
        row = by_id[dashboard_id]
        if row is not None:
            row.position = position
    log_event(
        db, entity_type="organization_dashboard", entity_id=organization_id, action="reordered", actor_id=actor_id,
        organization_id=organization_id, detail={"count": len(ordered_ids)},
    )


# --- bundles ------------------------------------------------------------------------------------------

#: Section of the organisation bundle that carries the pages.
BUNDLE_KEY = "organization_dashboards"


def export_org(db: Session, organization_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    """The organisation's stored pages as an `org.json` section: name, order, layout and viewers (by email or group name).

    The built-in page is carried only once it has been stored (it has a layout or viewers of its own).
    """
    pages = []
    for page in all_pages(db, organization_id):
        if page.row is None:
            continue
        pages.append({
            "name": page.name, "position": page.position, "is_default": page.is_default, "layout": page.row.layout,
            "viewers": [bundled for v in page.viewers if (bundled := principal_to_bundle(db, v.type.value, v.id)) is not None],
        })
    return {BUNDLE_KEY: pages}


def import_org(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
) -> None:
    """Adds the bundle's pages to an organisation.

    A page whose name the organisation already has is kept as it is (an import never overwrites), the built-in page is
    taken only while the organisation has not stored its own, and a layout that is not valid here is dropped with a
    warning (the page is kept, empty or built-in). A viewer that cannot be matched becomes the importing user, so an
    import never widens a restricted page.
    """
    raw = data.get(BUNDLE_KEY)
    held = {page.name.lower() for page in all_pages(db, organization_id) if page.row is not None}
    default_stored = any(page.is_default and page.row is not None for page in all_pages(db, organization_id))
    cache: dict[Any, Any] = {}
    layout_rules = rules(db, organization_id)
    count = len(held)
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            warnings.add("A dashboard in the bundle was not imported because it is not valid here.")
            continue
        is_default = bool(entry.get("is_default"))
        if (is_default and default_stored) or (not is_default and entry["name"].lower() in held):
            continue
        if count >= MAX_DASHBOARDS:
            warnings.add(f"Dashboards beyond the limit of {MAX_DASHBOARDS} were not imported.")
            break
        try:
            layout = validate_layout(entry.get("layout") or {"scope": "this", "widgets": []}, layout_rules) if entry.get("layout") else {}
        except HTTPException:
            warnings.add(f"The layout of dashboard '{entry['name']}' is not valid here and was not imported.")
            layout = {} if is_default else {"scope": "this", "widgets": []}
        row = OrganizationDashboard(
            organization_id=organization_id, name=OVERVIEW_NAME if is_default else " ".join(entry["name"].split())[:MAX_DASHBOARD_NAME_LENGTH],
            position=-1 if is_default else int(entry.get("position") or count + 1), is_default=is_default, layout=layout,
        )
        db.add(row)
        db.flush()
        viewers: list[PrincipalRef] = []
        for bundled in entry.get("viewers") or []:
            ref, warning = principal_from_bundle(
                db, bundled, organization_id=organization_id, project_id=None, fallback_user_id=actor.id, user_cache=cache,
            )
            if warning:
                warnings.add(f"Dashboard '{row.name}': {warning}")
            if ref is not None and all((v.type, v.id) != (ref.type, ref.id) for v in viewers):
                viewers.append(ref)
        for viewer in viewers:
            db.add(OrganizationDashboardViewer(dashboard_id=row.id, viewer_type=viewer.type.value, viewer_id=viewer.id))
        held.add(row.name.lower())
        default_stored = default_stored or is_default
        count += 1
    db.flush()
