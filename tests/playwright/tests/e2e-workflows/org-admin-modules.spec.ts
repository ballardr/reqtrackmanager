import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: module system Phase 1 (docs/compliance-module-plan.md) —
 * Org Admin's new "Modules" resource-menu group (`GET /orgs/{id}/modules`).
 *
 * Scope note: this deployment's real `INSTALLED_MODULES` registry
 * (`backend/app/modules/registry.py`) is genuinely empty until Phase 5 adds
 * the first real first-party module (Compliance) — there is no way to get a
 * real module into the registry for this Playwright run without either
 * shipping a fake production module package (explicitly against this
 * repo's own testing conventions — "do not fabricate a fake production
 * module just to test the UI") or monkeypatching backend process state,
 * which isn't reachable from a black-box e2e test against the built
 * container image. Full toggle-interaction e2e coverage (enabling an
 * entitled module, seeing a non-entitled one greyed out) is covered
 * instead at the Storybook level (`OrgAdminPage.stories.tsx`'s
 * `ModulesSection*` stories, which mock the endpoint) and the backend
 * pytest level (`backend/tests/test_module_registry.py`). This spec is
 * deliberately scoped to what's real and verifiable end-to-end today: the
 * section loads for an org admin and correctly shows the empty state.
 * Revisit once Phase 5 gives this spec a real module to toggle.
 */
test.describe("org admin: Modules section", () => {
  test("loads and shows the empty state when no modules are registered", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");

    await expect(page.getByText("No modules are registered on this deployment yet.")).toBeVisible();
  });
});
