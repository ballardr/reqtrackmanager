import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: inside a Compliance standard the header search box looks in that standard, and the search
 * page's Scope filter offers "This standard" beside "All projects". The scope comes from the module's own
 * registration, so it appears only on the standard's pages.
 *
 * The standard is created with a per-run suffix, so the spec depends on no seeded fixture.
 */
test.describe("global search: Compliance standard scope", () => {
  test("on a standard's pages the box searches that standard and the Scope filter offers it", async ({ page }) => {
    const suffix = Date.now();
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference: `E2E-SRCH-${suffix}`, name: `E2E Search Standard ${suffix}` });
    const standardId = page.url().split("/standards/")[1];

    const box = page.getByRole("combobox", { name: "Search" });
    await box.fill("access");
    await expect(page.getByText("See all results for ‘access’ in This standard")).toBeVisible();
    await box.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/search\\?q=access&scope=compliance%3Astandard%3A${standardId}`));

    const scope = page.getByRole("combobox", { name: "Scope" });
    await expect(scope.locator("option")).toHaveText(["This standard", "All projects"]);
    await scope.selectOption({ label: "All projects" });
    await expect(page).toHaveURL(/\/search\?q=access$/);

    // Away from the standard the scope is not offered.
    await page.goto("/projects");
    await box.fill("access");
    await expect(page.getByText("See all results for ‘access’ in All projects")).toBeVisible();
  });
});
