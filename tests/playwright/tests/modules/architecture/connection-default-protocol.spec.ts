import { expect, test, type Locator, type Page } from "@playwright/test";

import { installCleanupHook, selectOptionContaining, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** Chooses `name` in the connection type tree of an open dialog, searching for it first. */
async function chooseType(page: Page, dialog: Locator, name: string, search: string) {
  await dialog.getByRole("button", { name: "Connection type", exact: true }).click();
  await page.getByRole("searchbox", { name: "Search Connection type" }).fill(search);
  await page.getByRole("radio", { name, exact: true }).first().click();
  await expect(dialog.getByRole("button", { name: "Connection type", exact: true })).toContainText(name);
}

/**
 * Job to be done: an engineer who draws many SPI links sets "SPI mode 0" once on the connection type, so a new connection of
 * that type starts with it (and can still be given another protocol), and a diagram with Connection detail on writes it beside
 * the line without each connection being filled in by hand.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the two elements are created through the API
 * (not what is under test), the type default, the connections and the edit through the UI.
 */
test.describe("System Architecture: a connection type's default protocol", () => {
  test("a new connection starts with the type's default, a changed type follows it and a typed protocol is kept", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchProto", false, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementTypes = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
    const ids: string[] = [];
    for (const name of [`Sensor ${suffix}`, `Gateway ${suffix}`]) {
      const res = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: elementTypes[0].id, activate: true } });
      expect(res.ok(), await res.text()).toBeTruthy();
      ids.push((await res.json()).id);
    }
    const typeName = `Sensor bus ${suffix}`;

    await test.step("set a default protocol on a new connection type; the list shows it", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Connection Types", "System Architecture");
      await page.getByRole("button", { name: "New connection type with details" }).click();
      const dialog = page.getByRole("dialog", { name: "New connection type" });
      await dialog.getByLabel("Name", { exact: true }).fill(typeName);
      await dialog.getByLabel("Default protocol", { exact: true }).fill("SPI mode 0");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Connection type created.")).toBeVisible();
      await expect(page.getByText(/default protocol SPI mode 0/)).toBeVisible();
    });

    await test.step("a new connection of that type starts with the default and stores it", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/connections`);
      await page.getByRole("button", { name: "New connection" }).click();
      const dialog = page.getByRole("dialog", { name: "New connection" });
      await selectOptionContaining(dialog.getByLabel("Source element"), `Sensor ${suffix}`);
      await selectOptionContaining(dialog.getByLabel("Target element"), `Gateway ${suffix}`);
      await chooseType(page, dialog, typeName, "sensor bus");
      await expect(dialog.getByLabel("Protocol", { exact: true })).toHaveValue("SPI mode 0");
      await dialog.getByRole("button", { name: "Save and activate" }).click();
      await expect(page.getByText("Connection created.")).toBeVisible();
      await expect(page.locator("tr", { hasText: `Gateway ${suffix}` }).getByText("SPI mode 0", { exact: true })).toBeVisible();
    });

    await test.step("a diagram with Connection detail on writes the protocol beside the line", async () => {
      const made = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Links ${suffix}`, activate: true, connection_detail: true } });
      expect(made.ok(), await made.text()).toBeTruthy();
      const diagram = await made.json();
      const laid = await page.request.put(`${arch}/diagrams/${diagram.id}/layout`, {
        headers: adminHeaders,
        data: { version: diagram.version, notes: [], placements: [{ element_id: ids[0], x: 0, y: 0 }, { element_id: ids[1], x: 500, y: 0 }] },
      });
      expect(laid.ok(), await laid.text()).toBeTruthy();
      await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
      await expect(page.getByLabel(`Gateway ${suffix}, node`, { exact: true })).toBeVisible();
      await expect(page.getByText(`${typeName} · SPI mode 0`, { exact: true })).toBeVisible();
    });

    await test.step("editing keeps a typed protocol when the type changes, and follows the type while it is a default", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/connections`);
      await page.locator("tr", { hasText: `Gateway ${suffix}` }).getByRole("link", { name: /CON-001/ }).click();
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByLabel("Protocol", { exact: true })).toHaveValue("SPI mode 0");
      await dialog.getByLabel("Protocol", { exact: true }).fill("SPI mode 3, 8 MHz");
      await chooseType(page, dialog, "REST API", "rest");
      await expect(dialog.getByLabel("Protocol", { exact: true })).toHaveValue("SPI mode 3, 8 MHz");
      await chooseType(page, dialog, typeName, "sensor bus");
      await expect(dialog.getByLabel("Protocol", { exact: true })).toHaveValue("SPI mode 3, 8 MHz");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Connection updated.")).toBeVisible();
    });

    await test.step("changing the default later leaves the stored connection alone", async () => {
      const types = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
      const kind = types.find((t: { name: string }) => t.name === typeName);
      const patched = await page.request.patch(`${arch}/connection-types/${kind.id}`, { headers: adminHeaders, data: { default_protocol: "SPI mode 1" } });
      expect(patched.ok(), await patched.text()).toBeTruthy();
      const connections = await (await page.request.get(`${arch}/connections`, { headers: adminHeaders })).json();
      expect(connections[0].protocol).toBe("SPI mode 3, 8 MHz");
    });
  });
});
