import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, selectPreferencesGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a user leaves an organisation from Preferences' "Your access" tab; the action goes through the
 * shared Tier 1 `ConfirmDialog` and reports success via `Toast`.
 *
 * Uses a disposable organisation and a new user created through the API, so no shared persona or organisation is
 * affected by the membership change.
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
    deleteOrgOnCleanup({ id: org.id });
    // A plain "member": `leave_organization` (backend/app/routers/orgs.py) returns 409 rather than remove an
    // organisation's last administrator.
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
    await selectPreferencesGroup(page, "Your access");
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
