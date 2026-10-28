import crypto from "node:crypto";
import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { chooseListAction } from "../listActions";
import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: from a record list, take away a report that is about those records, without going to the Reports
 * page and without being offered reports about something else.
 *
 * The test works in its own disposable organisation with uniquely named layouts, so it passes alone, in any order
 * and repeated.
 */
test.describe("Download report from a record list", () => {
  installCleanupHook();

  const source = (record_type: string) => ({ type: "table", source: { record_type }, columns: [{ field: "code" }] });
  const layout = (record_type: string) => ({
    schema_version: 1, family: "document", nodes: [{ type: "heading", text: "Report" }, source(record_type)],
  });

  test("the Requirements list offers only the reports that use requirements, and downloads one", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-list-report-${suffix}@example.com`;
    const login = async (email: string, password: string) => {
      const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
      return { Authorization: `Bearer ${(await resp.json()).access_token}` };
    };
    const serverHeaders = await login("admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E List Report ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E List Report Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, {
      headers, data: { organization_id: org.id, name: `List report ${suffix}`, summary: "" },
    })).json();
    const forRequirements = `E2E Requirements layout ${suffix}`;
    const forOthers = `E2E Change requests layout ${suffix}`;
    for (const [name, recordType, folder] of [[forRequirements, "requirement", "Specs"], [forOthers, "change_request", "Work"]]) {
      const created = await request.post(`${API}/projects/${project.id}/report-layouts`, {
        headers, data: { name, description: "E2E layout", family: "document", folder, tree: layout(recordType) },
      });
      expect(created.ok(), await created.text()).toBeTruthy();
    }

    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await chooseListAction(page, "Download report");
    const dialog = page.getByRole("dialog", { name: "Download report" });

    await test.step("only the report that reads requirements is listed, in its folder, which starts collapsed", async () => {
      await expect(dialog.getByRole("button", { name: "Expand Specs" })).toBeVisible();
      await expect(dialog.getByRole("button", { name: new RegExp(`^${forRequirements}`) })).toHaveCount(0);
      await dialog.getByRole("button", { name: "Expand Specs" }).click();
      await expect(dialog.getByRole("button", { name: new RegExp(`^${forRequirements}`) })).toBeVisible();
      await expect(dialog.getByText(forOthers)).toHaveCount(0);
    });

    await test.step("the chosen report is run and downloads as a PDF", async () => {
      await dialog.getByRole("button", { name: new RegExp(`^${forRequirements}`) }).click();
      await dialog.getByRole("button", { name: "Export", exact: true }).click();
      const pending = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download PDF report" }).click();
      expect(fs.readFileSync((await (await pending).path())!).subarray(0, 5).toString()).toBe("%PDF-");
    });

    await test.step("Choose another report returns to the list, with the folder still open", async () => {
      await dialog.getByRole("button", { name: "Choose another report" }).click();
      await expect(dialog.getByRole("button", { name: new RegExp(`^${forRequirements}`) })).toBeVisible();
    });
  });
});
