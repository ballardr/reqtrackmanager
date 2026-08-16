import { expect, test } from "@playwright/test";

import { loginAs, logout, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: profile preferences persist server-side (not just
 * localStorage) — theme (U-U-01), pronouns (C-U-18), and the post-login
 * landing page (U-U-03, all three modes: automatic / overview / a specific
 * project). The Help page is also checked here as a light, low-risk page
 * visit rather than its own spec file.
 *
 * The landing preference is only resolved once, at the moment of login
 * (`resolveLandingPath` in LoginPage.tsx) — it's not applied to ordinary
 * in-app navigation like clicking the brand logo, which always goes to
 * plain `/projects`. Testing it for real means logging out and back in for
 * each mode, not just navigating around within one session.
 */
test.describe("preferences: theme persistence, pronouns, landing page mode; help page", () => {
  test("theme and pronouns persist across reload; all three landing-page modes save", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await test.step("theme persists across reload", async () => {
      await page.getByTitle("Preferences").click();
      await page.getByLabel("Theme").selectOption("dark");
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      await page.getByLabel("Theme").selectOption("light");
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    });

    await test.step("pronouns save and persist", async () => {
      await page.getByLabel("Pronouns").fill("they/them");
      // Wait for the PATCH to actually settle before reloading — a bare
      // click() races the async save against the immediate reload below,
      // which can abort it in flight.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
        page.getByRole("button", { name: "Save preferences" }).click(),
      ]);
      await page.reload();
      await expect(page.getByLabel("Pronouns")).toHaveValue("they/them");
    });

    await test.step("landing page mode: a specific project", async () => {
      await page.getByLabel("Landing page after login").selectOption("project");
      await page.getByLabel("Which project").selectOption({ label: PROJECT_NAMES.alpha1 });
      // Same PATCH-vs-navigation race as the pronouns step above — wait for
      // the save to settle before logout() navigates away.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
        page.getByRole("button", { name: "Save preferences" }).click(),
      ]);

      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
      await expect(page.getByRole("heading", { name: PROJECT_NAMES.alpha1 })).toBeVisible();
    });

    await test.step("landing page mode: project overview list", async () => {
      await page.getByTitle("Preferences").click();
      await page.getByLabel("Landing page after login").selectOption("overview");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
        page.getByRole("button", { name: "Save preferences" }).click(),
      ]);

      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await expect(page).toHaveURL(/\/projects$/);
    });

    await test.step("landing page mode: automatic (this account has multiple projects, so resolves the same as 'overview')", async () => {
      await page.getByTitle("Preferences").click();
      await page.getByLabel("Landing page after login").selectOption("auto");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
        page.getByRole("button", { name: "Save preferences" }).click(),
      ]);

      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await expect(page).toHaveURL(/\/projects$/);
    });

    await test.step("the help page renders", async () => {
      await page.getByRole("link", { name: "Help", exact: true }).click();
      await expect(page).toHaveURL(/\/help$/);
      await expect(page.locator("main")).not.toBeEmpty();
    });

    await test.step("the access tab lists direct and inherited org-group membership", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const me = await (
        await page.request.get("http://localhost:8000/api/v1/auth/me", { headers: { Authorization: `Bearer ${token}` } })
      ).json();
      const orgs = await (
        await page.request.get("http://localhost:8000/api/v1/orgs?mine=true", { headers: { Authorization: `Bearer ${token}` } })
      ).json();
      const alphaOrgId = orgs.find((o: { name: string; id: string }) => o.name === ORG_NAMES.alpha).id;
      const suffix = Date.now();
      const parentName = `E2E Preferences Parent ${suffix}`;
      const childName = `E2E Preferences Child ${suffix}`;
      const authHeaders = { Authorization: `Bearer ${token}` };
      const parent = await (
        await page.request.post(`http://localhost:8000/api/v1/orgs/${alphaOrgId}/groups`, {
          headers: authHeaders, data: { name: parentName },
        })
      ).json();
      const child = await (
        await page.request.post(`http://localhost:8000/api/v1/orgs/${alphaOrgId}/groups`, {
          headers: authHeaders, data: { name: childName },
        })
      ).json();
      await page.request.post(`http://localhost:8000/api/v1/orgs/${alphaOrgId}/groups/${parent.id}/members`, {
        headers: authHeaders, data: { member_org_group_id: child.id },
      });
      await page.request.post(`http://localhost:8000/api/v1/orgs/${alphaOrgId}/groups/${child.id}/members`, {
        headers: authHeaders, data: { user_id: me.id },
      });

      await page.goto("/preferences");
      await page.getByRole("button", { name: "Your access" }).click();
      await expect(page.getByText(childName)).toBeVisible();
      await expect(page.getByText(parentName)).toBeVisible();
      await expect(page.getByText("(via a nested group)")).toBeVisible();
    });
  });
});
