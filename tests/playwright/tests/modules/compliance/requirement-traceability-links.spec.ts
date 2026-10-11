import { expect, test } from "@playwright/test";

import { loginAs, openProject, openRequirementByName, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: a core requirement traces to the compliance standard's clause it
 * satisfies. The clause is an ordinary link target (docs/plans/platform-enhancements-
 * 2026-10-plan.md Phase 6c, replacing Compliance Phase 34's own table and section): it is
 * found from the shared Links panel's "Add a link" finder, either by searching its text
 * across every record type or by narrowing step by step (Standard -> Version ->
 * Requirement), appears in the panel under the clause's record type, survives a reload,
 * and is removed like any other link.
 *
 * Every fixture this spec creates (standard, version, clause, core requirement) is
 * dynamically named with a per-run timestamp suffix, per this repo's standing
 * test-idempotency rule — nothing here mutates or depends on another spec's named fixtures.
 */
test.describe("Compliance: core requirement <-> standard clause links through the Links panel", () => {
  test("find a clause by searching and by narrowing, link it, see it persist and remove it", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-TRACE-${suffix}`;
    const standardName = `E2E Traceability Standard ${suffix}`;
    const clauseReference = `TR.${suffix}`;
    const clauseName = `E2E Logical Access Control ${suffix}`;
    const coreRequirementName = `E2E Traceability Core Requirement ${suffix}`;
    const clauseLabel = `${reference} v1.0 · ${clauseReference} ${clauseName}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await test.step("author a standard, version and clause to link to", async () => {
      await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });
      await page.getByRole("link", { name: "Versions", exact: true }).click();
      await page.getByRole("button", { name: "v1.0" }).click();
      await page.getByRole("button", { name: "Add requirement" }).click();
      const newRequirementDialog = page.getByRole("dialog", { name: "New requirement" });
      await newRequirementDialog.getByLabel("Reference").fill(clauseReference);
      await newRequirementDialog.getByLabel("Requirement name").fill(clauseName);
      await newRequirementDialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText(clauseName)).toBeVisible();
    });

    await test.step("a fresh core requirement in Alpha-1, so no seeded requirement's links change", async () => {
      await page.goto("/projects");
      await openProject(page, PROJECT_NAMES.alpha1);
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("button", { name: "New requirement" }).click();
      await page.getByPlaceholder("Name", { exact: true }).fill(coreRequirementName);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await openRequirementByName(page, coreRequirementName);
      await expect(page.getByRole("heading", { name: coreRequirementName })).toBeVisible();
    });

    const panel = page.getByRole("region", { name: "Links", exact: true });
    const dialog = page.getByRole("dialog", { name: "Add a link" });

    await test.step("searching the clause's text across every record type finds it, labelled with its type", async () => {
      await panel.getByRole("button", { name: "Add link" }).click();
      await expect(dialog.getByText(/Type at least two characters to search every record type/)).toBeVisible();
      await dialog.getByLabel("Search").fill(clauseReference);
      const found = dialog.getByLabel("Record").locator("option", { hasText: clauseName });
      await expect(found).toHaveCount(1);
      await expect(found).toHaveText(`Compliance standard clause: ${clauseLabel}`);
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).not.toBeVisible();
    });

    await test.step("narrowing Standard -> Version -> Requirement lists the clause, then link it", async () => {
      await panel.getByRole("button", { name: "Add link" }).click();
      await dialog.getByLabel("Link to").selectOption({ label: "Compliance standard clause" });
      await dialog.getByLabel("Standard", { exact: true }).selectOption({ label: `${reference} ${standardName}` });
      await dialog.getByLabel("Version", { exact: true }).selectOption({ label: "v1.0" });
      // The last level narrows to exactly one clause.
      await dialog.getByLabel("Requirement", { exact: true }).selectOption({ label: `${clauseReference} ${clauseName}` });
      const record = dialog.getByLabel("Record");
      await expect(record.locator("option", { hasText: clauseName })).toHaveCount(1);
      await record.selectOption({ label: clauseLabel });
      await dialog.getByLabel("Relationship").selectOption({ label: "Derives from" });
      await dialog.getByRole("button", { name: "Add link" }).click();
      await expect(dialog).not.toBeVisible();
    });

    await test.step("the panel lists the clause under its record type, and it is still there after a reload", async () => {
      await expect(panel.getByRole("heading", { name: "Compliance standard clause" })).toBeVisible();
      await expect(panel.getByText(clauseLabel)).toBeVisible();
      await page.reload();
      await expect(panel.getByText(clauseLabel)).toBeVisible();
      await expect(panel.locator("span.badge", { hasText: "Derives from" })).toBeVisible();
    });

    await test.step("removing the link goes through the usual confirmation", async () => {
      await panel.getByRole("button", { name: new RegExp(`^Remove link: Derives from ${reference}`) }).click();
      await page.getByRole("dialog", { name: "Remove this link?" }).getByRole("button", { name: "Remove link" }).click();
      await expect(panel.getByText(clauseLabel)).toHaveCount(0);
    });
  });
});
