"""
Module: loadgen.scenarios

The Locust user classes, one per scenario, that drive the application's HTTP API.

Responsibilities:
- Define what each simulated person does (browse, search, edit, export, report, bundle, attachment) against the
  generated dataset, addressing records through the dataset manifest rather than listing first.
- Name every request after its endpoint template, not its URL, so statistics aggregate per endpoint.

Design decisions:
- Authentication happens once per simulated person before the run (`run.py`), never in a task, so the numbers
  measure the API and not bcrypt (login is deliberately slow).
- A search answered `429` is recorded as a failure with the message `throttled`; the summary reports those apart
  from real failures, because the per-person search limit working as built is not an application fault.
- A scenario that creates data names it with a run-unique suffix, so repeated and concurrent runs never collide.
- `SCENARIOS` is the single registry; `perf/lib/catalog.py` (host side) lists the same names and a test keeps the
  two in step.

Dependencies: locust.
"""

from __future__ import annotations

import io
import random
import uuid

from locust import HttpUser, constant, constant_throughput, task

SEARCH_WORDS = ("controller", "sensor", "interface", "recover", "audit", "gateway", "firmware", "operator", "latency", "backup")
TAG_WORDS = ("safety", "security", "performance", "usability", "regulatory")
ATTACHMENT_BYTES = 256 * 1024
LONG_TIMEOUT = 600
CAPACITY_TIMEOUT = 30
#: The failure message of a request the server throttled on purpose; `run.py` reports these apart from failures.
THROTTLED = "throttled"


class PerfUser(HttpUser):
    """Shared behaviour: a signed-in persona acting on one project of the dataset.

    Attributes:
        abstract: Not a runnable scenario itself.
    """

    abstract = True
    wait_time = constant_throughput(2)

    def on_start(self) -> None:
        """Picks a persona and a project from the manifest and installs the persona's token."""
        shared = self.environment.shared
        self.persona = shared.next_persona(admin=self.needs_admin)
        self.client.headers["Authorization"] = f"Bearer {self.persona['token']}"
        self.project = shared.pick_project(self.persona, nested_root=self.needs_nested_root)
        self.created: list[str] = []

    needs_admin = False
    needs_nested_root = False

    @property
    def base(self) -> str:
        """The project's API prefix."""
        return f"/api/v1/projects/{self.project['id']}"

    def requirement_id(self) -> str:
        """A sampled requirement of the project."""
        return random.choice(self.project["requirement_sample"])

    def hub_id(self) -> str:
        """A heavily linked requirement of the project (a random one if the project has no links)."""
        return random.choice(self.project["hubs"] or self.project["requirement_sample"])

    def get(self, path: str, name: str, **kwargs):
        """GET with the endpoint template as the statistics name."""
        return self.client.get(path, name=name, **kwargs)


class Browse(PerfUser):
    """Reading a project the way the screens do: lists, a record, its links, comments, activity, the dashboard."""

    @task(5)
    def projects(self) -> None:
        self.get("/api/v1/projects", "GET /projects")

    @task(10)
    def requirements_page(self) -> None:
        offset = random.randrange(0, max(1, self.project["requirements"] - 50))
        self.get(f"{self.base}/requirements?limit=50&offset={offset}", "GET /projects/{id}/requirements (page of 50)")

    @task(10)
    def requirement(self) -> None:
        self.get(f"{self.base}/requirements/{self.requirement_id()}", "GET /projects/{id}/requirements/{id}")

    @task(5)
    def links(self) -> None:
        self.get(f"{self.base}/requirements/{self.requirement_id()}/links", "GET /requirements/{id}/links")

    @task(5)
    def comments(self) -> None:
        self.get(f"{self.base}/requirements/{self.requirement_id()}/comments", "GET /requirements/{id}/comments")

    @task(3)
    def activity(self) -> None:
        self.get(f"{self.base}/artefacts/requirement/{self.requirement_id()}/activity?limit=25", "GET /artefacts/{type}/{id}/activity")

    @task(3)
    def dashboard(self) -> None:
        self.get(f"{self.base}/metrics", "GET /projects/{id}/metrics (dashboard)")

    @task(2)
    def tag_usage(self) -> None:
        self.get(f"{self.base}/tags/usage", "GET /projects/{id}/tags/usage")


class ListUnpaged(PerfUser):
    """The default requirement list, which returns every requirement in the project."""

    wait_time = constant(1)

    @task
    def unpaged(self) -> None:
        self.get(f"{self.base}/requirements", "GET /projects/{id}/requirements (unpaged)", timeout=LONG_TIMEOUT)


class ListFiltered(PerfUser):
    """Filter and sort combinations a person uses on the list."""

    @task(3)
    def by_status_sorted(self) -> None:
        self.get(f"{self.base}/requirements?status=approved&sort=name&order=desc&limit=50", "GET requirements (status + sort, page)")

    @task(3)
    def by_tag(self) -> None:
        self.get(f"{self.base}/requirements?tag={random.choice(TAG_WORDS)}&limit=50", "GET requirements (tag, page)")

    @task(3)
    def by_text(self) -> None:
        self.get(f"{self.base}/requirements?search={random.choice(SEARCH_WORDS)}&limit=50", "GET requirements (text search, page)")

    @task(1)
    def with_comments(self) -> None:
        self.get(f"{self.base}/requirements?has_comments=true&sort=created_at&limit=50", "GET requirements (has comments, page)")


