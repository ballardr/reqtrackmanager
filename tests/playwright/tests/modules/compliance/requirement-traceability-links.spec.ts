import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: Compliance Module Phase 34 (docs/compliance-module-plan.md)
 * — a traceability link between a core `Requirement` and a compliance
 * standard's own `ComplianceRequirement` can be created from the core
 * requirement's own detail page (the primary, V1 flow — see that phase's
 * own "initiating from the compliance-requirement side... deliberately out
 * of scope" note) and is visible from that requirement afterward, alongside
 * its own core-to-core `RequirementLink`s in the same Links card.
 *
 * Every fixture this spec creates (standard, version, compliance
 * requirement, core requirement) is dynamically named with a per-run
 * timestamp suffix, per this repo's standing test-idempotency rule —
 * nothing here mutates or depends on another spec's named fixtures.
 */
test.describe("Compliance Module: core requirement <-> compliance requirement traceability links (Phase 34)", () => {
  test("add a traceability link from a core requirement's Links card and see it rendered", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-TRACE-${suffix}`;
    const standardName = `E2E Traceability Standard ${suffix}`;
    const complianceRequirementReference = `TR.${suffix}`;
    const complianceRequirementName = `E2E Logical Access Control ${suffix}`;
    const coreRequirementName = `E2E Traceability Core Requirement ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    // --- Author a compliance standard/version/requirement to link to, via
    // the top-level `/standards` page (same flow `project-compliance-view
    // .spec.ts` uses) — no need to publish it, since the traceability
    // picker (`RequirementTraceabilityLinksSection.tsx`) lists an org's
    // standards/versions/requirements regardless of lifecycle status.
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });
    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.getByRole("button", { name: "Add requirement" }).click();
    const newRequirementDialog = page.getByRole("dialog", { name: "New requirement" });
    await newRequirementDialog.getByLabel("Reference").fill(complianceRequirementReference);
    await newRequirementDialog.getByLabel("Requirement name").fill(complianceRequirementName);
    await newRequirementDialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(complianceRequirementName)).toBeVisible();

    // --- A fresh core requirement in Alpha-1, so this spec never mutates
    // a seeded/shared requirement's own links.
    await page.goto("/projects");
    await page.getByRole("link", { name: PROJECT_NAMES.alpha1 }).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill(coreRequirementName);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.getByText(coreRequirementName).click();
    await expect(page.getByRole("heading", { name: coreRequirementName })).toBeVisible();

    await test.step("add a compliance link via the Links card's 'Add compliance link' picker", async () => {
      await page.getByRole("button", { name: "Add compliance link" }).click();
      const popover = page.getByRole("dialog", { name: "Add compliance link" });
      await popover.getByLabel("Standard").selectOption({ label: `${reference} — ${standardName}` });
      await popover.getByLabel("Version").selectOption({ label: "v1.0" });
      await popover.getByLabel("Requirement").selectOption({ label: `${complianceRequirementReference} — ${complianceRequirementName}` });
      await popover.getByLabel("Link type").selectOption({ index: 1 });
      await popover.getByRole("button", { name: "Add link" }).click();
      await expect(popover).not.toBeVisible();
    });

    await expect(page.getByText(new RegExp(complianceRequirementName))).toBeVisible();
    await expect(page.getByText(new RegExp(`${standardName}`))).toBeVisible();

    // --- Reloading the page re-fetches the link from the backend rather
    // than relying on client-only state, confirming it's genuinely
    // persisted, not just an optimistic local update.
    await page.reload();
    await expect(page.getByText(new RegExp(complianceRequirementName))).toBeVisible();
  });
});
