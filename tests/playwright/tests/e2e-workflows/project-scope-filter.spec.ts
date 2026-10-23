import { expect, type APIRequestContext, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: in a tree of projects, a person can widen a list to the parent and/or child
 * projects they can open, always sees which project a row comes from, and the choice is
 * remembered for that project (with a default they set in Preferences).
 *
 * Covers: no filter on a project with no relatives; the filter offered where there are relatives;
 * choosing parents adds the parent's rows, labelled and with the project code, linking to the
 * parent's own page, and read-only here (no bulk checkbox or reorder buttons); the choice survives
 * a reload and applies to that project only; the Preferences default applies to a project with no
 * choice of its own; a child-only member cannot see the parent's rows however they ask.
 *
 * Each test builds its own organisation, so none depends on state left by another test or run.
 */

const apiBaseUrl = "http://localhost:8000";
const SCOPE_LABEL = "Show records from";

interface Project {
  id: string;
  name: string;
  code: string;
  componentId: string;
  categoryId: string;
}

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
}

async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E Scope ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Scope Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  return { orgId: org.id, adminEmail, headers: { Authorization: `Bearer ${token}` } };
}

async function createProject(request: APIRequestContext, world: World, name: string, parentId?: string): Promise<Project> {
  const project = await (
    await request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: world.headers,
      data: { organization_id: world.orgId, name, summary: "", can_be_parent: true, ...(parentId ? { parent_project_id: parentId } : {}) },
    })
  ).json();
  const component = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, {
      headers: world.headers, data: { name: "Software", prefix: "SW" },
    })
  ).json();
  const category = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, {
      headers: world.headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
    })
  ).json();
  return { id: project.id, name, code: project.code, componentId: component.id, categoryId: category.id };
}

