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
  // Choosing closes the list, so the radio is gone before a check could be read back: click it.
  await page.getByRole("radio", { name, exact: true }).first().click();
  await expect(dialog.getByRole("button", { name: "Connection type", exact: true })).toContainText(name);
}

/**
 * Job to be done: an engineer starts a hardware connection as "some form of serial link" and refines it to I2C after
 * the detailed design, and finds both by filtering on the group. Connection types form a tree (a type may sit under
 * several groups) and a group is itself a usable type.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture switched on; the three elements are created
 * through the API (they are not what is under test), everything about the types and the connections through the UI.
 */
test.describe("System Architecture: the connection type tree", () => {
  test("a connection starts on a group, is refined to a member and is found by filtering on the group", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchTypeTree", false, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementTypes = await (await page.request.get(`${base}/element-types`, { headers: adminHeaders })).json();
    const board = elementTypes.find((t: { name: string }) => t.name === "Board") ?? elementTypes[0];
    const mcu = `MCU ${suffix}`;
    const sensor = `Sensor ${suffix}`;
    const flash = `Flash ${suffix}`;
    for (const name of [mcu, sensor, flash]) {
      const res = await page.request.post(`${base}/elements`, { headers: adminHeaders, data: { name, element_type_id: board.id, activate: true } });
      expect(res.ok(), await res.text()).toBeTruthy();
    }

    await test.step("the seeded types list the group they sit under", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Connection Types", "System Architecture");
      await expect(page.getByText("Hardware · Solid, two-way · Under Serial bus").first()).toBeVisible();
    });

    await test.step("add a project type that sits under two groups", async () => {
      await page.getByRole("button", { name: "New connection type with details" }).click();
      const dialog = page.getByRole("dialog", { name: "New connection type" });
      await dialog.getByLabel("Name", { exact: true }).fill("Board-to-board link");
      await dialog.getByRole("button", { name: "Sits under", exact: true }).click();
      const tree = page.getByRole("group", { name: "Sits under" });
      await tree.getByRole("checkbox", { name: "Serial bus", exact: true }).check();
      await tree.getByRole("checkbox", { name: "Network", exact: true }).check();
      await page.keyboard.press("Escape");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Connection type created.")).toBeVisible();
      await expect(page.getByText(/Under Network, Serial bus|Under Serial bus, Network/)).toBeVisible();
    });

    await test.step("start a connection on the group Serial bus", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/connections`);
      await page.getByRole("button", { name: "New connection" }).click();
      const dialog = page.getByRole("dialog", { name: "New connection" });
      await selectOptionContaining(dialog.getByLabel("Source element"), mcu);
      await selectOptionContaining(dialog.getByLabel("Target element"), sensor);
      await chooseType(page, dialog, "Serial bus", "serial");
      await dialog.getByRole("button", { name: "Save and activate" }).click();
      await expect(page.getByText("Connection created.")).toBeVisible();
      await expect(page.locator("tr", { hasText: sensor }).getByText("Serial bus", { exact: true })).toBeVisible();
    });

    await test.step("refine it to I2C once the design is detailed", async () => {
      await page.locator("tr", { hasText: sensor }).getByRole("link", { name: /CON-001/ }).click();
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await chooseType(page, dialog, "I2C", "i2c");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Connection updated.")).toBeVisible();
    });

    await test.step("add a second connection typed SPI", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/connections`);
      await page.getByRole("button", { name: "New connection" }).click();
      const dialog = page.getByRole("dialog", { name: "New connection" });
      await selectOptionContaining(dialog.getByLabel("Source element"), mcu);
      await selectOptionContaining(dialog.getByLabel("Target element"), flash);
      await chooseType(page, dialog, "SPI", "spi");
      await dialog.getByRole("button", { name: "Save and activate" }).click();
      await expect(page.getByText("Connection created.")).toBeVisible();
    });

    await test.step("filtering on the group finds both, filtering on a member finds one", async () => {
      const filter = page.getByLabel("Connection type", { exact: true });
      await filter.selectOption({ label: "Serial bus" });
      await expect(page.locator("tr", { hasText: sensor })).toBeVisible();
      await expect(page.locator("tr", { hasText: flash })).toBeVisible();
      await filter.selectOption({ label: "Serial bus › I2C" });
      await expect(page.locator("tr", { hasText: sensor })).toBeVisible();
      await expect(page.locator("tr", { hasText: flash })).toHaveCount(0);
    });
  });
});
