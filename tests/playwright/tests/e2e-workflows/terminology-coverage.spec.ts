import { expect, test } from "@playwright/test";

import { loginAs, recordActionNames, openProject, PERSONAS, PROJECT_NAMES, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: C-C-03's per-project terminology overrides reach every surface that renders one of the six
 * overridable nouns, not only the nav label and list-page heading (see docs/decisions.md).
 *
 * Uses PROJECT_NAMES.delta1, a project dedicated to this spec and seeded with a fixed, permanent terminology override
 * (`stage`->"Phase"/`requirement`->"Spec"/`change_request`->"ECR"; see TERMINOLOGY_OVERRIDE in seed_e2e_dataset.py and
 * helpers.ts). No set/revert is needed (unlike project-admin-groups-and-fields.spec.ts's narrower proof of the save
 * flow on Beta-2): the override stays in place for the life of the seeded database and no other spec depends on
 * Delta-1 being at, or away from, it.
 */
test.describe("terminology overrides reach their own surfaces", () => {
  test("nav, requirement detail, custom-fields entity-kind dropdown, and the review-due list all reflect the override", async ({
    page,
  }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.delta1);

    await test.step("nav rail relabels both renamed nouns (Layout.tsx, previously one of the only 2 'working' surfaces)", async () => {
      await expect(page.getByRole("link", { name: "Specs", exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "ECRs", exact: true })).toBeVisible();
    });

    await test.step("requirement detail page: 'Make a change request' menu item uses the override, not the audit's named leak", async () => {
      await page.getByRole("link", { name: "Specs", exact: true }).click();
      await expect(page.url()).toContain("/requirements");
      // A bare `getByText` is ambiguous: the seeded requirement's "Reasoning" field restates its name in lowercase prose
      // ("Reasoning: must respond to input within 50ms."), and `getByText`'s default substring match is case-insensitive,
      // so it resolves to that paragraph and the requirement link. Scoping to the link role disambiguates, but React Router
      // 7's startTransition-wrapped navigation (the previous page's content can stay mounted for a beat) can transiently
      // double-render this link while the "Specs" list settles; `.first()` is safe since both matches share the same
      // href/text.
      await page.getByRole("link", { name: "Must respond to input within 50ms" }).first().click();
      await expect(page.url()).toContain("/requirements/");
      // The menu is drawn once the record has loaded; `recordActionNames` does not wait for it.
      await expect(page.getByRole("button", { name: "Spec actions" })).toBeVisible();
      expect(await recordActionNames(page, "Spec")).toContain("Make ECR");
    });

    await test.step("Project Admin's custom-fields entity-kind dropdown — the audit's single most visible example", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Fields & actions");
      // The section draws no empty fields: the "Applies to" select is in the "New field" dialog.
      await page.getByRole("button", { name: "New field", exact: true }).click();
      const fieldDialog = page.getByRole("dialog", { name: "New field" });
      const entityKindSelect = fieldDialog.getByLabel("Applies to", { exact: true });
      // The default selection is "requirement", rendered as the override.
      await expect(entityKindSelect).toContainText("Spec");
      await entityKindSelect.selectOption("change_request");
      await expect(entityKindSelect).toContainText("ECR");
      await page.keyboard.press("Escape");
      await expect(fieldDialog).toHaveCount(0);
    });

    await test.step("the project's review-due list heading — the audit's named 'review-due lists' leak", async () => {
      await page.getByRole("link", { name: "Specs due for review", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Specs due for review" })).toBeVisible();
    });
  });
});
