import { expect, test } from "@playwright/test";

import { PASSWORD, PERSONAS } from "./helpers";

/**
 * Job to be done: a user who belongs to no organisation can use the app shell without a crash, an infinite spinner
 * or a console error. Pages that assume at least one organisation (Users table, project members, groups, the
 * org-admin hierarchy bypass, the add-member autocomplete, per-row action menus) are unreachable with no
 * organisation context, so this is a general app-shell robustness check.
 *
 * Uses the orphan persona (seeded as an Alpha member, then removed through self-service leave in
 * `backend/scripts/seed_e2e_dataset.py`, so it has zero `UserOrgRole` rows). It is shared read-only with
 * `two-factor-auth.spec.ts`, `org-login-2fa-handoff.spec.ts` and `user-directory-and-bans.spec.ts`; this spec only
 * navigates and asserts, so it leaves the persona unchanged.
 */
test.describe("app shell for a user with zero organisation memberships", () => {
  test("orgs, nav rail, projects, and favourites all degrade gracefully", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(err.message));

    await page.goto("/login");
    await page.getByLabel("Email").fill(PERSONAS.orphan.email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    await test.step("/orgs shows an empty directory, not a crash", async () => {
      await page.getByRole("link", { name: "Organisation settings" }).click();
      await expect(page).toHaveURL(/\/orgs$/);
      await expect(page.getByText("You do not belong to any organisations yet.")).toBeVisible();
    });

    await test.step("the nav rail has no org-admin/server-admin section for this plain, non-server-admin persona", async () => {
      // "Organisation settings" itself is a universal entry point (shown to
      // every signed-in user regardless of membership, Layout.tsx) — the
      // conditional nav content this persona must NOT see is the
      // server-admin-only "Administration" section (`user.is_server_admin`),
      // which zero org memberships alone must not accidentally unlock.
      await expect(page.getByRole("link", { name: "Organisation settings" })).toBeVisible();
      await expect(page.getByText("Administration", { exact: true })).not.toBeVisible();
      await expect(page.getByRole("link", { name: "Server management" })).not.toBeVisible();
    });

    await test.step("/projects shows a sane empty state", async () => {
      await page.getByRole("link", { name: "Projects", exact: true }).click();
      await expect(page).toHaveURL(/\/projects$/);
      await expect(page.getByText("No projects to show.")).toBeVisible();
    });

    await test.step("/favourites (navigated directly — zero favourites means no nav-rail entry at all) shows a sane empty state", async () => {
      await page.goto("/favourites");
      await expect(page.getByRole("heading", { name: "Favourites" })).toBeVisible();
      await expect(page.getByText("No projects to show.")).toBeVisible();
    });

    expect(consoleErrors, `unexpected console/page errors: ${consoleErrors.join("\n")}`).toEqual([]);
  });
});
