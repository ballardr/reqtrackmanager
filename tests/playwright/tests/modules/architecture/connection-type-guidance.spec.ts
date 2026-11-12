import { expect, test } from "@playwright/test";

import { installCleanupHook, selectOptionContaining, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/**
 * Job to be done: an architect wants the connection picker to offer sensible choices first without forbidding the
 * unusual. An element type names the connection types it suggests; a connection between two hardware elements lists the
 * suggestion first and hides software-only types until "Show all types"; a type that does not fit is allowed, with a
 * warning.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture switched on; the two elements are created
 * through the API (they are not what is under test), the element type and the connections through the UI.
 */
test.describe("System Architecture: soft guidance for connection types", () => {
  test("an element type suggests a connection type, the picker lists it first and a mismatch warns but saves", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchTypeGuide", false, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const radio = `Radio module ${suffix}`;

    await test.step("add a hardware element type that suggests UART", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Element Types", "System Architecture");
      await page.getByRole("button", { name: "New element type with details" }).click();
      const dialog = page.getByRole("dialog", { name: "New element type" });
      await dialog.getByLabel("Name", { exact: true }).fill(radio);
      await dialog.getByLabel("Domain", { exact: true }).selectOption({ label: "Hardware" });
      await dialog.getByRole("button", { name: "Suggested connection types", exact: true }).click();
      const tree = page.getByRole("group", { name: "Suggested connection types" });
      await tree.getByRole("checkbox", { name: "UART", exact: true }).check();
      await page.keyboard.press("Escape");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Element type created.")).toBeVisible();
    });

    const names = [`Transmitter ${suffix}`, `Receiver ${suffix}`];
    await test.step("two elements of that type", async () => {
      const types = await (await page.request.get(`${base}/element-types`, { headers: adminHeaders })).json();
      const type = types.find((t: { name: string }) => t.name === radio);
      for (const name of names) {
        const res = await page.request.post(`${base}/elements`, { headers: adminHeaders, data: { name, element_type_id: type.id, activate: true } });
        expect(res.ok(), await res.text()).toBeTruthy();
      }
    });

    await test.step("the picker follows the suggestion and hides the types that do not fit", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/connections`);
      await page.getByRole("button", { name: "New connection" }).click();
      const dialog = page.getByRole("dialog", { name: "New connection" });
      await selectOptionContaining(dialog.getByLabel("Source element"), names[0]);
      await selectOptionContaining(dialog.getByLabel("Target element"), names[1]);
      const picker = dialog.getByRole("button", { name: "Connection type", exact: true });
      await expect(picker).toContainText("UART");
      await expect(dialog.getByText(/\d+ hidden/)).toBeVisible();
      await picker.click();
      const list = page.getByRole("group", { name: "Connection type" });
      await expect(list.getByRole("radio", { name: "Suggested", exact: true })).toBeVisible();
      await expect(list.getByRole("radio", { name: "REST API", exact: true })).toHaveCount(0);
      await page.keyboard.press("Escape");
    });

    await test.step("show every type, choose one that does not fit and save it with the warning", async () => {
      const dialog = page.getByRole("dialog", { name: "New connection" });
      await dialog.getByRole("switch", { name: "Show all types" }).click();
      await dialog.getByRole("button", { name: "Connection type", exact: true }).click();
      await page.getByRole("searchbox", { name: "Search Connection type" }).fill("rest");
      await page.getByRole("radio", { name: "REST API", exact: true }).first().click();
      await expect(dialog.getByRole("status")).toContainText("REST API is a software connection type");
      await expect(dialog.getByRole("status")).toContainText("The connection can still be saved.");
      await dialog.getByRole("button", { name: "Save and activate" }).click();
      await expect(page.getByText("Connection created.")).toBeVisible();
      await expect(page.locator("tr", { hasText: names[1] }).getByText("REST API", { exact: true })).toBeVisible();
    });
  });
});
