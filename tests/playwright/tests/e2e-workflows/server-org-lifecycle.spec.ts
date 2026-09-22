import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: as a server administrator, I need to be able to disable
 * an organisation reversibly (e.g. a hosting customer stopped paying) and,
 * separately, permanently delete one once it's genuinely no longer needed
 * — both from the Server Management console, without touching any other
 * organisation. See docs/decisions.md's "Organisation disable and hard
 * delete" section for the full design.
 *
 * Persona: ServerAdminOnly (zero org memberships).
 */
test.describe("server admin manages an organisation's lifecycle", () => {
  test("create, disable, re-enable, then permanently delete an organisation", async ({ page }) => {
    const orgName = `Lifecycle Test Org ${Date.now()}`;

    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.getByRole("link", { name: "Organisations", exact: true }).last().click();
    await expect(page).toHaveURL(/\/server\/organisations$/);
    // Wait for this page's own heading before touching its Status filter:
    // `FilterField` nests the `<select>` inside the same `<label>` as its
    // caption (components/FilterPanel.tsx), so the accessible "label" text
    // `getByLabel` matches against is the caption *plus every option's own
    // text* (confirmed directly: this control's is "StatusActiveDisabled
    // All") — a plain substring match on "Status" isn't safe: any org row's
    // `ActionMenu` trigger has an accessible name of "<org name> actions",
    // and an org whose name happens to contain the word "Status"/"Statuses"
    // (e.g. another spec's "E2E Statuses Org" fixture, still present in the
    // shared test DB) then collides with it. Scoping by role="combobox"
    // (the native `<select>`'s accessible role; the `ActionMenu` trigger is
    // role="button") disambiguates regardless of what other rows/fixtures
    // exist on the page. React Router 7's default startTransition-wrapped
    // navigation (the URL updates immediately, but a just-left page's
    // content can stay mounted for a beat — see the identical fix in
    // golden-path.spec.ts) can also transiently leave a *different* page's
    // own "status"-containing filter mounted alongside this one; the heading
    // wait below already guards against that.
    await expect(page.getByRole("heading", { name: "Organisations", exact: true })).toBeVisible();
    // Disabled orgs are hidden by default (UI/UX pass) — this test watches
    // one org through its whole lifecycle including a disabled state, so
    // it needs the "All" filter rather than the default "Active" one.
    await page.getByRole("combobox", { name: "Status" }).selectOption("all");

    await test.step("create the organisation, with Decision Management's seeded template picker visible", async () => {
      // "New organisation" opens a Modal (style guide "Pattern: modal
      // dialog for entity create/rename") — scoped to it rather than the
      // whole page.
      await page.getByRole("button", { name: "New organisation" }).click();
      const dialog = page.getByRole("dialog", { name: "New organisation" });
      await dialog.getByLabel("Organisation name").fill(orgName);

      // Module 4 (Decision Management) Phase 1's org-creation-choices
      // picker (`GET /orgs/creation-choices`) — this page renders it
      // generically with no hardcoded knowledge of Decision Management,
      // so exercising it here is real coverage of that mechanism, not
      // just this specific module's own three packs. All three are
      // `default_selected: true`, so pre-checked; leave Y-Statement
      // unchecked to prove an opt-out is actually respected (checked
      // indirectly — the org still creates successfully with one
      // deselected — since no Decision Management UI exists yet, Phase 5,
      // to directly verify which templates a given org ended up with).
      await expect(dialog.getByText("Decision Templates")).toBeVisible();
      const nygard = dialog.getByRole("checkbox", { name: /Nygard/ });
      const madr = dialog.getByRole("checkbox", { name: /MADR/ });
      const yStatement = dialog.getByRole("checkbox", { name: /Y-Statement/ });
      await expect(nygard).toBeChecked();
      await expect(madr).toBeChecked();
      await expect(yStatement).toBeChecked();
      await yStatement.uncheck();

      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("row", { name: new RegExp(orgName) })).toContainText("Active");
    });

    const row = page.getByRole("row", { name: new RegExp(orgName) });
    // Style guide "Pattern: action menu"'s per-row addendum — Edit/
    // Disable-Enable/Delete now sit behind one `ActionMenu` in the row's
    // actions column instead of three standalone buttons.
    const rowActionsMenu = page.getByRole("menu", { name: `${orgName} actions` });

    await test.step("edit opens this organisation's own admin page", async () => {
      await row.getByRole("button", { name: `${orgName} actions` }).click();
      await rowActionsMenu.getByRole("menuitem", { name: "Edit" }).click();
      await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
      await expect(page.getByText(orgName)).toBeVisible();

      await page.goBack();
      await expect(page).toHaveURL(/\/server\/organisations$/);
      // A fresh mount of this page after navigating back defaults to the
      // "Active" status filter, same as a first visit — re-apply "All" so
      // the rest of this test (which watches this org through a disabled
      // state) can still find its row. role="combobox" scoping: see the
      // comment on this same selector near the top of this test.
      await page.getByRole("combobox", { name: "Status" }).selectOption("all");
    });

    await test.step("disable it", async () => {
      // Disable now confirms via the shared `ConfirmDialog` (sixth-pass
      // audit) rather than `window.confirm`.
      await row.getByRole("button", { name: `${orgName} actions` }).click();
      await rowActionsMenu.getByRole("menuitem", { name: "Disable" }).click();
      await page.getByRole("dialog", { name: `Disable "${orgName}"?` }).getByRole("button", { name: "Disable" }).click();
      await expect(row).toContainText("Disabled");
    });

    await test.step("re-enable it", async () => {
      await row.getByRole("button", { name: `${orgName} actions` }).click();
      await rowActionsMenu.getByRole("menuitem", { name: "Enable" }).click();
      await expect(row).toContainText("Active");
    });

    await test.step("delete requires typing the exact name", async () => {
      await row.getByRole("button", { name: `${orgName} actions` }).click();
      await rowActionsMenu.getByRole("menuitem", { name: "Delete" }).click();
      const confirmButton = page.getByRole("button", { name: "Permanently delete" });
      await expect(confirmButton).toBeDisabled();
      await page.getByPlaceholder(orgName).fill("the wrong name");
      await expect(confirmButton).toBeDisabled();
      await page.getByPlaceholder(orgName).fill(orgName);
      await expect(confirmButton).toBeEnabled();
      await confirmButton.click();
    });

    await test.step("the organisation is gone", async () => {
      await expect(page.getByRole("row", { name: new RegExp(orgName) })).toHaveCount(0);
    });
  });
});
