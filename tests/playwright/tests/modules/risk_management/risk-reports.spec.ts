import { readFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, createRisk, riskLevels, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: — the
 * four Risk Management reports appear in the shared Reports page (rendered by
 * the generic viewer, no custom view), show the project's risks with display
 * labels, narrow through the generated option controls, and download as PDF and
 * CSV. Also that a project with the module off offers none of them.
 *
 * Each test builds its own disposable org (see `./helpers.ts`).
 */

const REPORTS = ["Risk register", "Risk exposure", "Treatment coverage", "Review schedule"];

const picker = (page: Page) => page.getByRole("combobox", { name: "Report", exact: true });

/** A disposable org with an assessed, scored risk that has no treatment and one unscored risk. */
async function setUp(page: Page) {
  const { suffix, project, adminHeaders } = await setUpOrg(page, "RiskRep");
  const { level } = await riskLevels(page, project.id, adminHeaders);
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/risk_management/risks`;
  const titles = { scored: `Controller fails ${suffix}`, unscored: `Vague worry ${suffix}` };
  const scored = await createRisk(page, project.id, adminHeaders, {
    title: titles.scored, inherent_likelihood_level_id: level("likelihood", "Likely"),
    inherent_consequence_level_id: level("consequence", "Major"),
  });
  const moved = await page.request.post(`${base}/${scored.id}/transition`, { headers: adminHeaders, data: { status: "assessed", comment: "" } });
  expect(moved.ok(), await moved.text()).toBeTruthy();
  await createRisk(page, project.id, adminHeaders, { title: titles.unscored });
  return { project, adminHeaders, titles };
}

test.describe("Risk Management: reports", () => {
  test("the project Reports page lists the four Risk reports", async ({ page }) => {
    const { project } = await setUp(page);
    await page.goto(`/projects/${project.id}/reports`);

    await expect(picker(page)).toHaveValue("requirements");
    expect(await picker(page).locator("option").allTextContents()).toEqual(expect.arrayContaining(REPORTS));

    await picker(page).selectOption({ label: "Risk register" });
    await expect(page).toHaveURL(/report=risk-register/);
    await page.reload();
    await expect(picker(page)).toHaveValue("risk-register");
  });

  test("the register shows display labels and derived ratings, and narrows by status", async ({ page }) => {
    const { project, titles } = await setUp(page);
    await page.goto(`/projects/${project.id}/reports?report=risk-register`);

    const register = page.getByRole("region", { name: "Risks", exact: true });
    await expect(register.getByRole("row")).toHaveCount(3); // header + two risks
    const scored = register.getByRole("row", { name: new RegExp(titles.scored) });
    await expect(scored).toContainText("Assessed");
    await expect(scored).toContainText("High"); // Likely x Major, derived from the matrix
    await expect(register.getByRole("row", { name: new RegExp(titles.unscored) })).toContainText("Not rated");
    await expect(register).not.toContainText("treatment_planned");

    await page.getByRole("combobox", { name: "Status" }).selectOption({ label: "Identified" });
    await expect(register.getByRole("row")).toHaveCount(2);
    await expect(register).toContainText(titles.unscored);
    await expect(register).not.toContainText(titles.scored);
  });

  test("exposure lists unrated risks and coverage lists risks with no effective treatment", async ({ page }) => {
    const { project, titles } = await setUp(page);

    await page.goto(`/projects/${project.id}/reports?report=risk-exposure`);
    await expect(page.getByRole("region", { name: "Not rated" })).toContainText(titles.unscored);
    await expect(page.getByRole("region", { name: /Highest residual risks/ })).not.toContainText(titles.unscored);

    await page.goto(`/projects/${project.id}/reports?report=treatment-coverage`);
    const untreated = page.getByRole("region", { name: "No effective treatment" });
    await expect(untreated).toContainText(titles.scored);
    await expect(untreated).not.toContainText(titles.unscored); // Identified: not yet expected to be treated
  });

  test("the review schedule flags an assessed risk with no review date", async ({ page }) => {
    const { project, titles } = await setUp(page);
    await page.goto(`/projects/${project.id}/reports?report=review-schedule`);
    const unscheduled = page.getByRole("region", { name: "No review scheduled" });
    await expect(unscheduled).toContainText(titles.scored);
    await expect(unscheduled).not.toContainText(titles.unscored);
  });

  test("every Risk report downloads as PDF and CSV", async ({ page }) => {
    const { project, titles } = await setUp(page);
    await page.goto(`/projects/${project.id}/reports`);
    await expect(picker(page)).toHaveValue("requirements");
    const values = await picker(page).locator("option").evaluateAll((els, labels) =>
      els.filter((e) => labels.includes(e.textContent ?? "")).map((e) => ({ value: (e as HTMLOptionElement).value, label: e.textContent ?? "" })),
    REPORTS);
    expect(values).toHaveLength(4);

    for (const report of values) {
      await test.step(`${report.label}: PDF and CSV`, async () => {
        await picker(page).selectOption(report.value);
        await expect(page.getByRole("button", { name: "Export" })).toBeVisible();
        for (const kind of ["PDF", "CSV"] as const) {
          await page.getByRole("button", { name: "Export" }).click();
          const [download] = await Promise.all([
            page.waitForEvent("download"),
            page.getByRole("button", { name: `Download ${kind} report` }).click(),
          ]);
          expect(download.suggestedFilename()).toBe(`${report.value}.${kind.toLowerCase()}`);
          if (kind === "CSV" && report.value === "risk-register") {
            expect(await readFile((await download.path())!, "utf8")).toContain(titles.scored);
          }
        }
      });
    }
  });

  test("a project with the module off offers no Risk reports", async ({ page }) => {
    const { project, adminHeaders } = await setUp(page);
    const off = await page.request.put(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/risk_management/enablement`, {
      headers: adminHeaders, data: { enabled: false },
    });
    expect(off.ok(), await off.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/reports`);
    await expect(page.getByRole("button", { name: "Generate PDF" })).toBeVisible();
    await expect(picker(page)).toHaveCount(0);
  });
});
