import { expect, test, type Page } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an author writes the introduction, chapters and appendices
 * of each report type separately, at three levels (organisation defaults, a
 * report template, a project), and a project with nothing of its own inherits
 * its parent project's, then the organisation's — with the editor saying where
 * each blank field comes from.
 *
 * Runs in a disposable organisation (nothing here edits shared seed data), with
 * a parent and a child project.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";
const apiBaseUrl = "http://localhost:8000";

async function api(page: Page, token: string, method: "get" | "post" | "put", path: string, data?: unknown) {
  const resp = await page.request[method](`${apiBaseUrl}${path}`, { headers: { Authorization: `Bearer ${token}` }, data });
  expect(resp.ok(), `${method.toUpperCase()} ${path}: ${resp.status()} ${await resp.text()}`).toBe(true);
  return resp;
}

async function login(page: Page, email: string, password: string): Promise<string> {
  const resp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email, password } });
  return (await resp.json()).access_token;
}

test("report content is written per report type and inherited from parent projects and the organisation", async ({ page }) => {
  const suffix = Date.now();
  const adminToken = await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  const orgName = `E2E Report Content Org ${suffix}`;
  const org = await (await api(page, adminToken, "post", "/api/v1/orgs", { name: orgName })).json();
  deleteOrgOnCleanup({ id: org.id });
  const email = `e2e-reportcontent-${suffix}@example.com`;
  await api(page, adminToken, "post", `/api/v1/orgs/${org.id}/users`, {
    email, display_name: "Report Content Admin", password: "OrgAdmin123!", role: "org_admin",
  });
  const token = await login(page, email, "OrgAdmin123!");
  const parentName = `E2E Report Parent ${suffix}`;
  const parent = await (
    await api(page, token, "post", "/api/v1/projects", { organization_id: org.id, name: parentName, summary: "", can_be_parent: true })
  ).json();
  const child = await (
    await api(page, token, "post", "/api/v1/projects", {
      organization_id: org.id, name: `E2E Report Child ${suffix}`, summary: "", parent_project_id: parent.id,
    })
  ).json();
  // The report types the editors offer come from the server (the requirements report and each enabled
  // module's reports), so the spec compares against them rather than hard-coding a module's report.
  const reportTypes: { key: string; title: string }[] = await (await api(page, token, "get", `/api/v1/orgs/${org.id}/report-types`)).json();

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("OrgAdmin123!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await test.step("organisation defaults: a drop-down of report types, saved per type", async () => {
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Templates & reports");
    await ensureExpanded(page, "Report Defaults");
    const defaults = page.locator(".card", { has: page.getByRole("button", { name: "Report Defaults section" }) });
    const options = await defaults.getByLabel("Report type").locator("option").allTextContents();
    expect(options).toEqual(["All reports", ...reportTypes.map((t) => t.title)]);

    await defaults.getByLabel("Report type").selectOption("requirements");
    await defaults.locator("textarea").first().fill("Org intro for {{project_name}} at {{organisation}}");
    await defaults.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText("Report defaults saved.")).toBeVisible();

    await page.reload();
    await selectOrgAdminGroup(page, "Templates & reports");
    await ensureExpanded(page, "Report Defaults");
    await defaults.getByLabel("Report type").selectOption("requirements");
    await expect(defaults.locator("textarea").first()).toHaveValue(/^Org intro for \{\{project_name\}\}/);
    // Another report type has no content of its own.
    await defaults.getByLabel("Report type").selectOption("*");
    await expect(defaults.getByText(/Content set for: Requirements report\./)).toBeVisible();
  });

  await test.step("the child project inherits the organisation default and names its source", async () => {
    await page.goto(`/projects/${child.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    await page.getByLabel("Report type").selectOption("requirements");
    await expect(page.getByText(`Organisation default (${orgName})`).first()).toBeVisible();
    await expect(page.getByRole("note", { name: "Inherited content" }).first()).toContainText("Org intro for {{project_name}}");
  });

  await test.step("a parent project's content beats the organisation's for its children", async () => {
    await api(page, token, "put", `/api/v1/projects/${parent.id}/report-config`, {
      content: [{
        report_key: "requirements", intro: `Parent intro for {{project_name}}`,
        chapters: [{ title: "Parent chapter", body: "Shared by every child." }], appendices: [],
      }],
    });
    await page.goto(`/projects/${child.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    await page.getByLabel("Report type").selectOption("requirements");
    await expect(page.getByText(`Inherited from ${parentName}`).first()).toBeVisible();
    await expect(page.getByRole("note", { name: "Inherited content" }).filter({ hasText: "Parent chapter" })).toBeVisible();
    // The appendices still come from nowhere, and the introduction from the parent.
    await expect(page.getByText("Nothing is inherited, so the report prints none.")).toBeVisible();
  });

  await test.step("the generation page shows the content the server resolves, placeholders still unfilled", async () => {
    await page.goto(`/projects/${child.id}/reports`);
    await ensureExpanded(page, "Introduction");
    await expect(page.locator("textarea").first()).toHaveValue("Parent intro for {{project_name}}");
  });

  await test.step("the child's own content wins, and 'Use inherited' gives it back", async () => {
    await page.goto(`/projects/${child.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    await page.getByLabel("Report type").selectOption("requirements");
    await page.locator("textarea").first().fill("Child's own introduction");
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/report-config") && r.request().method() === "PUT"),
      page.getByRole("button", { name: "Save settings" }).click(),
    ]);
    await expect(page.getByText("Report setup saved.")).toBeVisible();
    await page.reload();
    await selectProjectAdminGroup(page, "Report Setup");
    await page.getByLabel("Report type").selectOption("requirements");
    await expect(page.locator("textarea").first()).toHaveValue("Child's own introduction");
    await page.getByRole("button", { name: "Use inherited" }).first().click();
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/report-config") && r.request().method() === "PUT"),
      page.getByRole("button", { name: "Save settings" }).click(),
    ]);
    const saved = await (await api(page, token, "get", `/api/v1/projects/${child.id}/report-config`)).json();
    expect(saved.content).toEqual([]);
  });

  await test.step("a report template carries its own content per type and wins when selected", async () => {
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Templates & reports");
    await ensureExpanded(page, "Report templates");
    await page.getByRole("button", { name: "New template" }).click();
    const dialog = page.getByRole("dialog", { name: "New template" });
    await dialog.getByLabel("Name", { exact: true }).fill(`E2E Content Template ${suffix}`);
    await dialog.getByLabel("Report type").selectOption("requirements");
    await dialog.locator("textarea").first().fill("Template intro");
    await dialog.getByRole("button", { name: "Create", exact: true }).click();
    await expect(dialog).not.toBeVisible();

    await page.goto(`/projects/${child.id}/reports`);
    await ensureExpanded(page, "Template & layout");
    await page.getByLabel("Report template").selectOption({ label: `E2E Content Template ${suffix}` });
    await ensureExpanded(page, "Introduction");
    await expect(page.locator("textarea").first()).toHaveValue("Template intro");
  });

  await test.step("a report still generates from the resolved content", async () => {
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Generate PDF" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  });
});
