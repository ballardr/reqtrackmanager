import { expect, test, type Page } from "@playwright/test";

import { addDefinition, installCleanupHook, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** The row of the definition grid whose name input holds `value`. */
const gridRow = (page: Page, value: string) =>
  page.locator(`input[value="${value}"]`).first().locator("xpath=ancestor::div[contains(@class,'definition-grid__row')][1]");

/**
 * Job to be done: a team that works in more than software and hardware names its own domains, puts an element type in
 * several of them and finds the type under each domain where it is added to a diagram; an organisation default domain a
 * project does not use is hidden there and can be added back.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the diagram is created through the API as
 * setup, the domains and the type through the UI.
 */
test.describe("System Architecture: domains are a vocabulary", () => {
  test("a project adds a domain, puts a type in two domains, finds it under each in the Add menu, and hides and restores a default", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchDomains", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const domain = `Optical ${suffix}`;
    const typeName = `Lens ${suffix}`;

    await test.step("add a domain of the project's own", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Domains", "System Architecture");
      await expect(page.locator('input[value="Software"]')).toBeVisible();
      await expect(page.locator('input[value="Hardware"]')).toBeVisible();
      const created = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith("/modules/architecture/domains") && r.ok());
      await addDefinition(page, "Add domain", { Name: domain });
      await created;
      await expect(page.locator(`input[value="${domain}"]`)).toBeVisible();
    });

    await test.step("an element type is in the new domain and in Hardware", async () => {
      await selectProjectAdminGroup(page, "Element Types", "System Architecture");
      await page.getByRole("button", { name: "New element type with details" }).click();
      const dialog = page.getByRole("dialog", { name: "New element type" });
      await dialog.getByLabel("Name", { exact: true }).fill(typeName);
      await expect(dialog.getByRole("button", { name: "Domains", exact: true })).toContainText("Any domain");
      await dialog.getByRole("button", { name: "Domains", exact: true }).click();
      await page.getByRole("checkbox", { name: domain, exact: true }).check();
      await page.getByRole("checkbox", { name: "Hardware", exact: true }).check();
      await page.keyboard.press("Escape");
      await expect(dialog.getByRole("button", { name: "Domains", exact: true })).toContainText(domain);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Element type created.")).toBeVisible();
      await expect(page.getByText(new RegExp(`Hardware, ${domain} · Rectangle`)).or(page.getByText(new RegExp(`${domain}, Hardware · Rectangle`)))).toBeVisible();
    });

    await test.step("the type is listed under each of its domains in the diagram's Add menu", async () => {
      const diagram = await (await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } })).json();
      await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
      await page.getByRole("button", { name: "Add to diagram" }).click();
      const menu = page.getByRole("menu", { name: "Add to diagram" });
      // A group of one type shows its heading over the type; a group of several is a row that opens in place.
      await expect(menu.getByText(`New ${domain.toLowerCase()} element`, { exact: true })).toBeVisible();
      await expect(menu.getByText("New hardware element", { exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("hide an organisation default domain in the project, then add it back", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Domains", "System Architecture");
      await gridRow(page, "Software").getByRole("button", { name: "Hide domain in this project" }).click();
      const hidden = page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().includes("/modules/architecture/domains/") && r.ok());
      await page.getByRole("dialog", { name: 'Hide "Software" in this project?' }).getByRole("button", { name: "Hide" }).click();
      await hidden;
      await expect(page.locator('input[value="Software"]')).toHaveCount(0);
      await page.getByRole("button", { name: "Add organisation defaults (1)" }).click();
      await page.getByRole("dialog", { name: "Add organisation defaults" }).getByRole("button", { name: "Add 1 default" }).click();
      await expect(page.locator('input[value="Software"]')).toBeVisible();
    });

    await test.step("a domain a type is in cannot be deleted, and says why", async () => {
      await gridRow(page, domain).getByRole("button", { name: "Delete domain" }).click();
      await expect(page.getByText(/still used by a type or a diagram switch/)).toBeVisible();
      await expect(page.locator(`input[value="${domain}"]`)).toBeVisible();
    });
  });
});
