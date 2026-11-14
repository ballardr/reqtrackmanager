import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an architect takes the project's architecture out as a JSON file and as a Structurizr workspace, and
 * brings the JSON file back into a project. The import shows what it will add before anything is stored.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture switched on. Two elements and a connection are
 * created through the API; the exports and the import are driven through the Interchange menu on the Elements tab.
 */
test.describe("System Architecture: interchange", () => {
  test("the architecture is exported as JSON and Structurizr, and the JSON file is previewed and imported", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchInterchange", false, "System Architecture");
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${base}/element-types`, { headers: adminHeaders })).json();
    const connectionTypes = await (await page.request.get(`${base}/connection-types`, { headers: adminHeaders })).json();
    const element = async (name: string) => {
      const created = await page.request.post(`${base}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, activate: true } });
      expect(created.ok(), await created.text()).toBeTruthy();
      return created.json();
    };
    const gateway = await element(`Gateway ${suffix}`);
    const store = await element(`Store ${suffix}`);
    const link = await page.request.post(`${base}/connections`, {
      headers: adminHeaders,
      data: { connection_type_id: connectionTypes[0].id, source_element_id: gateway.id, target_element_id: store.id, activate: true },
    });
    expect(link.ok(), await link.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture?tab=elements`);
    const interchange = page.getByRole("button", { name: "Interchange" });

    let jsonPath = "";
    await test.step("the JSON file holds the elements and the connection", async () => {
      await interchange.click();
      const download = page.waitForEvent("download");
      await page.getByRole("menuitem", { name: "Export JSON file" }).click();
      jsonPath = await (await download).path();
      const document = JSON.parse(await readFile(jsonPath, "utf8"));
      expect(document.format).toBe("reqtrack-architecture");
      expect(document.data.architecture_elements.map((e: { name: string }) => e.name)).toEqual([`Gateway ${suffix}`, `Store ${suffix}`]);
      expect(document.data.architecture_connections).toHaveLength(1);
    });

    await test.step("the Structurizr file is a workspace naming both elements", async () => {
      await interchange.click();
      const download = page.waitForEvent("download");
      await page.getByRole("menuitem", { name: "Export Structurizr DSL" }).click();
      const text = await readFile(await (await download).path(), "utf8");
      expect(text).toContain("workspace");
      expect(text).toContain(`Gateway ${suffix}`);
      expect(text).toContain("->");
    });

    await test.step("importing the file previews it first and then adds copies", async () => {
      await interchange.click();
      await page.getByRole("menuitem", { name: "Import JSON file…" }).click();
      const dialog = page.getByRole("dialog", { name: "Import JSON file" });
      await expect(dialog.getByRole("button", { name: "Import" })).toBeDisabled();
      await dialog.getByLabel("File").setInputFiles(jsonPath);
      await expect(dialog.getByRole("row", { name: /Elements\s*2/ })).toBeVisible();
      await expect(dialog.getByRole("row", { name: /Connections\s*1/ })).toBeVisible();
      const imported = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith("/interchange/json") && r.ok());
      await dialog.getByRole("button", { name: "Import" }).click();
      await imported;
      await expect(page.getByText("Imported 3 records.")).toBeVisible();
      await expect(page.getByRole("cell", { name: `Gateway ${suffix}`, exact: true })).toHaveCount(2);
    });
  });
});