async function createRequirement(request: APIRequestContext, world: World, project: Project, name: string): Promise<{ id: string; code: string }> {
  const created = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/requirements`, {
      headers: world.headers,
      data: { name, reasoning: "e2e", component_id: project.componentId, category_id: project.categoryId, keywords: [] },
    })
  ).json();
  return { id: created.id, code: created.unique_code };
}

test.describe("list scope filter across nested projects", () => {
  test("a project with no relatives offers no scope filter", async ({ page }) => {
    const world = await createWorld(page.request, "flat");
    const lone = await createProject(page.request, world, `E2E Lone ${Date.now()}`);
    await createRequirement(page.request, world, lone, "Lonely requirement");

    await loginAs(page, world.adminEmail, PASSWORD);
    await page.goto(`/projects/${lone.id}/requirements`);

    await expect(page.getByRole("link", { name: "Lonely requirement" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: SCOPE_LABEL })).toHaveCount(0);
  });

  test("widening a child's list to its parent adds labelled, read-only rows that open in the parent, and is remembered", async ({ page }) => {
    const world = await createWorld(page.request, "widen");
    const parent = await createProject(page.request, world, `E2E Scope Parent ${Date.now()}`);
    const child = await createProject(page.request, world, `E2E Scope Child ${Date.now()}`, parent.id);
    const other = await createProject(page.request, world, `E2E Scope Other Child ${Date.now()}`, parent.id);
    const parentReq = await createRequirement(page.request, world, parent, "Parent-level requirement");
    await createRequirement(page.request, world, child, "Child-level requirement");

    await loginAs(page, world.adminEmail, PASSWORD);
    await page.goto(`/projects/${child.id}/requirements`);
    const scope = page.getByRole("combobox", { name: SCOPE_LABEL });

    await test.step("only this project's rows are listed to begin with, and the parent is offered", async () => {
      await expect(page.getByRole("link", { name: "Child-level requirement" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Parent-level requirement" })).toHaveCount(0);
      await expect(scope).toHaveValue("this");
      await expect(scope.getByRole("option", { name: "This + parent projects" })).toHaveCount(1);
      // The child has no children of its own, so those options are not offered.
      await expect(scope.getByRole("option", { name: "This + child projects" })).toHaveCount(0);
    });

    await test.step("choosing parents lists the parent's row, labelled, qualified and read-only", async () => {
      await page.getByRole("button", { name: "List view" }).click();
      await scope.selectOption({ label: "This + parent projects" });
      const parentLink = page.getByRole("link", { name: "Parent-level requirement" });
      await expect(parentLink).toBeVisible();
      const row = page.getByRole("row").filter({ has: parentLink });
      await expect(row).toContainText(`From ${parent.name}`);
      await expect(row).toContainText(`${parent.code}-${parentReq.code}`);
      await expect(row.getByRole("checkbox")).toHaveCount(0);
      await expect(row.getByRole("button", { name: "Move up" })).toHaveCount(0);
      await expect(page.getByText("Includes records from related")).toBeVisible();
      // A sibling project is never part of the scope.
      await expect(page.getByText(other.name)).toHaveCount(0);
    });

    await test.step("the row opens in the project it belongs to", async () => {
      await page.getByRole("link", { name: "Parent-level requirement" }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${parent.id}/requirements/${parentReq.id}$`));
    });

    await test.step("the choice is remembered for this project only", async () => {
      await page.goto(`/projects/${child.id}/requirements`);
      await expect(page.getByRole("combobox", { name: SCOPE_LABEL })).toHaveValue("parents");
      await expect(page.getByRole("link", { name: "Parent-level requirement" })).toBeVisible();
      await page.goto(`/projects/${other.id}/requirements`);
      await expect(page.getByRole("combobox", { name: SCOPE_LABEL })).toHaveValue("this");
    });

    await test.step("going back to this project drops the parent's rows", async () => {
      await page.goto(`/projects/${child.id}/requirements`);
      await page.getByRole("combobox", { name: SCOPE_LABEL }).selectOption({ label: "This project" });
      await expect(page.getByRole("link", { name: "Parent-level requirement" })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Child-level requirement" })).toBeVisible();
    });
  });

  test("the overview counts and the files list follow the same choice", async ({ page }) => {
    const world = await createWorld(page.request, "overview");
    const parent = await createProject(page.request, world, `E2E Overview Parent ${Date.now()}`);
    const child = await createProject(page.request, world, `E2E Overview Child ${Date.now()}`, parent.id);
    const parentReq = await createRequirement(page.request, world, parent, "Parent with a file");
    await createRequirement(page.request, world, child, "Child requirement");
    const upload = await page.request.post(`${apiBaseUrl}/api/v1/projects/${parent.id}/requirements/${parentReq.id}/files`, {
      headers: world.headers,
      multipart: { file: { name: "parent-spec.txt", mimeType: "text/plain", buffer: Buffer.from("spec") } },
    });
    expect(upload.status()).toBe(201);

    await loginAs(page, world.adminEmail, PASSWORD);
    await page.goto(`/projects/${child.id}`);
    const scope = page.getByRole("combobox", { name: SCOPE_LABEL });

    await test.step("the scope select sits in the title row, level with the New button, above nothing", async () => {
      const title = await page.getByRole("heading", { level: 1 }).boundingBox();
      const select = await scope.boundingBox();
      const button = await page.getByRole("link", { name: /^New requirement$/i }).boundingBox();
      expect(select!.x + select!.width).toBeLessThanOrEqual(button!.x + 1);
      expect(Math.abs((select!.y + select!.height / 2) - (button!.y + button!.height / 2))).toBeLessThan(button!.height);
      // Nothing is added between the title and the metric tiles by the scope control.
      expect(select!.y).toBeLessThan(title!.y + title!.height + button!.height);
    });

    await test.step("the overview counts only this project until widened, then says how many projects they cover", async () => {
      await expect(page.locator(".card", { hasText: "Total records" })).toContainText(/Requirements\s*1(?!\d)/);
      const saved = page.waitForResponse((r) => r.url().endsWith("/api/v1/auth/me/preferences") && r.request().method() === "PATCH");
      await scope.selectOption({ label: "This + parent projects" });
      expect((await saved).ok()).toBeTruthy();
      await expect(scope).toHaveAccessibleDescription(/Counts cover 2 projects/);
      await expect(scope).toHaveClass(/project-scope-select-widened/);
      // The explanation is a tooltip on hover and on keyboard focus.
      await scope.hover();
      await expect(page.getByRole("tooltip")).toContainText("Counts cover 2 projects");
      await page.mouse.move(0, 0);
      await scope.focus();
      await expect(page.getByRole("tooltip")).toContainText("Counts cover 2 projects");
      await expect(page.locator(".card", { hasText: "Total records" })).toContainText(/Requirements\s*2(?!\d)/);
    });

    await test.step("the files list shows the parent's file, labelled, once widened", async () => {
      await page.goto(`/projects/${child.id}/files`);
      await expect(page.getByRole("combobox", { name: SCOPE_LABEL })).toHaveValue("parents");
      const row = page.getByRole("row").filter({ hasText: "parent-spec.txt" });
      await expect(row).toContainText(`From ${parent.name}`);
      await expect(row.getByRole("link", { name: new RegExp(parentReq.code) })).toHaveAttribute(
        "href", new RegExp(`/projects/${parent.id}/requirements/${parentReq.id}$`),
      );
    });
  });

  test("the Preferences default applies to a project with no choice of its own", async ({ page }) => {
    const world = await createWorld(page.request, "default");
    const parent = await createProject(page.request, world, `E2E Default Parent ${Date.now()}`);
    const child = await createProject(page.request, world, `E2E Default Child ${Date.now()}`, parent.id);
    await createRequirement(page.request, world, parent, "Default parent requirement");

    await loginAs(page, world.adminEmail, PASSWORD);
    await page.goto("/preferences");
    // The choice is saved by a background request: wait for it before leaving the page.
    const saved = page.waitForResponse((r) => r.url().endsWith("/api/v1/auth/me/preferences") && r.request().method() === "PATCH");
    await page.getByRole("combobox", { name: "Default list scope" }).selectOption({ label: "This + parent and child projects" });
    expect((await saved).ok()).toBeTruthy();
    await expect(page.getByRole("combobox", { name: "Default list scope" })).toHaveValue("both");

    await page.goto(`/projects/${child.id}/requirements`);

    // "Both" degrades to what each project can offer: a child has a parent only, a parent has children only.
    await expect(page.getByRole("combobox", { name: SCOPE_LABEL })).toHaveValue("parents");
    await expect(page.getByRole("link", { name: "Default parent requirement" })).toBeVisible();
    await page.goto(`/projects/${parent.id}/requirements`);
    await expect(page.getByRole("combobox", { name: SCOPE_LABEL })).toHaveValue("children");
  });

  test("a member of the child only never sees the parent's rows", async ({ page }) => {
    const world = await createWorld(page.request, "limited");
    const parent = await createProject(page.request, world, `E2E Limited Parent ${Date.now()}`);
    const child = await createProject(page.request, world, `E2E Limited Child ${Date.now()}`, parent.id);
    await createRequirement(page.request, world, parent, "Hidden parent requirement");
    await createRequirement(page.request, world, child, "Visible child requirement");
    const email = `e2e-limited-member-${Date.now()}@example.com`;
    const created = await page.request.post(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/users`, {
      headers: world.headers, data: { email, display_name: "Child Member", password: PASSWORD, role: "member" },
    });
    expect(created.status()).toBe(201);
    const userId = (await created.json()).user_id;
    const granted = await page.request.post(`${apiBaseUrl}/api/v1/projects/${child.id}/roles`, {
      headers: world.headers, data: { user_id: userId, role: "member" },
    });
    expect(granted.ok()).toBeTruthy();

    await loginAs(page, email, PASSWORD);
    await page.goto(`/projects/${child.id}/requirements`);

    await expect(page.getByRole("link", { name: "Visible child requirement" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: SCOPE_LABEL })).toHaveCount(0);
    // Asking for the parent anyway still returns nothing from it.
    const token = (
      await (await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email, password: PASSWORD } })).json()
    ).access_token;
    const widened = await page.request.get(`${apiBaseUrl}/api/v1/projects/${child.id}/requirements?project_scope=parents`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect((await widened.json()).map((r: { name: string }) => r.name)).toEqual(["Visible child requirement"]);
  });
});
