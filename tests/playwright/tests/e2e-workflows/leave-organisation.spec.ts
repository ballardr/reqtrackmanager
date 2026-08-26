import { expect, test } from "@playwright/test";

/**
 * Job to be done: a user can leave an organisation themselves, from
 * Preferences' "Your access" tab (2026-08 UX audit roadmap item 520) —
 * moved out of Org Admin entirely, since leaving is about the current
 * user's own membership, not an org-level setting. Previously fired
 * immediately with zero confirmation; now goes through the shared Tier 1
 * `ConfirmDialog` and reports success via `Toast`, matching every other
 * ordinary/reversible mutation in the app.
 *
 * Uses a disposable organisation + a brand-new user created via the API
 * (same pattern `org-rename-and-test-email.spec.ts` already established)
 * rather than a shared seed persona/org — leaving an org is exactly the
 * kind of mutation other specs sharing this suite's single-worker run
 * shouldn't see happen to a persona/org they also depend on.
 */

const apiBaseUrl = "http://localhost:8000";

test.describe("leave organisation from Preferences", () => {
  test("cancelling the confirm dialog keeps membership; confirming leaves and removes the org from the list", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Leave Org ${suffix}`;
    const userEmail = `e2e-leave-org-${suffix}@example.com`;
    const password = "LeaveOrg123!";

    const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    });
    const adminToken = (await adminLoginResp.json()).access_token;

    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { name: orgName },
      })
    ).json();
    // Plain "member", not "org_admin" — `leave_organization` (backend/app/
    // routers/orgs.py) 409s rather than silently stripping an org of its
    // last admin, which this brand-new, single-user org's own admin would
    // otherwise be. A plain member has no such guard to work around.
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { email: userEmail, display_name: "E2E Leave Org User", password, role: "member" },
    });

    await page.goto("/login");
    await page.getByLabel("Email").fill(userEmail);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    await page.goto("/preferences");
    await page.getByRole("tab", { name: "Your access" }).click();
    await expect(page.getByText(orgName)).toBeVisible();

    await test.step("cancelling the confirm dialog leaves membership untouched", async () => {
      await page.getByRole("button", { name: `Leave ${orgName}` }).click();
      const dialog = page.getByRole("dialog", { name: `Leave ${orgName}?` });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).not.toBeVisible();
      await expect(page.getByText(orgName)).toBeVisible();
    });

    await test.step("confirming leaves the organisation, shows feedback, and removes it from the list", async () => {
      await page.getByRole("button", { name: `Leave ${orgName}` }).click();
      const dialog = page.getByRole("dialog", { name: `Leave ${orgName}?` });
      await Promise.all([
        page.waitForResponse((r) => r.url().includes(`/orgs/${org.id}/membership`) && r.request().method() === "DELETE"),
        dialog.getByRole("button", { name: "Leave" }).click(),
      ]);
      await expect(page.getByText("Left organisation")).toBeVisible();
      await expect(page.getByText(orgName)).not.toBeVisible();
    });

    await test.step("the org no longer appears in this user's own membership list", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const mine = await (
        await page.request.get(`${apiBaseUrl}/api/v1/orgs?mine=true`, { headers: { Authorization: `Bearer ${token}` } })
      ).json();
      expect(mine.find((o: { id: string }) => o.id === org.id)).toBeUndefined();
    });
  });
});
