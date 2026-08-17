import { expect, test } from "@playwright/test";

import { loginAs, openRequirementByCode, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: two requirements can be linked with a typed, bidirectional
 * relationship (C-G-09) — the link renders with the correct display name
 * from whichever requirement's page you're looking from (`forward_name`
 * from the source, `reverse_name` from the target), entirely resolved
 * server-side, and can be removed from either end.
 *
 * Uses Alpha-1, which `backend/scripts/seed_e2e_dataset.py` already seeds
 * with a fixed custom link type ("E2E Supersedes"/"E2E Is superseded by")
 * and one fixed link (SW-PERF-002 -> HW-FN-001) for exactly this spec to
 * sanity-check read-only. The create/remove flow below uses two different,
 * untouched requirements (HW-FN-005/SW-PERF-006) so this spec never
 * mutates that shared fixture.
 *
 * A link's display name (e.g. "Depends on") is also one of the "add link"
 * form's own `<option>` labels, and the other requirement's own code/name
 * is also an `<option>` in the "Target requirement" picker — every
 * assertion below is scoped to the actual rendered link row (its badge, or
 * the real `<a>` it renders as) rather than a bare `getByText`, to stay
 * unambiguous against those selects.
 */
function linkBadge(page: import("@playwright/test").Page, text: string) {
  return page.locator("span.badge", { hasText: text });
}

test.describe("requirement traceability links", () => {
  test("the seeded custom link type reads correctly from both ends; a new link can be added and removed", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    await test.step("the seeded fixed link shows the forward name on its source requirement", async () => {
      await openRequirementByCode(page, "SW-PERF-002");
      await expect(linkBadge(page, "E2E Supersedes")).toBeVisible();
      await expect(page.getByRole("link", { name: /HW-FN-001/ })).toBeVisible();
    });

    await test.step("and the reverse name on its target requirement", async () => {
      await page.getByRole("link", { name: /HW-FN-001/ }).click();
      await expect(page.url()).toContain("/requirements/");
      await expect(linkBadge(page, "E2E Is superseded by")).toBeVisible();
      await expect(page.getByRole("link", { name: /SW-PERF-002/ })).toBeVisible();
    });

    await test.step("add a new 'Depends on' link between two other requirements", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-005");
      const targetSelect = page.getByLabel("Target requirement");
      const targetValue = await targetSelect.locator("option", { hasText: "SW-PERF-006" }).getAttribute("value");
      await targetSelect.selectOption(targetValue!);
      await page.getByLabel("Link type").selectOption({ label: "Depends on" });
      await page.getByRole("button", { name: "Add link" }).click();
      await expect(linkBadge(page, "Depends on")).toBeVisible();
      await expect(page.getByRole("link", { name: /SW-PERF-006/ })).toBeVisible();
    });

    await test.step("the reverse name shows on the target requirement's own page", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "SW-PERF-006");
      await expect(linkBadge(page, "Is a dependency of")).toBeVisible();
      await expect(page.getByRole("link", { name: /HW-FN-005/ })).toBeVisible();
    });

    await test.step("remove the link from the target requirement's own page; it disappears from both ends", async () => {
      const linkRow = page.locator(".row", { hasText: "Is a dependency of" });
      await linkRow.getByRole("button").click();
      await expect(linkBadge(page, "Is a dependency of")).toHaveCount(0);

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-005");
      await expect(linkBadge(page, "Depends on")).toHaveCount(0);
    });
  });
});
