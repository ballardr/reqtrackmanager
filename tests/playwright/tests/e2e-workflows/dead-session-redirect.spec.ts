import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiLogin, deleteOrgOnCleanup, ensureExpanded, installCleanupHook, SERVER_ADMIN_LOGIN } from "./helpers";

// Deletes this file's disposable organisation after the test that created it (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/** Creates a disposable organisation holding one member (so no shared persona's password or token is touched). */
async function createDisposableMember(request: APIRequestContext, password: string): Promise<string> {
  const suffix = `${Date.now()}-${Math.floor(Math.random() * 1000)}`;
  const email = `e2e-dead-session-${suffix}@example.com`;
  const admin = await apiLogin(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: { Authorization: `Bearer ${admin.access_token}` },
      data: { name: `E2E Dead Session Org ${suffix}` },
    })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  const created = await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: { Authorization: `Bearer ${admin.access_token}` },
    data: { email, display_name: "Dead Session Persona", password, role: "member" },
  });
  expect(created.ok()).toBe(true);
  return email;
}

/**
 * A session whose token was invalidated on the server (here by a password change made from another session) ends at
 * the first refused request: the person is returned to sign-in without reloading, then back to the page they were on.
 *
 * The interface (port 3000) and the API (port 8000) are different origins in this stack, so the browser hides every
 * response header the API does not expose; only a real browser against this stack can show that the client still
 * recognises a dead token (curl and the backend's own test client bypass cross-origin rules).
 */
test.describe("a dead session returns to sign-in", () => {
  test("the first refused request ends the session without a reload and sign-in returns to the page", async ({ page, request }) => {
    const firstPassword = "Password123!";
    const secondPassword = "Password456!";
    const email = await createDisposableMember(request, firstPassword);

    // The signed-in browser session.
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(firstPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await page.evaluate(() => {
      (window as unknown as { __notReloaded: boolean }).__notReloaded = true;
    });

    // Another session changes the password, which invalidates every token issued before it.
    const other = await apiLogin(request, email, firstPassword);
    const changed = await request.post(`${apiBaseUrl}/api/v1/auth/change-password`, {
      headers: { Authorization: `Bearer ${other.access_token}` },
      data: { current_password: firstPassword, new_password: secondPassword },
    });
    expect(changed.ok()).toBe(true);

    // Any request from the page now, without leaving it: switching to the list view saves the choice as a preference.
    const pageBefore = new URL(page.url()).pathname;
    await page.getByRole("button", { name: "List view" }).click();
    await expect(page).toHaveURL(/\/login$/);
    // The page was not reloaded: the client router moved to sign-in on its own.
    expect(await page.evaluate(() => (window as unknown as { __notReloaded?: boolean }).__notReloaded)).toBe(true);

    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(secondPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await expect.poll(() => new URL(page.url()).pathname).toBe(pageBefore);
  });

  test("a wrong current password on the change-password form does not end the session", async ({ page, request }) => {
    // The ordinary 401 the change-password call answers for a typing mistake carries no dead-session signal.
    const password = "Password123!";
    const email = await createDisposableMember(request, password);
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    await page.goto("/preferences/security");
    await ensureExpanded(page, "Change password");
    await page.getByLabel("Current password").fill("not-the-password");
    await page.getByLabel("New password").fill("Password789!");
    await page.getByRole("button", { name: "Change password", exact: true }).click();

    await expect(page.getByText("Current password is incorrect.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await expect(page).toHaveURL(/\/preferences\/security/);
  });
});
