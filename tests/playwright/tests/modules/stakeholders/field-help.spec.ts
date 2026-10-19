import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { openNew, openPeople, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done:
 * Playwright e2e coverage for field help (`FieldHelp`, docs/ux-style-guide.md, "Pattern: field help")
 * on the Persona form, whose importance weight is the field that most needs explaining.
 *
 * Builds a disposable org + admin + project through the API (see `setUpOrg`), so the spec depends on
 * no seeded state and can run alone, first, last or repeated.
 */
test.describe("Field help on the Persona form", () => {
  test("opens and closes the importance-weight help by mouse and by keyboard without changing the form", async ({ page }) => {
    const { project } = await setUpOrg(page, "FieldHelp");
    await openPeople(page, project.id, "persona");
    await openNew(page, "Persona");

    const dialog = page.getByRole("dialog", { name: "New Persona (project)" });
    const weight = dialog.getByLabel("Importance weight");
    const helpButton = dialog.getByRole("button", { name: "Help: Importance weight (optional)" });
    const helpText = dialog.getByText(/How much this persona counts when scores are rolled up/);

    await weight.fill("4");
    await expect(helpText).toHaveCount(0);

    // Mouse: the button toggles the text and leaves the typed value alone.
    await helpButton.click();
    await expect(helpButton).toHaveAttribute("aria-expanded", "true");
    await expect(helpText).toBeVisible();
    await expect(weight).toHaveValue("4");
    await helpButton.click();
    await expect(helpText).toHaveCount(0);

    // Keyboard: Enter opens it, Escape closes the help but not the dialog.
    await helpButton.focus();
    await page.keyboard.press("Enter");
    await expect(helpText).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(helpText).toHaveCount(0);
    await expect(dialog).toBeVisible();
    await expect(helpButton).toBeFocused();
  });

  test("a self-explanatory field has no help button", async ({ page }) => {
    const { project } = await setUpOrg(page, "FieldHelpNone");
    await openPeople(page, project.id, "persona");
    await openNew(page, "Persona");

    const dialog = page.getByRole("dialog", { name: "New Persona (project)" });
    await expect(dialog.getByLabel("Persona name")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Help: Name" })).toHaveCount(0);
  });
});
