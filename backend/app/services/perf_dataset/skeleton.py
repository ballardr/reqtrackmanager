"""
Module: services.perf_dataset.skeleton

Builds the dataset's structure (organisations, people, projects, their roles, components and categories)
through the application's own HTTP API.

Responsibilities:
- Create organisations, an administrator and members per organisation, enable every module for each, the projects (flat or nested), the
  taxonomy each project needs for requirement codes, and the project roles.
- Return a `Skeleton` that the bulk phase fills with records.

Design decisions:
- The structure is small relative to the records (hundreds of rows against up to a hundred thousand), so it is
  created through the real API: organisation creation seeds link types, roles and module state through hooks that
  a hand-written insert would silently miss. Only the high-volume records are bulk-inserted
  (`perf_dataset.core`).
- The HTTP client is any object with httpx's `.get/.post/.put` methods (httpx.Client against a running server,
  or the test client), so the same code runs against the stack and in the backend tests.
- Names are generic and deterministic (`Perf Org 03`, `perf-o03-u2@perf.example.com`); no real data.

Dependencies: an httpx-compatible client; the application's API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.perf_dataset.spec import DatasetSpec

EMAIL_DOMAIN = "perf.example.com"
API = "/api/v1"


class Client(Protocol):
    """The slice of an httpx client the builder uses."""

    def get(self, url: str, **kwargs: Any) -> Any: ...  # noqa: D102
    def post(self, url: str, **kwargs: Any) -> Any: ...  # noqa: D102
    def put(self, url: str, **kwargs: Any) -> Any: ...  # noqa: D102


class SkeletonError(RuntimeError):
    """An API call needed to build the structure failed; the message names the call and the status."""


@dataclass
class ProjectPlan:
    """One generated project.

    Attributes:
        id: Project id (string UUID).
        organization_id: Owning organisation id.
        name: Project name.
        parent_id: Parent project id, or None for a root.
        depth: 0 for a root, 1 for its children, and so on.
        components: `(component id, prefix)` pairs.
        categories: `(category id, component id, prefix)` triples.
        stage_ids: The project's stage ids, earliest first.
    """

    id: str
    organization_id: str
    name: str
    parent_id: str | None
    depth: int
    components: list[tuple[str, str]] = field(default_factory=list)
    categories: list[tuple[str, str, str]] = field(default_factory=list)
    stage_ids: list[str] = field(default_factory=list)


@dataclass
class OrgPlan:
    """One generated organisation.

    Attributes:
        id: Organisation id.
        index: Its 1-based position.
        name: Organisation name.
        admin_email: The organisation administrator's login.
        member_emails: The other people's logins.
        user_ids: Every person's user id, administrator first.
        projects: The organisation's projects, parents before children.
    """

    id: str
    index: int
    name: str
    admin_email: str
    member_emails: list[str]
    user_ids: list[str]
    projects: list[ProjectPlan] = field(default_factory=list)


@dataclass
class Skeleton:
    """The structure built for one dataset."""

    organisations: list[OrgPlan] = field(default_factory=list)


def _check(response: Any, what: str) -> Any:
    """Returns the JSON body of a successful response, else raises `SkeletonError` naming the call."""
    if response.status_code >= 400:
        raise SkeletonError(f"{what} failed with {response.status_code}: {response.text[:200]}")
    return response.json() if response.content else None


def _login(client: Client, email: str, password: str) -> dict:
    """Signs in and returns the Authorization header."""
    body = _check(client.post(f"{API}/auth/login", json={"email": email, "password": password}), f"login as {email}")
    return {"Authorization": f"Bearer {body['access_token']}"}


def user_email(org_index: int, user_index: int) -> str:
    """The login of person `user_index` (0 is the administrator) in organisation `org_index`."""
    role = "admin" if user_index == 0 else f"u{user_index}"
    return f"perf-o{org_index:02d}-{role}@{EMAIL_DOMAIN}"


def _project_names(spec: DatasetSpec, org_index: int) -> list[tuple[str, int | None, int]]:
    """`(name, parent position or None, depth)` for every project of one organisation, parents first."""
    topology = spec.topology
    if not topology.is_nested:
        return [(f"Perf Project {org_index:02d}-{n:03d}", None, 0) for n in range(1, topology.projects_per_org + 1)]
    names: list[tuple[str, int | None, int]] = [(f"Perf Project {org_index:02d}-L0-001", None, 0)]
    previous_level = [0]
    for depth in range(1, topology.nesting_depth):
        this_level = []
        for parent_position in previous_level:
            for _ in range(topology.nesting_fanout):
                names.append((f"Perf Project {org_index:02d}-L{depth}-{len(names) + 1:03d}", parent_position, depth))
                this_level.append(len(names) - 1)
        previous_level = this_level
    return names


def _enable_modules(client: Client, org_id: str, headers: dict) -> None:
    """Turns on every registered module and sub-component for the organisation, so the generated records of every
    type are reachable through the API (a module is off until an organisation administrator enables it)."""
    from app.modules.registry import get_module_registry

    for key, definition in get_module_registry().items():
        _check(client.put(f"{API}/orgs/{org_id}/modules/{key}", json={"enabled": True}, headers=headers), f"enable module {key}")
        for sub in definition.sub_components:
            _check(
                client.put(f"{API}/orgs/{org_id}/modules/{key}/subcomponents/{sub.key}", json={"enabled": True}, headers=headers),
                f"enable {key}/{sub.key}",
            )


def build_skeleton(
    client: Client,
    spec: DatasetSpec,
    *,
    admin_email: str,
    admin_password: str,
    user_password: str,
    say: Any = print,
) -> Skeleton:
    """Creates the organisations, people and projects the spec describes.

    Args:
        client: An httpx-compatible client for the running application.
        spec: What to build.
        admin_email / admin_password: The server administrator, who creates organisations and people.
        user_password: The password every generated person gets (reset per run by the runner).
        say: Progress sink.

    Returns:
        The skeleton, with every id the bulk phase needs.

    Raises:
        SkeletonError: If an API call fails.
    """
    server_headers = _login(client, admin_email, admin_password)
    skeleton = Skeleton()
    for org_index in range(1, spec.topology.organisations + 1):
        name = f"Perf Org {org_index:02d}"
        org = _check(client.post(f"{API}/orgs", json={"name": name}, headers=server_headers), f"create {name}")
        emails = [user_email(org_index, n) for n in range(spec.users_per_org)]
        user_ids = []
        for n, email in enumerate(emails):
            created = _check(
                client.post(
                    f"{API}/orgs/{org['id']}/users",
                    headers=server_headers,
                    json={
                        "email": email,
                        "display_name": f"Perf User {org_index:02d}.{n}",
                        "password": user_password,
                        "role": "org_admin" if n == 0 else "member",
                    },
                ),
                f"create {email}",
            )
            user_ids.append(created["user_id"])
        plan = OrgPlan(id=org["id"], index=org_index, name=name, admin_email=emails[0], member_emails=emails[1:], user_ids=user_ids)
        admin_headers = _login(client, emails[0], user_password)
        _enable_modules(client, org["id"], admin_headers)
        specs = _project_names(spec, org_index)
        for project_name, parent_position, depth in specs:
            is_parent = spec.topology.is_nested and depth < spec.topology.nesting_depth - 1
            payload: dict[str, Any] = {"organization_id": org["id"], "name": project_name, "summary": "Generated performance dataset project."}
            if parent_position is not None:
                payload["parent_project_id"] = plan.projects[parent_position].id
            if is_parent:
                payload["can_be_parent"] = True
            project = _check(client.post(f"{API}/projects", json=payload, headers=admin_headers), f"create {project_name}")
            project_plan = ProjectPlan(
                id=project["id"],
                organization_id=org["id"],
                name=project_name,
                parent_id=plan.projects[parent_position].id if parent_position is not None else None,
                depth=depth,
            )
            for component_index in range(1, 3):
                component = _check(
                    client.post(
                        f"{API}/projects/{project['id']}/components",
                        headers=admin_headers,
                        json={"name": f"Component {component_index}", "prefix": f"C{component_index}"},
                    ),
                    "create component",
                )
                project_plan.components.append((component["id"], f"C{component_index}"))
                for category_index in range(1, 3):
                    category = _check(
                        client.post(
                            f"{API}/projects/{project['id']}/categories",
                            headers=admin_headers,
                            json={"name": f"Category {category_index}", "prefix": f"K{category_index}", "component_id": component["id"]},
                        ),
                        "create category",
                    )
                    project_plan.categories.append((category["id"], component["id"], f"K{category_index}"))
            stages = _check(client.get(f"{API}/projects/{project['id']}/stages", headers=admin_headers), "list stages")
            project_plan.stage_ids = [s["id"] for s in sorted(stages, key=lambda s: s["sort_order"])]
            for member_index, member_id in enumerate(user_ids[1:], start=1):
                role = "project_manager" if member_index == 1 else "stakeholder"
                _check(
                    client.post(f"{API}/projects/{project['id']}/roles", headers=admin_headers, json={"user_id": member_id, "role": role}),
                    "assign project role",
                )
            plan.projects.append(project_plan)
        skeleton.organisations.append(plan)
        say(f"skeleton: {name} with {len(plan.projects)} projects and {len(user_ids)} people")
    return skeleton
