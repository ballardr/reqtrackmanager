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
  test("shows, pins and dismisses the importance-weight help without moving or changing the form", async ({ page }) => {
    const { project } = await setUpOrg(page, "FieldHelp");
    await openPeople(page, project.id, "persona");
    await openNew(page, "Persona");

    const dialog = page.getByRole("dialog", { name: "New Persona (project)" });
    const weight = dialog.getByLabel("Importance weight");
    const helpButton = dialog.getByRole("button", { name: "Help: Importance weight" });
    // The help is a tooltip portalled to the page body, so it is found on the page, not in the dialog.
    const helpText = page.getByRole("tooltip").filter({ hasText: /How much this persona counts when scores are rolled up/ });

    await weight.fill("4");
    await expect(helpText).toHaveCount(0);
    const before = await weight.boundingBox();

    // Mouse: a click pins it past mouse-leave, leaves the typed value alone and moves nothing.
    await helpButton.click();
    await expect(helpText).toBeVisible();
    await page.mouse.move(0, 0);
    await expect(helpText).toBeVisible();
    await expect(weight).toHaveValue("4");
    expect(await weight.boundingBox()).toEqual(before);
    await helpButton.click();
    await expect(helpText).toHaveCount(0);

    // Hover alone shows it, and leaving hides it again (the pointer re-enters, as a closed click leaves it over the button).
    await page.mouse.move(0, 0);
    await helpButton.hover();
    await expect(helpText).toBeVisible();
    await page.mouse.move(0, 0);
    await expect(helpText).toHaveCount(0);

    // Keyboard: focus shows it, Enter pins it, Escape closes the help but not the dialog.
    await weight.focus(); // the button kept focus from the clicks above; move away so focusing it again is a real focus
    await helpButton.focus();
    await expect(helpText).toBeVisible();
    await page.keyboard.press("Enter");
    await page.keyboard.press("Escape");
    await expect(helpText).toHaveCount(0);
    await expect(dialog).toBeVisible();
    await expect(helpButton).toBeFocused();

    // A press outside closes a pinned help.
    await helpButton.click();
    await expect(helpText).toBeVisible();
    await dialog.getByRole("heading").first().click();
    await expect(helpText).toHaveCount(0);
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
