import crypto from "node:crypto";
import fs from "node:fs";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { chooseReport } from "./reportPicker";
import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a report too big to produce while waiting is prepared in the background; the person is told it
 * has started, sees it in the top bar while it is prepared, is notified when it is ready, opens it from the
 * notification, downloads it, and can generate it again once the file has been removed. Nobody else can fetch it.
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

  test("a report too big to wait for is prepared in the background, opened from its notification, downloaded and generated again", async ({ page, request }) => {
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

    await test.step("the Reports button opens the chooser directly, with no background-reports view", async () => {
      await page.goto(`/projects/${project.id}`);
      await page.getByRole("button", { name: "Reports", exact: true }).click();
      await expect(page.getByRole("dialog", { name: "Reports" })).toBeVisible();
      await expect(page.getByRole("menuitem")).toHaveCount(0);
      await page.keyboard.press("Escape");
    });

    await test.step("the person was notified once the server produced it", async () => {
      // The notification is written just after the run is marked ready.
      await expect
        .poll(async () => {
          const notifications = await (await request.get(`${API}/notifications`, { headers })).json();
          return notifications.map((n: { title: string }) => n.title);
        }, { timeout: 60_000 })
        .toContain(`Report ready: ${layoutName}`);
    });

    await test.step("clicking the notification opens the report and downloads a real PDF", async () => {
      await page.goto(`/projects/${project.id}`);
      await page.getByRole("button", { name: "Notifications", exact: true }).click();
      await page.getByText(`Report ready: ${layoutName}`).click();
      const dialog = page.getByRole("dialog", { name: layoutName });
      await expect(dialog.getByText("Ready", { exact: true })).toBeVisible();
      const pending = page.waitForEvent("download");
      await dialog.getByRole("button", { name: "Download", exact: true }).click();
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

    await test.step("once the file is removed the same link says so and generates the report again", async () => {
      const [run] = await (await request.get(`${API}/report-runs`, { headers })).json();
      expect((await request.delete(`${API}/report-runs/${run.id}`, { headers })).ok()).toBeTruthy();
      await page.goto(`/report-runs/${run.id}`);
      const dialog = page.getByRole("dialog", { name: layoutName });
      await expect(dialog.getByText(/removed after its retention period/)).toBeVisible();
      await dialog.getByRole("button", { name: "Generate again" }).click();
      await expect(dialog.getByText(/fresh run of this report has been queued/)).toBeVisible();
      await expect
        .poll(async () => {
          const runs = await (await request.get(`${API}/report-runs`, { headers })).json();
          return runs.filter((r: { status: string }) => r.status === "ready").length;
        }, { timeout: 60_000 })
        .toBe(1);
      const runs = await (await request.get(`${API}/report-runs`, { headers })).json();
      expect(runs).toHaveLength(2);
      expect(runs.map((r: { id: string }) => r.id)).toContain(run.id);
    });
  });

  test("a failed background report shows its reason and offers to generate it again", async ({ page, request }) => {
    const { project, layoutName } = await setup(page, request);
    const run = {
      id: "00000000-0000-4000-8000-000000000001", organization_id: "x", project_id: project.id, scope: "project",
      layout_name: layoutName, layout_version: 1, format: "pdf", status: "failed", created_at: "2026-10-29T01:00:00Z",
      started_at: "2026-10-29T01:00:05Z", finished_at: "2026-10-29T01:01:00Z", expires_at: null, output_filename: null,
      output_size: null, error: "The report took too long to produce. Narrow the layout or select fewer projects.",
    };
    await page.route(`**/api/v1/report-runs/${run.id}`, (route) => route.fulfill({ json: run }));

    await page.goto(`/report-runs/${run.id}`);

    const dialog = page.getByRole("dialog", { name: layoutName });
    await expect(dialog.getByRole("alert")).toContainText("The report took too long to produce.");
    await expect(dialog.getByRole("button", { name: "Generate again" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Download", exact: true })).toHaveCount(0);
  });

  test("the top bar shows the reports still being prepared and hides when there are none", async ({ page, request }) => {
    const { project } = await setup(page, request);
    let active: unknown[] = [];
    await page.route(/\/api\/v1\/report-runs\?active=true/, (route) => route.fulfill({ json: active }));

    await page.goto(`/projects/${project.id}`);
    await expect(page.getByRole("button", { name: /being prepared/ })).toHaveCount(0);

    active = [{
      id: "00000000-0000-4000-8000-000000000002", organization_id: "x", project_id: project.id, scope: "project",
      layout_name: "Quarterly review", layout_version: 1, format: "docx", status: "running", created_at: "2026-10-29T01:00:00Z",
      started_at: "2026-10-29T01:00:05Z", finished_at: null, expires_at: null, output_filename: null, output_size: null, error: null,
    }];
    await page.evaluate(() => window.dispatchEvent(new Event("reqtrack:report-run-queued")));
    await page.getByRole("button", { name: "1 report being prepared" }).click();
    const popover = page.getByRole("dialog", { name: "Reports being prepared" });
    await expect(popover.getByText("Quarterly review")).toBeVisible();
    await expect(popover.getByRole("button")).toHaveCount(0);
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
