import { expect, test } from "@playwright/test";

import { apiHeaders, loginAs, PERSONAS, SERVER_ADMIN_LOGIN, selectServerManagementGroup } from "./helpers";

/**
 * Job to be done: the server administration pages behave the same way as the rest of the product. A group of fields
 * has one Save that is unavailable until a change and confirms with a toast; the platform pictures are removable;
 * revoking every Personal Access Token needs a typed confirmation; the Organisations list is a sortable table whose
 * names open the organisation's administration.
 *
 * Mutates the deployment-wide email footer company name and restores it through the API in `afterAll`.
 */

const apiBaseUrl = "http://localhost:8000";

type Footer = { email_footer_company_name: string | null };

async function readFooter(request: import("@playwright/test").APIRequestContext): Promise<Footer> {
  const resp = await request.get(`${apiBaseUrl}/api/v1/system/branding`);
  return resp.json();
}

test.describe("server administration", () => {
  let original: Footer;

  test.beforeAll(async ({ request }) => {
    original = await readFooter(request);
  });

  test.afterAll(async ({ request }) => {
    const headers = await apiHeaders(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
    const resp = await request.put(`${apiBaseUrl}/api/v1/system/branding`, {
      headers, data: { email_footer_company_name: original.email_footer_company_name },
    });
    expect(resp.ok()).toBeTruthy();
  });

  test("Server details has one Save that waits for a change and confirms with a toast", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    await selectServerManagementGroup(page, "Server details");

    const save = page.getByRole("button", { name: "Save", exact: true });
    await expect(save).toBeDisabled();
    await page.getByLabel(/^Company name/).fill(`E2E Details ${Date.now()}`);
    await expect(save).toBeEnabled();
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/system/branding") && r.request().method() === "PUT"),
      save.click(),
    ]);
    await expect(page.getByText("Server details saved.")).toBeVisible();
    await expect(save).toBeDisabled();
  });

  test("the menu lists the groups by relatedness, with Users first and no Access review", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    const links = page.locator("nav.resource-menu-nav").getByRole("link");
    await expect(links.first()).toHaveText("Users");
    await expect(page.locator("nav.resource-menu-nav").getByRole("link", { name: "Access review" })).toHaveCount(0);
    await expect(page.locator("nav.resource-menu-nav").getByRole("link", { name: "Server details", exact: true })).toBeVisible();
  });

  test("revoking every Personal Access Token needs the typed word", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management");
    await page.getByRole("button", { name: "Revoke all Personal Access Tokens platform-wide", exact: true }).click();
    const dialog = page.getByRole("dialog");
    const confirm = dialog.getByRole("button", { name: "Revoke all Personal Access Tokens platform-wide", exact: true });
    await expect(confirm).toBeDisabled();
    await dialog.getByRole("textbox").fill("Revoke");
    await expect(confirm).toBeEnabled();
    // Not confirmed: it would revoke the tokens the rest of the suite uses.
    await dialog.getByRole("button", { name: "Close" }).click();
  });

  test("the Organisations list is sortable and a name opens the organisation's administration", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/organisations?status=all");
    const table = page.getByRole("table", { name: "Organisations" });
    await expect(table.getByRole("columnheader", { name: /Name/ })).toBeVisible();
    await table.getByRole("button", { name: /Name/ }).click();
    const first = table.getByRole("row").nth(1).getByRole("link");
    const name = await first.innerText();
    await first.click();
    await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]+\/admin/);
    await expect(page.getByText(name).first()).toBeVisible();
  });
});
