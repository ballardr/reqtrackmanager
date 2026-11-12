import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook, selectOptionContaining, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/** The row of the definition grid whose name input holds `value`. */
const gridRow = (page: Page, value: string) =>
  page.locator(`input[value="${value}"]`).first().locator("xpath=ancestor::div[contains(@class,'definition-grid__row')][1]");

/**
 * Job to be done: an architect records the parts of a product and how they connect. Elements nest under a parent, carry
 * ports, are joined by typed connections and move through a lifecycle (a parent cannot retire while a child is in use);
 * the project can hide an organisation's default element type, and a collection shares elements with other projects.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture switched on; everything else through the UI.
 */
test.describe("System Architecture: elements, connections and sharing", () => {
  test("an architect builds a small system, connects it, retires it in order and hides a default type", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "Architecture", false, "System Architecture");
    const gateway = `Gateway ${suffix}`;
    const orders = `Orders ${suffix}`;

    await test.step("create a top-level element and activate it in one step", async () => {
      await page.goto(`/projects/${project.id}`);
      await page.getByRole("link", { name: "Architecture", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/architecture/elements$`));
      await page.getByRole("button", { name: "New element" }).click();
      const dialog = page.getByRole("dialog", { name: "New element" });
      await expect(dialog.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
      await dialog.getByLabel("Name", { exact: true }).fill(gateway);
      await dialog.getByRole("button", { name: "Save and activate" }).click();
      await expect(page.getByText("Element created.")).toBeVisible();
      await expect(page.locator("tr", { hasText: gateway }).getByText("Active", { exact: true })).toBeVisible();
    });

    await test.step("create a child under it, left as a draft, and see it nested in the tree", async () => {
      await page.getByRole("button", { name: "New element" }).click();
      const dialog = page.getByRole("dialog", { name: "New element" });
      await dialog.getByLabel("Name", { exact: true }).fill(orders);
      await selectOptionContaining(dialog.getByLabel("Parent element"), gateway);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.locator("tr", { hasText: orders }).getByText("Draft", { exact: true })).toBeVisible();

      await page.getByRole("tab", { name: "Tree" }).click();
      const parentItem = page.getByRole("listitem").filter({ has: page.getByRole("link", { name: new RegExp(gateway) }) }).first();
      await expect(parentItem.getByRole("link", { name: new RegExp(orders) })).toBeVisible();
    });

    await test.step("add a port to the parent on its page", async () => {
      await page.getByRole("link", { name: new RegExp(gateway) }).first().click();
      await expect(page.getByRole("heading", { name: new RegExp(gateway) })).toBeVisible();
      const ports = page.getByRole("region", { name: "Ports" });
      await ports.getByPlaceholder("Port name").fill("HTTPS API");
      await ports.getByRole("button", { name: "Add port" }).click();
      await expect(ports.locator('input[value="HTTPS API"]')).toBeVisible();
      await ports.getByLabel("Direction of HTTPS API").selectOption("in");
      await page.reload();
      await expect(page.getByRole("region", { name: "Ports" }).getByLabel("Direction of HTTPS API")).toHaveValue("in");
    });

    await test.step("connect the two elements through the Connections list", async () => {
      await page.getByRole("link", { name: "Connections", exact: true }).first().click();
      await expect(page.getByText("No connections recorded for this project yet.")).toBeVisible();
      await page.getByRole("button", { name: "New connection" }).click();
      const dialog = page.getByRole("dialog", { name: "New connection" });
      await selectOptionContaining(dialog.getByLabel("Source element"), gateway);
      await selectOptionContaining(dialog.getByLabel("Source port"), "HTTPS API");
      await selectOptionContaining(dialog.getByLabel("Target element"), orders);
      await dialog.getByLabel("Protocol").fill("HTTPS/1.1");
      await dialog.getByRole("button", { name: "Save and activate" }).click();
      await expect(page.getByText("Connection created.")).toBeVisible();
      const row = page.locator("tr", { hasText: "HTTPS/1.1" });
      await expect(row.getByText(new RegExp(`${gateway} \\(HTTPS API\\)`))).toBeVisible();
      await expect(row.getByText(new RegExp(orders))).toBeVisible();
    });

    await test.step("a parent cannot retire while a child is in use; retire the child first", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/elements`);
      await page.getByRole("link", { name: /ELM-002/ }).click();
      await page.getByRole("button", { name: "Activate" }).click();
      await expect(page.getByText("Element moved to Active.")).toBeVisible();

      await page.goBack();
      await page.getByRole("link", { name: /ELM-001/ }).click();
      await page.getByRole("button", { name: "Retire" }).click();
      await expect(page.getByText(/still has 1 child element\(s\) in use/)).toBeVisible();

      await page.goBack();
      await page.getByRole("link", { name: /ELM-002/ }).click();
      await page.getByRole("button", { name: "Retire" }).click();
      await expect(page.getByText("Element moved to Retired.")).toBeVisible();
      await page.goBack();
      await page.getByRole("link", { name: /ELM-001/ }).click();
      await page.getByRole("button", { name: "Retire" }).click();
      await expect(page.getByText("Element moved to Retired.")).toBeVisible();
    });

    await test.step("hide an organisation default element type in the project, then add it back", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Element Types", "System Architecture");
      await gridRow(page, "Service").getByRole("button", { name: "Hide element type in this project" }).click();
      await page.getByRole("dialog", { name: 'Hide "Service" in this project?' }).getByRole("button", { name: "Hide" }).click();
      await expect(page.locator('input[value="Service"]')).toHaveCount(0);

      await page.goto(`/projects/${project.id}/modules/architecture/elements`);
      await page.getByRole("button", { name: "New element" }).click();
      const typeSelect = page.getByRole("dialog", { name: "New element" }).getByLabel("Element type");
      await expect(typeSelect.locator("option", { hasText: "Service" })).toHaveCount(0);
      await expect(typeSelect.locator("option", { hasText: "Component" })).toHaveCount(1);
      await page.keyboard.press("Escape");

      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Element Types", "System Architecture");
      await page.getByRole("button", { name: "Add organisation defaults (1)" }).click();
      await page.getByRole("dialog", { name: "Add organisation defaults" }).getByRole("button", { name: "Add 1 default" }).click();
      await expect(page.locator('input[value="Service"]')).toBeVisible();
    });
  });

  test("a collection groups elements for sharing and the element's page lists the collection", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchShare", true, "System Architecture");
    const apiBase = "http://localhost:8000";
    const element = `Identity ${suffix}`;
    const created = await page.request.post(`${apiBase}/api/v1/projects/${project.id}/modules/architecture/elements`, {
      headers: adminHeaders,
      data: { name: element, element_type_id: (await (await page.request.get(`${apiBase}/api/v1/projects/${project.id}/modules/architecture/element-types`, { headers: adminHeaders })).json())[0].id, activate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture/sharing`);
    await page.getByRole("button", { name: "New collection" }).click();
    const dialog = page.getByRole("dialog", { name: "New collection" });
    await dialog.getByLabel("Name", { exact: true }).fill("Shared infrastructure");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    const card = page.getByRole("region", { name: "Shared infrastructure" });
    await expect(card.getByText("No elements in this collection.")).toBeVisible();
    await expect(card.getByText("Not shared with anyone yet.")).toBeVisible();

    await selectOptionContaining(card.getByLabel("Add an element to Shared infrastructure"), element);
    await expect(card.getByText(new RegExp(element))).toBeVisible();

    // The element's own page lists the collection it is shared through.
    await page.goto(`/projects/${project.id}/modules/architecture/elements`);
    await page.getByRole("link", { name: /ELM-001/ }).click();
    await expect(page.getByRole("region", { name: "Sharing" }).getByText("Shared infrastructure · 0 grants")).toBeVisible();
  });
});