class Search(PerfUser):
    """The global search, in one project and across every project the person can open."""

    wait_time = constant_throughput(0.5)

    def _search(self, body: dict, name: str) -> None:
        with self.client.post("/api/v1/search", json=body, name=name, catch_response=True) as response:
            if response.status_code == 429:
                response.failure(THROTTLED)
            elif response.status_code >= 400:
                response.failure(f"{response.status_code}")

    @task(3)
    def in_project(self) -> None:
        self._search({"q": random.choice(SEARCH_WORDS), "scope": "project", "project_id": self.project["id"], "limit": 25}, "POST /search (project)")

    @task(1)
    def everywhere(self) -> None:
        self._search({"q": random.choice(SEARCH_WORDS), "scope": "all", "limit": 25}, "POST /search (all projects)")


class Links(PerfUser):
    """The links finder and trace around a hub record: cost depends on degree, not on row count."""

    @task(3)
    def graph(self) -> None:
        self.get(f"{self.base}/artefacts/requirement/{self.hub_id()}/link-graph", "GET /artefacts/{type}/{id}/link-graph (hub)")

    @task(2)
    def hub_links(self) -> None:
        self.get(f"{self.base}/requirements/{self.hub_id()}/links", "GET /requirements/{id}/links (hub)")

    @task(2)
    def candidates(self) -> None:
        self.get(
            f"{self.base}/artefacts/requirement/{self.requirement_id()}/link-candidates?other_type=requirement&q={random.choice(SEARCH_WORDS)}",
            "GET /artefacts/{type}/{id}/link-candidates",
        )


class Edit(PerfUser):
    """Creating and changing records: counter allocation, a new version, the audit event, tags, comments, actions."""

    wait_time = constant_throughput(1)

    def _owner(self) -> dict:
        return {"type": "user", "id": self.persona["user_id"]}

    @task(3)
    def create(self) -> None:
        suffix = uuid.uuid4().hex[:8]
        with self.client.post(
            f"{self.base}/requirements", name="POST /projects/{id}/requirements (create)", catch_response=True,
            json={"name": f"Perf created {suffix}", "reasoning": "Created by the load generator.", "component_id": self.project["component_id"],
                  "category_id": self.project["category_id"], "keywords": [random.choice(TAG_WORDS)]},
        ) as response:
            if response.status_code == 201:
                self.created.append(response.json()["id"])
            else:
                response.failure(f"{response.status_code}: {response.text[:120]}")

    @task(4)
    def update(self) -> None:
        if not self.created:
            return
        requirement_id = random.choice(self.created)
        self.client.put(
            f"{self.base}/requirements/{requirement_id}", name="PUT /projects/{id}/requirements/{id} (edit)",
            json={"name": f"Perf edited {uuid.uuid4().hex[:6]}", "reasoning": "Edited.", "component_id": self.project["component_id"],
                  "category_id": self.project["category_id"], "owner": self._owner(), "change_note": "Load test edit."},
        )

    @task(2)
    def comment(self) -> None:
        target = random.choice(self.created) if self.created else self.requirement_id()
        self.client.post(f"{self.base}/requirements/{target}/comments", json={"body": "A comment from the load generator."},
                         name="POST /requirements/{id}/comments")

    @task(1)
    def action(self) -> None:
        if not self.created or not self.project.get("action_type_id"):
            return
        self.client.post(
            f"{self.base}/requirements/{random.choice(self.created)}/actions/create-and-link", name="POST /requirements/{id}/actions/create-and-link",
            json={"title": "Perf action", "description": "Created by the load generator.", "action_type_id": self.project["action_type_id"]},
        )


class ExportCsv(PerfUser):
    """The list as a CSV (the file the list's Export button downloads)."""

    needs_admin = True
    wait_time = constant(1)

    @task
    def export(self) -> None:
        self.get(f"{self.base}/records/requirement/export", "GET /records/requirement/export (csv)", timeout=LONG_TIMEOUT)


class ImportPreview(PerfUser):
    """Previewing a CSV import of the project's own export (every row an update, validated and rolled back)."""

    needs_admin = True
    wait_time = constant(1)

    def on_start(self) -> None:
        super().on_start()
        self.csv = self.client.get(f"{self.base}/records/requirement/export", name="setup: export", timeout=LONG_TIMEOUT).content

    @task
    def preview(self) -> None:
        self.client.post(
            f"{self.base}/records/requirement/import?dry_run=true", files={"file": ("requirements.csv", self.csv, "text/csv")},
            name="POST /records/requirement/import (preview)", timeout=LONG_TIMEOUT,
        )


