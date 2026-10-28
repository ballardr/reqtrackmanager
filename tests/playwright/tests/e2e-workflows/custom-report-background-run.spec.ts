import crypto from "node:crypto";
import fs from "node:fs";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { chooseReport } from "./reportPicker";
import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a report too big to produce while waiting is prepared in the background; the person is told it
 * has started, is notified when it is ready, downloads it, and can delete the stored file. Nobody else can fetch it.
 *
 * A layout big enough to pass the synchronous limits would need ~100,000 records, so the test answers the
 * synchronous run with the same 409 the server sends for one; the queueing, the leader's job loop, the stored file,
 * the notification, the download rules and the deletion are all real. Each test works in its own disposable
 * organisation, so it passes alone, in any order and repeated.
 */
test.describe("Custom report background run", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-bg-report-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Background Report ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Background Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Atlas ${suffix}`, summary: "" } })).json();
    const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Hardware", prefix: "HW" } })).json();
    const category = await (await request.post(`${API}/projects/${project.id}/categories`, {
      headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
    })).json();
    const created = await request.post(`${API}/projects/${project.id}/requirements`, {
      headers, data: { name: `Requirement ${suffix}`, component_id: component.id, category_id: category.id },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const layoutName = `E2E Background layout ${suffix}`;
    const layout = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers,
      data: {
        name: layoutName, description: "E2E layout", family: "document",
        tree: {
          schema_version: 1, family: "document",
          nodes: [
            { type: "heading", text: "Requirements" },
            { type: "table", source: { record_type: "requirement" }, columns: [{ field: "code" }, { field: "title", label: "Name" }] },
          ],
        },
      },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();
    return { org, project, headers, layoutName, suffix };
  }

  test("a report too big to wait for is prepared in the background, downloaded by its requester and deleted", async ({ page, request }) => {
    const { project, headers, layoutName } = await setup(page, request);

    await test.step("a file run that is too big is queued instead, and the person is told", async () => {
      await page.route(/\/custom-reports\/[^/]+\/run\?.*format=pdf/, (route) =>
        route.fulfill({
          status: 409, contentType: "application/json",
          body: JSON.stringify({ detail: { code: "async_required", message: "Too big to produce while you wait." } }),
        }),
      );
      await page.goto(`/projects/${project.id}?reports=choose`);
      await chooseReport(page, layoutName);
      await page.getByRole("button", { name: "Export", exact: true }).click();
      await page.getByRole("button", { name: "Download PDF report" }).click();
      await expect(page.getByText(/being prepared in the background/)).toBeVisible();
    });

    const panel = page.getByRole("region", { name: "Background reports" });
    await test.step("the Background reports list shows it and, once the server has produced it, offers the file", async () => {
      await page.goto(`/projects/${project.id}?reports=runs`);
      await expect(panel.getByRole("row", { name: new RegExp(layoutName) })).toBeVisible();
      await expect(panel.getByText("Ready")).toBeVisible({ timeout: 60_000 });
    });

    await test.step("the person was notified", async () => {
      // The notification is written just after the run is marked ready.
      await expect
        .poll(async () => {
          const notifications = await (await request.get(`${API}/notifications`, { headers })).json();
          return notifications.map((n: { title: string }) => n.title);
        })
        .toContain(`Report ready: ${layoutName}`);
    });

    await test.step("the stored file is a real PDF", async () => {
      const pending = page.waitForEvent("download");
      await panel.getByRole("button", { name: `Download ${layoutName}` }).click();
      const file = await pending;
      expect(fs.readFileSync((await file.path())!).subarray(0, 5).toString()).toBe("%PDF-");
    });

    await test.step("nobody else can fetch it", async () => {
      const runs = await (await request.get(`${API}/report-runs`, { headers })).json();
      expect(runs).toHaveLength(1);
      const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
      expect((await request.get(`${API}/report-runs/${runs[0].id}/download`, { headers: serverHeaders })).status()).toBe(404);
      expect((await request.get(`${API}/report-runs`, { headers: serverHeaders })).status()).toBe(200);
    });

    await test.step("deleting the stored file asks first and leaves the run listed as expired", async () => {
      await panel.getByRole("button", { name: `Delete file ${layoutName}` }).click();
      await page.getByRole("dialog", { name: "Delete file" }).getByRole("button", { name: "Delete file" }).click();
      await expect(page.getByText("The report file was deleted.")).toBeVisible();
      await expect(panel.getByText("Expired")).toBeVisible();
      await expect(panel.getByRole("button", { name: `Download ${layoutName}` })).toHaveCount(0);
    });

  });

  test("an organisation admin sets how long background report files are kept", async ({ page, request }) => {
    const { org } = await setup(page, request);

    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Templates & reports");
    await ensureExpanded(page, "Background reports");
    await expect(page.getByText(/platform default of 7 days/)).toBeVisible();
    await page.getByLabel("Keep background report files for (days)").fill("3");
    await page.getByRole("button", { name: "Save background report settings" }).click();

    await expect(page.getByText("Settings saved.")).toBeVisible();
    await page.reload();
    await selectOrgAdminGroup(page, "Templates & reports");
    await ensureExpanded(page, "Background reports");
    await expect(page.getByLabel("Keep background report files for (days)")).toHaveValue("3");
  });
});
