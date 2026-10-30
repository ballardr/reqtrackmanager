import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, searchReportSetup, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";
/** A 1 x 1 pixel PNG. */
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

/**
 * Job to be done: start a new report from one that already exists (a shared layout, a built-in starter, or one of the
 * project's own) without retyping it, and share a project's layout with the whole organisation only when it carries
 * nothing private to the project.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Duplicate a report", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with an admin and a project; the page is left logged in as the admin on the project's Report setup. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-duplicate-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Duplicate ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Duplicate Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Duplicate project ${suffix}`, summary: "" } })).json();
    return { org, headers, project, suffix };
  }

  async function createLayout(request: APIRequestContext, headers: Record<string, string>, base: string, name: string, body: object = {}) {
    const parsed = await (await request.post(`${base}/report-layouts/text/parse`, { headers, data: { text: "@layout document\n" } })).json();
    const tree = { ...parsed.tree, ...body };
    const created = await request.post(`${base}/report-layouts`, { headers, data: { name, description: "", family: "document", tree } });
    expect(created.ok(), await created.text()).toBeTruthy();
    return created.json();
  }

  async function openSetup(page: Page, projectId: string) {
    await page.goto(`/projects/${projectId}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
  }

  test("a shared layout is duplicated into the project as its own editable copy", async ({ page, request }) => {
    const { org, headers, project, suffix } = await setup(page, request);
    const name = `E2E shared ${suffix}`;
    await createLayout(request, headers, `${API}/orgs/${org.id}`, name);
    await openSetup(page, project.id);

    const grid = await searchReportSetup(page, name);
    await grid.getByRole("button", { name: `Actions for ${name}` }).click();
    await page.getByRole("menuitem", { name: "Duplicate…" }).click();
    const dialog = page.getByRole("dialog", { name: "Duplicate layout" });
    await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue(`${name} (copy)`);
    await expect(dialog.getByRole("combobox", { name: "Copy into" })).toHaveValue("project");
    await dialog.getByRole("button", { name: "Create copy" }).click();

    await expect(page.getByRole("heading", { name: `${name} (copy)` })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Layout text" })).not.toHaveAttribute("readonly", "");
  });

  test("a built-in starter starts a new layout, and a taken name is refused before anything is created", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await openSetup(page, project.id);

    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New from a starter…" }).click();
    const dialog = page.getByRole("dialog", { name: "New layout from a starter" });
    await expect(dialog.getByRole("button", { name: "Create copy" })).toBeDisabled();
    await dialog.getByRole("combobox", { name: "Starter" }).selectOption({ label: "Review Package" });
    const name = dialog.getByRole("textbox", { name: "Name" });
    await expect(name).not.toHaveValue("");
    const own = `Starter based ${suffix}`;
    await name.fill(own);
    await dialog.getByRole("button", { name: "Create copy" }).click();
    await expect(page.getByRole("heading", { name: own })).toBeVisible();

    await page.getByRole("button", { name: "Report layouts" }).click();
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New from a starter…" }).click();
    const again = page.getByRole("dialog", { name: "New layout from a starter" });
    await again.getByRole("combobox", { name: "Starter" }).selectOption({ label: "Review Package" });
    await again.getByRole("textbox", { name: "Name" }).fill(own);
    await expect(again.getByRole("alert")).toContainText("already exists here");
    await expect(again.getByRole("button", { name: "Create copy" })).toBeDisabled();
  });

  test("copying a project layout up to the organisation is refused while it uses a project picture", async ({ page, request }) => {
    const { org, headers, project, suffix } = await setup(page, request);
    const fileName = `plan-${suffix}.png`;
    const uploaded = await (await request.post(`${API}/projects/${project.id}/report-images`, {
      headers, multipart: { file: { name: fileName, mimeType: "image/png", buffer: PIXEL } },
    })).json();
    const name = `E2E private picture ${suffix}`;
    await createLayout(request, headers, `${API}/projects/${project.id}`, name, {
      nodes: [{ type: "image", file: uploaded.id, alt: "A plan" }],
    });
    await openSetup(page, project.id);

    const grid = await searchReportSetup(page, name);
    await grid.getByRole("button", { name: `Actions for ${name}` }).click();
    await page.getByRole("menuitem", { name: "Duplicate…" }).click();
    const dialog = page.getByRole("dialog", { name: "Duplicate layout" });
    await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue(`${name} (copy)`);
    await dialog.getByRole("combobox", { name: "Copy into" }).selectOption({ label: "The organisation (shared with every project)" });
    await expect(dialog.getByRole("alert")).toContainText(fileName);
    await expect(dialog.getByRole("button", { name: "Create copy" })).toBeDisabled();

    await dialog.getByRole("combobox", { name: "Copy into" }).selectOption({ label: "This project" });
    await expect(dialog.getByRole("button", { name: "Create copy" })).toBeEnabled();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    const orgLayouts = await (await request.get(`${API}/orgs/${org.id}/report-layouts`, { headers })).json();
    expect(orgLayouts.map((l: { name: string }) => l.name)).not.toContain(`${name} (copy)`);
  });
});
