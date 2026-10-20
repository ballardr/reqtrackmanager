import { expect, test } from "@playwright/test";

import { chooseRecordAction, loginAs, openProject, openRequirementByName, PERSONAS, PROJECT_NAMES, recordActionNames } from "./helpers";

/**
 * The `/unarchive` counterpart to `requirement-archive-confirm.spec.ts`
 *. Covers the full
 * archive-then-restore round trip for both a requirement and an action:
 * archive it, confirm it's reachable only via each list's own "Include
 * archived" filter with an "Archived" badge, restore it via the detail
 * page's new "Restore" button (no `ConfirmDialog` — mirrors
 * `ProjectAdminPage.tsx`'s existing unarchive button, which also fires
 * immediately), and confirm it's back in the default active list.
 *
 * Creates its own throwaway requirement and action rather than reusing
 * seeded data, matching `requirement-archive-confirm.spec.ts`'s own
 * reasoning: other specs may depend on the seeded fixtures staying in
 * their current (active) state, so a spec that itself archives/restores
 * something must own a fixture nobody else touches.
 */
test.describe("requirement and action restore", () => {
  test("archiving a requirement, then restoring it, returns it to the active list", async ({ page }) => {
    const name = `E2E Restore Requirement ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    await test.step("create a throwaway requirement", async () => {
      await page.getByRole("button", { name: "New requirement" }).click();
      await page.getByPlaceholder("Name", { exact: true }).fill(name);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      // Search rather than assume page one of the paginated list (shared
      // Alpha-1 grows every run).
      await page.getByPlaceholder("Search by name or ID").fill(name);
      await expect(page.getByText(name)).toBeVisible();
    });

    await test.step("archive it (Tier 1 ConfirmDialog) — it drops off the default list", async () => {
      await openRequirementByName(page, name);
      await chooseRecordAction(page, "Requirement", "Archive");
      const dialog = page.getByRole("dialog", { name: "Archive this requirement?" });
      await dialog.getByRole("button", { name: "Archive", exact: true }).click();
      await page.waitForURL(/\/requirements$/);
      // Searched, so "not visible" means archived, not merely off page one.
      await page.getByPlaceholder("Search by name or ID").fill(name);
      await expect(page.getByText(name)).not.toBeVisible();
    });

    await test.step("it's reachable via 'Include archived', tagged with an Archived badge", async () => {
      await page.getByLabel("Include archived").check();
      const link = page.getByRole("link", { name });
      await expect(link).toBeVisible();
      // Scoped to this link's own row/card ancestor (same xpath approach as
      // `openRequirementByCode` in helpers.ts) rather than a bare
      // `.card, tr` selector — the whole table sits inside an outer
      // `<div className="card">` wrapper in list view, so an unscoped
      // `.card` match picks up every row's badge at once, not just this
      // one, and collides with another spec's own archived fixture when
      // the full suite runs tests in parallel.
      const row = link.locator(
        "xpath=ancestor::*[self::tr or contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]"
      );
      await expect(row.getByText("Archived", { exact: true })).toBeVisible();
      await link.click();
    });

    await test.step("the detail page shows Restore (not Archive) and an Archived badge", async () => {
      await expect(page.getByRole("heading", { name: new RegExp(name) })).toBeVisible();
      await expect.poll(() => recordActionNames(page, "Requirement")).toContain("Restore");
      await expect.poll(() => recordActionNames(page, "Requirement")).not.toContain("Archive");
      await expect(page.getByText("Archived", { exact: true })).toBeVisible();
    });

    await test.step("clicking Restore (no confirmation dialog) shows a toast and flips the buttons back", async () => {
      await chooseRecordAction(page, "Requirement", "Restore");
      await expect(page.getByText("Requirement restored")).toBeVisible();
      await expect.poll(() => recordActionNames(page, "Requirement")).toContain("Archive");
      await expect.poll(() => recordActionNames(page, "Requirement")).not.toContain("Restore");
    });

    await test.step("it's back in the default (active) requirements list", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await expect(page.getByLabel("Include archived")).not.toBeChecked();
      await page.getByPlaceholder("Search by name or ID").fill(name);
      await expect(page.getByText(name)).toBeVisible();
    });
  });

  test("archiving an action, then restoring it, returns it to the active list", async ({ page }) => {
    const title = `E2E Restore Action ${Date.now()}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Actions", exact: true }).click();

    await test.step("create a throwaway action", async () => {
      await page.getByRole("button", { name: "New action" }).click();
      await page.getByLabel("Title").fill(title);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByText("Action created")).toBeVisible();
      await expect(page.getByRole("link", { name: title })).toBeVisible();
    });

    await test.step("archive it (Tier 1 ConfirmDialog) — the detail page goes read-only in place", async () => {
      await page.getByRole("link", { name: title }).click();
      await chooseRecordAction(page, "Action", "Archive");
      const dialog = page.getByRole("dialog", { name: "Archive this action?" });
      await dialog.getByRole("button", { name: "Archive", exact: true }).click();
      await expect(page.getByText("Action archived")).toBeVisible();
      await expect(page.getByLabel("Title")).toBeDisabled();
      await expect.poll(() => recordActionNames(page, "Action")).toContain("Restore");
      await expect.poll(() => recordActionNames(page, "Action")).not.toContain("Archive");
    });

    await test.step("it drops off the default Actions list but is reachable via 'Include archived'", async () => {
      await page.getByRole("link", { name: "Actions", exact: true }).click();
      await expect(page.getByRole("link", { name: title })).not.toBeVisible();
      await page.getByLabel("Include archived").check();
      await expect(page.getByRole("link", { name: title })).toBeVisible();
      await expect(page.locator("tr", { hasText: title }).getByText("Archived", { exact: true })).toBeVisible();
      await page.getByRole("link", { name: title }).click();
    });

    await test.step("clicking Restore (no confirmation dialog) shows a toast and makes the fields editable again", async () => {
      await chooseRecordAction(page, "Action", "Restore");
      await expect(page.getByText("Action restored")).toBeVisible();
      await expect(page.getByLabel("Title")).toBeEnabled();
      await expect.poll(() => recordActionNames(page, "Action")).toContain("Archive");
      await expect.poll(() => recordActionNames(page, "Action")).not.toContain("Restore");
    });

    await test.step("it's back in the default (active) actions list", async () => {
      await page.getByRole("link", { name: "Actions", exact: true }).click();
      await expect(page.getByLabel("Include archived")).not.toBeChecked();
      await expect(page.getByRole("link", { name: title })).toBeVisible();
    });
  });
});
