import { expect, test } from "@playwright/test";

import { ensureExpanded, loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: an organisation administrator gives an integration its own identity. The service user has no
 * password and no sign-in; the administrator issues a personal access token for it, which authenticates as the
 * service user until it is revoked. The deep rules (closed sign-in paths, scope, expiry, audit) are covered by the
 * backend tests; this spec proves what only a browser and the API together can: the secret the dialog shows once is
 * a working credential, revoking it through the dialog kills it, the badge marks the account, and the account cannot
 * sign in with a password.
 *
 * Persona: `orgAdminGamma` (`org_admin` of Gamma only). The service user has a name unique to the run and is
 * deactivated and archived at the end, so the test can be repeated against the same database.
 */
const apiBaseUrl = "http://localhost:8000";

test("an administrator creates a service user, issues a token that works, revokes it and archives the account", async ({ page }) => {
  const name = `E2E service ${Date.now()}`;
  await loginAs(page, PERSONAS.orgAdminGamma.email);
  await page.goto("/orgs");
  await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
  await page.getByRole("link", { name: "Users", exact: true }).click();
  await ensureExpanded(page, "Service users");

  await test.step("create the service user", async () => {
    await page.getByRole("button", { name: "New service user" }).click();
    const dialog = page.getByRole("dialog", { name: "New service user" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("textbox", { name: "Description" }).fill("Created by the end-to-end suite.");
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText("Service user created.")).toBeVisible();
    const row = page.getByRole("row", { name: new RegExp(name) });
    await expect(row.getByText("Service", { exact: true })).toBeVisible();
    // Nobody is named responsible, so the access review flags it.
    await expect(row.getByText("No responsible party")).toBeVisible();
  });

  const detail = page.getByRole("dialog", { name: `Service user: ${name}` });
  let token = "";
  await test.step("issue a token and see its secret once", async () => {
    await page.getByRole("button", { name: new RegExp(`^${name}`) }).click();
    await detail.getByRole("button", { name: "Issue token" }).click();
    const form = page.getByRole("dialog", { name: "Issue token" });
    await form.getByRole("textbox", { name: "Token name" }).fill("Playwright token");
    await form.getByRole("button", { name: "Issue token" }).click();
    const secret = detail.locator("[role=status] code");
    await expect(secret).toBeVisible();
    token = (await secret.textContent()) ?? "";
    expect(token.startsWith("rtm_pat_")).toBe(true);
    await expect(detail.getByText(/shown once/)).toBeVisible();
    await detail.getByRole("button", { name: "I have copied it" }).click();
    await expect(secret).toHaveCount(0);
    await expect(detail.getByRole("row", { name: /Playwright token/ })).toContainText("Active");
  });

  let email = "";
  await test.step("the token authenticates as the service user, which cannot sign in with a password", async () => {
    const me = await page.request.get(`${apiBaseUrl}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
    expect(me.ok()).toBe(true);
    const body = await me.json();
    expect(body.display_name).toBe(name);
    email = body.email;
    const login = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email, password: "Anything-Goes-123!" } });
    // Refused either as an unknown account (401) or, for the reserved `.invalid` address, as not a valid email (422).
    expect([401, 422]).toContain(login.status());
  });

  await test.step("revoking the token kills it", async () => {
    await detail.getByRole("button", { name: "Revoke the token Playwright token" }).click();
    await page.getByRole("dialog", { name: "Revoke this token?" }).getByRole("button", { name: "Revoke" }).click();
    await expect(page.getByText("Token revoked.")).toBeVisible();
    await expect(detail.getByRole("row", { name: /Playwright token/ })).toContainText("Revoked");
    const after = await page.request.get(`${apiBaseUrl}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
    expect(after.status()).toBe(401);
  });

  await test.step("deactivate and archive the account", async () => {
    await detail.getByRole("button", { name: "Deactivate" }).click();
    await page.getByRole("dialog", { name: `Deactivate ${name}?` }).getByRole("button", { name: "Deactivate" }).click();
    await expect(page.getByText("Service user deactivated.")).toBeVisible();
    await detail.getByRole("button", { name: "Archive" }).click();
    const confirm = page.getByRole("dialog", { name: `Archive ${name}?` });
    await confirm.getByRole("textbox").fill(name);
    await confirm.getByRole("button", { name: "Archive" }).click();
    await expect(page.getByText("Service user archived.")).toBeVisible();
    await expect(page.getByRole("row", { name: new RegExp(name) })).toHaveCount(0);
  });
});
