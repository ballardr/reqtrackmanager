import { expect, test } from "@playwright/test";

import { loginAs, openProject, openRequirementByCode, PERSONAS, PROJECT_NAMES } from "./helpers";

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
 * Links are shown and edited in the shared Links panel (`ArtefactLinksPanel`,
 * October 2026 platform enhancements Phase 6): "Add link" opens a dialog (record
 * finder, then the relationship) and removing a link goes through a
 * `ConfirmDialog` (Tier 1). A link's phrase is also one of the dialog's own
 * `<option>` labels, so every assertion below is scoped to the panel's rendered
 * rows (their badge, or the real `<a>`) rather than a bare `getByText`.
 */
function linkBadge(page: import("@playwright/test").Page, text: string) {
  return page.locator("span.badge", { hasText: text });
}

const linksPanel = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Links", exact: true });

/** Links the open requirement to the requirement named `target` with `relationship` via the panel's dialog. */
async function addRequirementLink(page: import("@playwright/test").Page, relationship: string, target: string) {
  await linksPanel(page).getByRole("button", { name: "Add link" }).click();
  const modal = page.getByRole("dialog", { name: "Add a link" });
  await modal.getByLabel("Link to").selectOption({ label: "Requirement" });
  await modal.getByLabel("Search").fill(target);
  const targetSelect = modal.getByLabel("Record");
  await expect(targetSelect.locator("option", { hasText: target })).toHaveCount(1);
  await targetSelect.selectOption({ label: await targetSelect.locator("option", { hasText: target }).innerText() });
  // The relationship is chosen after the record, from those usable for it.
  await modal.getByLabel("Relationship").selectOption({ label: relationship });
  await modal.getByRole("button", { name: "Add link" }).click();
  await expect(modal).not.toBeVisible();
}

/** Removes the link whose row reads `phrase`, confirming the dialog. */
async function removeLink(page: import("@playwright/test").Page, phrase: string) {
  await linksPanel(page).getByRole("button", { name: new RegExp(`^Remove link: ${phrase}`) }).click();
  const dialog = page.getByRole("dialog", { name: "Remove this link?" });
  await dialog.getByRole("button", { name: "Remove link" }).click();
  await expect(dialog).not.toBeVisible();
}

/**
 * Self-heals Alpha-1 before the run: deletes any HW-FN-005 -> SW-PERF-006 or
 * HW-FN-007 -> SW-PERF-008 link an earlier run left behind (a run that
 * times out before its own removal step leaks the link, and the picker
 * then no longer offers the already-linked target — found 2026-10-04).
 * Never touches the seeded SW-PERF-002 -> HW-FN-001 fixture.
 */
async function removeLeftoverLinks(page: import("@playwright/test").Page) {
  const projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
  const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const headers = { Authorization: `Bearer ${token}` };
  const base = `http://localhost:8000/api/v1/projects/${projectId}/requirements`;
  for (const [source, target] of [["HW-FN-005", "SW-PERF-006"], ["HW-FN-007", "SW-PERF-008"]]) {
    const matches: { id: string; unique_code: string }[] = await (
      await page.request.get(`${base}?search=${source}`, { headers })
    ).json();
    const requirement = matches.find((r) => r.unique_code === source);
    if (!requirement) continue;
    const links: { id: string; other_requirement_unique_code: string }[] = await (
      await page.request.get(`${base}/${requirement.id}/links`, { headers })
    ).json();
    for (const link of links.filter((l) => l.other_requirement_unique_code === target)) {
      await page.request.delete(`${base}/${requirement.id}/links/${link.id}`, { headers });
    }
  }
}

test.describe("requirement traceability links", () => {
  test("the seeded custom link type reads correctly from both ends; a new link can be added and removed", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await removeLeftoverLinks(page);

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

    await test.step("add a new 'Depends on' link between two other requirements via the panel's 'Add link' dialog", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-005");
      await addRequirementLink(page, "Depends on", "SW-PERF-006");
      await expect(linkBadge(page, "Depends on")).toBeVisible();
      await expect(page.getByRole("link", { name: /SW-PERF-006/ })).toBeVisible();
    });

    await test.step("the dialog's search narrows the offered records", async () => {
      // A third, otherwise-untouched pair (neither seeded with a fixed
      // link/action/attachment nor used by any other spec) — added then
      // immediately removed so this step is fully self-contained and leaves
      // no state behind for later runs.
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-007");
      await linksPanel(page).getByRole("button", { name: "Add link" }).click();
      const modal = page.getByRole("dialog", { name: "Add a link" });
      await modal.getByLabel("Link to").selectOption({ label: "Requirement" });
      await modal.getByLabel("Search").fill("SW-PERF-008");
      // The search actually filters: only the matching requirement is offered.
      await expect(modal.getByLabel("Record").locator("option", { hasText: "SW-PERF-008" })).toHaveCount(1);
      await expect(modal.getByLabel("Record").locator("option", { hasText: "HW-FN-001" })).toHaveCount(0);
      await modal.getByRole("button", { name: "Cancel" }).click();
      await addRequirementLink(page, "Depends on", "SW-PERF-008");
      await expect(linkBadge(page, "Depends on")).toBeVisible();
      await expect(page.getByRole("link", { name: /SW-PERF-008/ })).toBeVisible();

      await removeLink(page, "Depends on");
      await expect(linkBadge(page, "Depends on")).toHaveCount(0);
    });

    await test.step("the reverse name shows on the target requirement's own page", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "SW-PERF-006");
      await expect(linkBadge(page, "Is a dependency of")).toBeVisible();
      await expect(page.getByRole("link", { name: /HW-FN-005/ })).toBeVisible();
    });

    await test.step("remove the link from the target requirement's own page (confirming the ConfirmDialog); it disappears from both ends", async () => {
      await removeLink(page, "Is a dependency of");
      await expect(linkBadge(page, "Is a dependency of")).toHaveCount(0);

      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-005");
      await expect(linkBadge(page, "Depends on")).toHaveCount(0);
    });
  });
});