class _Report(PerfUser):
    """A generated report document."""

    needs_admin = True
    wait_time = constant(1)
    format = "pdf"

    @task
    def report(self) -> None:
        self.client.post(f"{self.base}/reports", json={"format": self.format}, name=f"POST /projects/{{id}}/reports ({self.format})", timeout=LONG_TIMEOUT)


class ReportPdf(_Report):
    """A PDF report (peak memory is the risk)."""

    format = "pdf"


class ReportDocx(_Report):
    """A Word report."""

    format = "docx"


class BundleExport(PerfUser):
    """The full project export (structure and history) as a zip."""

    needs_admin = True
    wait_time = constant(1)

    @task
    def export(self) -> None:
        self.get(f"{self.base}/export", "GET /projects/{id}/export (bundle)", timeout=LONG_TIMEOUT)


class BundleImport(PerfUser):
    """Importing a project bundle into a new project (grows the data: each run adds a copy)."""

    needs_admin = True
    wait_time = constant(1)

    def on_start(self) -> None:
        super().on_start()
        self.bundle = self.client.get(f"{self.base}/export", name="setup: export", timeout=LONG_TIMEOUT).content

    @task
    def import_bundle(self) -> None:
        self.client.post(
            "/api/v1/projects/import", data={"organization_id": self.project["organization_id"], "name": f"Perf import {uuid.uuid4().hex[:8]}"},
            files={"file": ("bundle.zip", self.bundle, "application/zip")}, name="POST /projects/import (bundle)", timeout=LONG_TIMEOUT,
        )


class Attachment(PerfUser):
    """Uploading a file to a requirement."""

    wait_time = constant_throughput(0.5)

    def on_start(self) -> None:
        super().on_start()
        self.payload = random.Random(1).randbytes(ATTACHMENT_BYTES)

    @task
    def upload(self) -> None:
        self.client.post(
            f"{self.base}/requirements/{self.requirement_id()}/files", files={"file": (f"perf-{uuid.uuid4().hex[:6]}.bin", io.BytesIO(self.payload), "application/octet-stream")},
            name="POST /requirements/{id}/files (256 KB)", timeout=LONG_TIMEOUT,
        )


class ProjectScope(PerfUser):
    """A parent project's widened list and dashboard, which read every descendant's records."""

    needs_nested_root = True
    wait_time = constant_throughput(0.5)

    @task(2)
    def widened_list(self) -> None:
        self.get(f"{self.base}/requirements?project_scope=children&limit=50", "GET requirements (project_scope=children, page)", timeout=LONG_TIMEOUT)

    @task(1)
    def widened_dashboard(self) -> None:
        self.get(f"{self.base}/metrics?project_scope=children", "GET /projects/{id}/metrics (project_scope=children)", timeout=LONG_TIMEOUT)


class Soak(Browse):
    """A steady mix at a fixed request rate, to see whether memory keeps growing after warm-up."""

    wait_time = constant_throughput(1)

    @task(2)
    def search(self) -> None:
        with self.client.post(
            "/api/v1/search", json={"q": random.choice(SEARCH_WORDS), "scope": "project", "project_id": self.project["id"], "limit": 25},
            name="POST /search (project)", catch_response=True,
        ) as response:
            if response.status_code == 429:
                response.failure(THROTTLED)

    @task(1)
    def edit(self) -> None:
        with self.client.post(
            f"{self.base}/requirements", name="POST /projects/{id}/requirements (create)", catch_response=True,
            json={"name": f"Soak created {uuid.uuid4().hex[:8]}", "reasoning": "Soak.", "component_id": self.project["component_id"],
                  "category_id": self.project["category_id"], "keywords": []},
        ) as response:
            if response.status_code != 201:
                response.failure(f"{response.status_code}")


class Capacity(Browse, Edit):
    """How many people one stack serves: the browse mix plus writes (about one request in five), each simulated
    person issuing `CAPACITY_REQUESTS_PER_SECOND` (`perf/lib/catalog.py` names the same constant). The runner steps
    the number of people up until the stack saturates or starts failing; a real person makes a request every several
    seconds, so one simulated person stands for many."""

    wait_time = constant_throughput(1)

    def on_start(self) -> None:
        """As any scenario, plus a request timeout: a request the stack never answers is counted as a failure after
        `CAPACITY_TIMEOUT` seconds, so a stalled stack shows as failures instead of as no requests at all (Locust only
        counts a request when it finishes)."""
        super().on_start()
        request = self.client.request
        self.client.request = lambda method, url, **kwargs: request(method, url, **{"timeout": CAPACITY_TIMEOUT, **kwargs})


SCENARIOS: dict[str, type[PerfUser]] = {
    "browse": Browse,
    "list_unpaged": ListUnpaged,
    "list_filtered": ListFiltered,
    "search": Search,
    "links": Links,
    "edit": Edit,
    "export_csv": ExportCsv,
    "import_preview": ImportPreview,
    "report_pdf": ReportPdf,
    "report_docx": ReportDocx,
    "bundle_export": BundleExport,
    "bundle_import": BundleImport,
    "attachment": Attachment,
    "project_scope": ProjectScope,
    "soak": Soak,
    "capacity": Capacity,
}
