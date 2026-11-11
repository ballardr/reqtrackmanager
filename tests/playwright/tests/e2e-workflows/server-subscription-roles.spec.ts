import { expect, test } from "@playwright/test";

import { apiHeaders, deleteOrgOnCleanup, installCleanupHook, loginAs, SERVER_ADMIN_LOGIN } from "./helpers";

// Deletes the disposable organisations each test creates (even on timeout).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";
const MANAGER = { email: "e2e-subscription-manager@example.com" } as const;
const REMOVER = { email: "e2e-removal-authority@example.com" } as const;
const MODULE_ADMIN = { email: "e2e-module-admin@example.com" } as const;
const PLAIN_MEMBER = { email: "e2e-member-ab@example.com" } as const;

/** Creates a disposable organisation as the server administrator and schedules its removal. */
async function createDisposableOrg(request: import("@playwright/test").APIRequestContext, label: string) {
  const headers = await apiHeaders(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const name = `E2E Subscription ${label} ${Date.now()}`;
  const resp = await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers, data: { name } });
  expect(resp.status()).toBe(201);
  const org: { id: string; name: string } = await resp.json();
  deleteOrgOnCleanup({ id: org.id });
  return org;
}

/**
 * Job to be done: a Platform subscription manager provisions and suspends organisations but cannot delete one,
 * open its administration or reach any other server setting.
 */
test("a Platform subscription manager suspends an organisation and has no Delete", async ({ page }) => {
  const org = await createDisposableOrg(page.request, "Manager");
  await loginAs(page, MANAGER.email);

  await test.step("the navigation offers Organisations and Server management", async () => {
    await expect(page.getByRole("link", { name: "Organisations", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Server management" })).toBeVisible();
  });

  await test.step("creating is offered, deleting and editing are not", async () => {
    await page.goto("/server/organisations");
    await expect(page.getByRole("button", { name: /^New organisation/ })).toBeVisible();
    await page.getByRole("button", { name: `${org.name} actions` }).click();
    const menu = page.getByRole("menu", { name: `${org.name} actions` });
    await expect(menu.getByRole("menuitem", { name: "Disable" })).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Delete" })).toHaveCount(0);
    await expect(menu.getByRole("menuitem", { name: "Administration" })).toHaveCount(0);
  });

  await test.step("suspending the organisation takes effect", async () => {
    await page.getByRole("menuitem", { name: "Disable" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Disable" }).click();
    const headers = await apiHeaders(page.request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
    await expect
      .poll(async () => (await (await page.request.get(`${apiBaseUrl}/api/v1/orgs/${org.id}`, { headers })).json()).is_active)
      .toBe(false);
  });

  await test.step("only the module entitlements of Server management are available, and other settings are refused", async () => {
    await page.goto("/server/management/accessReview");
    // A group this person may not use falls back to the first they may, and the address names it.
    await expect(page).toHaveURL(/\/server\/management\/modules$/);
    await expect(page.getByRole("heading", { name: "Availability per organisation" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Entitlement policy" })).toHaveCount(0);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const refused = await page.request.get(`${apiBaseUrl}/api/v1/system/users`, { headers: { Authorization: `Bearer ${token}` } });
    expect(refused.status()).toBe(403);
    const deleted = await page.request.delete(`${apiBaseUrl}/api/v1/orgs/${org.id}`, {
      headers: { Authorization: `Bearer ${token}` }, data: { confirm_name: org.name },
    });
    expect(deleted.status()).toBe(403);
  });
});

/**
 * Job to be done: a Subscription removal authority finds an organisation and deletes it after typing its name; it
 * can neither create nor suspend an organisation and does not see Server management.
 */
test("a Subscription removal authority deletes an organisation and cannot create one", async ({ page }) => {
  const org = await createDisposableOrg(page.request, "Removal");
  await loginAs(page, REMOVER.email);

  await test.step("only Organisations is in the navigation", async () => {
    await expect(page.getByRole("link", { name: "Organisations", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Server management" })).toHaveCount(0);
  });

  await test.step("creating and suspending are not offered", async () => {
    await page.goto("/server/organisations");
    await expect(page.getByRole("button", { name: `${org.name} actions` })).toBeVisible();
    await expect(page.getByRole("button", { name: /^New organisation/ })).toHaveCount(0);
    await page.getByRole("button", { name: `${org.name} actions` }).click();
    const menu = page.getByRole("menu", { name: `${org.name} actions` });
    await expect(menu.getByRole("menuitem", { name: "Delete" })).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Disable" })).toHaveCount(0);
  });

  await test.step("the deletion needs the typed name and then removes the organisation", async () => {
    await page.getByRole("menuitem", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Permanently delete" })).toBeDisabled();
    await dialog.getByRole("textbox").fill(org.name);
    await dialog.getByRole("button", { name: "Permanently delete" }).click();
    await expect(page.getByRole("button", { name: `${org.name} actions` })).toHaveCount(0);
  });
});

/**
 * Job to be done: a Module administrator reaches only the Modules group of Server management, with the deployment-wide
 * policy and defaults that a Platform subscription manager does not see, and cannot see the organisation list's actions.
 */
test("a Module administrator reaches only the Modules group, with the policy and defaults", async ({ page }) => {
  await loginAs(page, MODULE_ADMIN.email);
  await page.goto("/server/management/accessReview");
  await expect(page).toHaveURL(/\/server\/management\/modules$/);
  await expect(page.getByRole("heading", { name: "Entitlement policy" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Module defaults" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Availability per organisation" })).toBeVisible();
});

/** Job to be done: a person with no server role who opens Server management is told they have no access. */
test("a person with no server role is told Server management is not available to them", async ({ page }) => {
  await loginAs(page, PLAIN_MEMBER.email);
  await page.goto("/server/management");
  await expect(page.getByText("You do not have access to server management.")).toBeVisible();
  await page.getByRole("link", { name: "Return to the home page" }).click();
  // The home page redirects to the person's landing page; the point is that they have left Server management.
  await expect(page).not.toHaveURL(/\/server\//);
});
