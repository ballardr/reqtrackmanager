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
 *
 * 2026-08 UX audit, sixth pass: "Add link" opens a picker instead of
 * rendering the target/type selects as a permanently-visible inline row,
 * and removing a link now goes through a `ConfirmDialog` (Tier 1) instead
 * of firing immediately — both asserted below alongside the underlying job.
 *
 * Platform-review-2026-09 Phase 7 replaced that picker's original flat,
 * unsearched `<select>` `Popover` with `RequirementLinkPickerModal` — a
 * `Modal` offering a default-active Search tab (exercised below, alongside
 * the underlying create/remove job) and a Requirements browse tab
 * (component -> category -> requirement cascade, exercised in its own
 * dedicated step using a third, otherwise-untouched requirement pair so it
 * doesn't interfere with the create/remove flow's own HW-FN-005/
 * SW-PERF-006 pair).
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

    await test.step("add a new 'Depends on' link between two other requirements via the 'Add link' modal's Search tab", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-005");
      await page.getByRole("button", { name: "Add link" }).click();
      const modal = page.getByRole("dialog", { name: "Add link" });
      // Search is the default-active tab.
      await modal.getByPlaceholder("Search by code or name…").fill("SW-PERF-006");
      const targetSelect = modal.getByLabel("Target requirement");
      const targetValue = await targetSelect.locator("option", { hasText: "SW-PERF-006" }).getAttribute("value");
      await targetSelect.selectOption(targetValue!);
      await modal.getByLabel("Link type").selectOption({ label: "Depends on" });
      await modal.getByRole("button", { name: "Add link" }).click();
      await expect(modal).not.toBeVisible();
      await expect(linkBadge(page, "Depends on")).toBeVisible();
      await expect(page.getByRole("link", { name: /SW-PERF-006/ })).toBeVisible();
    });

    await test.step("the 'Add link' modal's Requirements tab cascades component -> category -> requirement", async () => {
      // A third, otherwise-untouched pair (neither seeded with a fixed
      // link/action/attachment nor used by any other spec, confirmed by
      // grep before writing this step) — added then immediately removed so
      // this step is fully self-contained and leaves no state behind for
      // later runs.
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-007");
      await page.getByRole("button", { name: "Add link" }).click();
      const modal = page.getByRole("dialog", { name: "Add link" });
      await modal.getByRole("tab", { name: "Requirements" }).click();
      await modal.getByLabel("Component").selectOption({ label: "Hardware (HW)" });
      await modal.getByLabel("Category").selectOption({ label: "Functional (FN)" });
      // The cascade actually filters: Hardware/Functional never offers a
      // Software/Performance requirement.
      await expect(modal.getByLabel("Target requirement").locator("option", { hasText: "SW-PERF-008" })).toHaveCount(0);
      await modal.getByLabel("Component").selectOption({ label: "Software (SW)" });
      await modal.getByLabel("Category").selectOption({ label: "Performance (PERF)" });
      const targetSelect = modal.getByLabel("Target requirement");
      const targetValue = await targetSelect.locator("option", { hasText: "SW-PERF-008" }).getAttribute("value");
      await targetSelect.selectOption(targetValue!);
      await modal.getByLabel("Link type").selectOption({ label: "Depends on" });
      await modal.getByRole("button", { name: "Add link" }).click();
      await expect(modal).not.toBeVisible();
      await expect(linkBadge(page, "Depends on")).toBeVisible();
      await expect(page.getByRole("link", { name: /SW-PERF-008/ })).toBeVisible();

      const linkRow = page.locator(".row", { hasText: "Depends on" });
      await linkRow.getByRole("button").click();
      const dialog = page.getByRole("dialog", { name: "Remove this link?" });
      await dialog.getByRole("button", { name: "Remove link" }).click();
      await expect(dialog).not.toBeVisible();
      await expect(linkBadge(page, "Depends on")).toHaveCount(0);
    });

    await test.step("the reverse name shows on the target requirement's own page", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "SW-PERF-006");
      await expect(linkBadge(page, "Is a dependency of")).toBeVisible();
      await expect(page.getByRole("link", { name: /HW-FN-005/ })).toBeVisible();
    });

    await test.step("remove the link from the target requirement's own page (confirming the ConfirmDialog); it disappears from both ends", async () => {
      const linkRow = page.locator(".row", { hasText: "Is a dependency of" });
      await linkRow.getByRole("button").click();
      const dialog = page.getByRole("dialog", { name: "Remove this link?" });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Remove link" }).click();
      await expect(dialog).not.toBeVisible();
      await expect(linkBadge(page, "Is a dependency of")).toHaveCount(0);

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-005");
      await expect(linkBadge(page, "Depends on")).toHaveCount(0);
    });
  });
});
