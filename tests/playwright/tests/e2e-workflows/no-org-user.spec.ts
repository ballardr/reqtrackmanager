import { expect, test } from "@playwright/test";

import { PASSWORD, PERSONAS } from "./helpers";

/**
 * Job to be done: a user who belongs to zero organisations at all can
 * still use the app shell without a crash, an infinite spinner, or a
 * console error — every page most of this session's new code implicitly
 * assumes "at least one org" for (Users table, project members, groups,
 * the org-admin hierarchy bypass, the combined add-member/add-group
 * autocomplete, the new per-row action menus) is unreachable with zero
 * org/project context in the first place, so this is really a general
 * app-shell robustness check, not something specific to PR6's own new UI
 * (PR6 of the members/groups directory rework plan's "Additional test"
 * note, docs/decisions.md).
 *
 * Uses the orphan persona (seeded as an Alpha member, then removed via
 * self-service leave — see `backend/scripts/seed_e2e_dataset.py` — so it
 * ends up with genuinely zero `UserOrgRole` rows, not just zero *visible*
 * orgs). Already shared, read-only-safe, across `two-factor-auth.spec.ts`/
 * `org-login-2fa-handoff.spec.ts`/`user-directory-and-bans.spec.ts` for the
 * same "zero org memberships" reason; this spec only navigates and asserts
 * — it makes no mutation, so it can't leave the persona in a different
 * state for any of those.
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
      await page.getByRole("link", { name: "My organisations" }).click();
      await expect(page).toHaveURL(/\/orgs$/);
      await expect(page.getByText("You don't belong to any organisations yet.")).toBeVisible();
    });

    await test.step("the nav rail has no org-admin/server-admin section for this plain, non-server-admin persona", async () => {
      // "My organisations" itself is a universal entry point (shown to
      // every signed-in user regardless of membership, Layout.tsx) — the
      // conditional nav content this persona must NOT see is the
      // server-admin-only "Administration" section (`user.is_server_admin`),
      // which zero org memberships alone must not accidentally unlock.
      await expect(page.getByRole("link", { name: "My organisations" })).toBeVisible();
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
