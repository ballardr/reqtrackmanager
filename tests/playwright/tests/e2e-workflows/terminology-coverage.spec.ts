import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: C-C-03's per-project terminology overrides actually reach
 * every surface that renders one of the six overridable nouns, not just the
 * nav label + list-page heading the 2026-08 UX audit found were the only
 * two "working" surfaces before this fix (see docs/ux-audit-2026-08.md's
 * "Terminology coverage" finding and its roadmap entry "Extend terminology
 * overrides to actually cover their own surface", and the corresponding
 * entry in docs/decisions.md).
 *
 * Uses PROJECT_NAMES.delta1, a project dedicated to this spec and seeded
 * with a fixed, permanent terminology override
 * (`stage`->"Phase"/`requirement`->"Spec"/`change_request`->"ECR" — see
 * TERMINOLOGY_OVERRIDE in seed_e2e_dataset.py and helpers.ts). No set/
 * revert dance is needed here (unlike project-admin-groups-and-fields.
 * spec.ts's own, narrower proof that the *save flow* itself works, which
 * toggles a term on Beta-2 and reverts it) since Delta-1's override is
 * meant to stay in place for the life of the seeded database — no other
 * spec depends on Delta-1 being at, or away from, this override.
 */
test.describe("terminology overrides reach their own surfaces", () => {
  test("nav, requirement detail, custom-fields entity-kind dropdown, and the review-due list all reflect the override", async ({
    page,
  }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.delta1).click();

    await test.step("nav rail relabels both renamed nouns (Layout.tsx, previously one of the only 2 'working' surfaces)", async () => {
      await expect(page.getByRole("link", { name: "Specs", exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "ECRs", exact: true })).toBeVisible();
    });

    await test.step("requirement detail page: 'Make a change request' link uses the override, not the audit's named leak", async () => {
      await page.getByRole("link", { name: "Specs", exact: true }).click();
      await expect(page.url()).toContain("/requirements");
      // A bare `getByText` here is ambiguous: the seeded requirement's own
      // "Reasoning" field restates its name in lowercase prose ("Reasoning:
      // must respond to input within 50ms."), and `getByText`'s default
      // substring match is case-insensitive, so it resolves to both that
      // paragraph and the actual requirement link. Scoped to the link role
      // disambiguates that, but React Router 7's default startTransition-
      // wrapped navigation (a behavior change from 6 — the URL updates
      // immediately, but the previous page's own content can stay mounted
      // for a beat longer) can still transiently double-render *this same
      // link* while the "Specs" list settles in — `.first()` is safe here
      // since both matches share the same href/text, unlike the badge-vs-
      // filter-option ambiguity fixed elsewhere in this branch.
      await page.getByRole("link", { name: "Must respond to input within 50ms" }).first().click();
      await expect(page.url()).toContain("/requirements/");
      await expect(page.getByRole("link", { name: "Make ECR" })).toBeVisible();
    });

    await test.step("Project Admin's custom-fields entity-kind dropdown — the audit's single most visible example", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Fields & actions");
      const entityKindSelect = page.getByRole("combobox").first();
      // Default selection is "requirement" -> now renders as the override.
      await expect(entityKindSelect).toContainText("Spec");
      await entityKindSelect.selectOption("change_request");
      await expect(entityKindSelect).toContainText("ECR");
    });

    await test.step("the project's review-due list heading — the audit's named 'review-due lists' leak", async () => {
      await page.getByRole("link", { name: "Specs due for review", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Specs due for review" })).toBeVisible();
    });
  });
});
