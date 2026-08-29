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
    // All") — a substring match on "Status" is normally fine (only this
    // one control on the page contains it), but React Router 7's default
    // startTransition-wrapped navigation (the URL updates immediately, but
    // a just-left page's content can stay mounted for a beat — see the
    // identical fix in golden-path.spec.ts) can transiently leave a
    // *different* page's own "status"-containing filter mounted alongside
    // this one, and unlike a plain label that ambiguity can't be resolved
    // with `{ exact: true }` given the option-text quirk above.
    await expect(page.getByRole("heading", { name: "Organisations", exact: true })).toBeVisible();
    // Disabled orgs are hidden by default (UI/UX pass) — this test watches
    // one org through its whole lifecycle including a disabled state, so
    // it needs the "All" filter rather than the default "Active" one.
    await page.getByLabel("Status").selectOption("all");

    await test.step("create the organisation", async () => {
      // "New organisation" opens a Modal (style guide "Pattern: modal
      // dialog for entity create/rename") — scoped to it rather than the
      // whole page.
      await page.getByRole("button", { name: "New organisation" }).click();
      const dialog = page.getByRole("dialog", { name: "New organisation" });
      await dialog.getByLabel("Organisation name").fill(orgName);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("row", { name: new RegExp(orgName) })).toContainText("Active");
    });

    const row = page.getByRole("row", { name: new RegExp(orgName) });

    await test.step("disable it", async () => {
      // Disable now confirms via the shared `ConfirmDialog` (sixth-pass
      // audit) rather than `window.confirm`.
      await row.getByRole("button", { name: "Disable" }).click();
      await page.getByRole("dialog", { name: `Disable "${orgName}"?` }).getByRole("button", { name: "Disable" }).click();
      await expect(row).toContainText("Disabled");
    });

    await test.step("re-enable it", async () => {
      await row.getByRole("button", { name: "Enable" }).click();
      await expect(row).toContainText("Active");
    });

    await test.step("delete requires typing the exact name", async () => {
      await row.getByRole("button", { name: "Delete", exact: true }).click();
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
