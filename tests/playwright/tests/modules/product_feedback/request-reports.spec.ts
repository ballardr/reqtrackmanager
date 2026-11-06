import { readFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { chooseReport, listReports, reportPickerButton } from "../../e2e-workflows/reportPicker";
import { pickReportFormat, reportDownloadButton } from "../../reportDownload";
import { createRequest, projectBase, requestLevels, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a triager asks the shared Reports page the cross-cutting questions about enhancement requests:
 * which open requests rank highest and which of them rest on no problem, which requests are waiting to be decided,
 * and downloads each report. The reports are rendered by the generic viewer (no custom view).
 *
 * Each test builds its own disposable org (see `./helpers.ts`).
 */

/** The five Product Feedback reports: the file name (the URL slug) and the title the picker shows. */
const REPORTS = [
  { slug: "demand-ranking", title: "Demand ranking" },
  { slug: "unlinked-requests", title: "Unlinked requests" },
  { slug: "close-the-loop", title: "Close the loop" },
  { slug: "triage-ageing", title: "Triage ageing" },
  { slug: "problem-demand", title: "Problem demand" },
];

/** A disposable org with a scored request, an unscored one and a declined one (which no open-request report lists). */
async function setUp(page: Page) {
  const { suffix, project, adminHeaders } = await setUpOrg(page, "FeedbackRep");
  const base = projectBase(project.id);
  const { level } = await requestLevels(page, project.id, adminHeaders);
  const titles = { scored: `Scored ask ${suffix}`, unscored: `Unscored ask ${suffix}`, declined: `Declined ask ${suffix}` };
  const scored = await createRequest(page, base, adminHeaders, {
    title: titles.scored,
    levels: {
      reach: level("reach", "Many"), impact: level("impact", "High"), confidence: level("confidence", "High"),
      ease: level("ease", "Easy"), effort: level("effort", "Medium"),
    },
  });
  await createRequest(page, base, adminHeaders, { title: titles.unscored });
  const declined = await createRequest(page, base, adminHeaders, { title: titles.declined });
  const moved = await page.request.post(`${base}/requests/${declined.id}/transition`, {
    headers: adminHeaders, data: { status: "declined", comment: "Out of scope" },
  });
  expect(moved.ok(), await moved.text()).toBeTruthy();
  return { project, adminHeaders, titles, scored };
}

test.describe("Enhancement requests: reports", () => {
  test("the project Reports page lists the five reports", async ({ page }) => {
    const { project } = await setUp(page);
    await page.goto(`/projects/${project.id}?reports=choose`);

    await expect(reportPickerButton(page)).toHaveAttribute("aria-label", "Report: Requirements report");
    expect(await listReports(page)).toEqual(expect.arrayContaining(REPORTS.map((r) => r.title)));

    await chooseReport(page, "Demand ranking");
    await expect(page).toHaveURL(/report=demand-ranking/);
    await page.reload();
    await expect(reportPickerButton(page)).toHaveAttribute("aria-label", "Report: Demand ranking");
  });

  test("the demand ranking lists open requests, flags a request with no Pain Point and marks the unscored", async ({ page }) => {
    const { project, titles } = await setUp(page);
    await page.goto(`/projects/${project.id}?reports=choose&report=demand-ranking`);

    const ranking = page.getByRole("region", { name: "Open requests", exact: true });
    await expect(ranking.getByRole("row")).toHaveCount(3); // header + the two open requests
    await expect(ranking).not.toContainText(titles.declined);
    const scored = ranking.getByRole("row", { name: new RegExp(titles.scored) });
    await expect(scored).toContainText("No Pain Point");
    await expect(scored).toContainText("%"); // a score, as a share of the best possible
    await expect(ranking.getByRole("row", { name: new RegExp(titles.unscored) })).toContainText("Not scored");
  });

  test("unlinked requests and triage ageing read the same requests as the list", async ({ page }) => {
    const { project, titles } = await setUp(page);

    await page.goto(`/projects/${project.id}?reports=choose&report=unlinked-requests`);
    const unlinked = page.getByRole("region", { name: "Requests with no Pain Point" });
    await expect(unlinked).toContainText(titles.scored);
    await expect(unlinked).toContainText(titles.unscored);
    await expect(unlinked).not.toContainText(titles.declined);

    await page.goto(`/projects/${project.id}?reports=choose&report=triage-ageing`);
    const summary = page.getByRole("region", { name: "By status" });
    await expect(summary.getByRole("row", { name: /^New/ })).toContainText("2"); // both open requests are still New
  });

  test("every report downloads as PDF and CSV", async ({ page }) => {
    const { project, titles } = await setUp(page);
    await page.goto(`/projects/${project.id}?reports=choose`);
    await expect(reportPickerButton(page)).toHaveAttribute("aria-label", "Report: Requirements report");
    const offered = await listReports(page);
    expect(REPORTS.filter((r) => offered.includes(r.title))).toHaveLength(5);

    for (const report of REPORTS) {
      await test.step(`${report.title}: PDF and CSV`, async () => {
        await chooseReport(page, report.title);
        await expect(reportDownloadButton(page)).toBeVisible();
        for (const kind of ["PDF", "CSV"] as const) {
          await pickReportFormat(page, kind);
          const [download] = await Promise.all([
            page.waitForEvent("download"),
            reportDownloadButton(page).click(),
          ]);
          expect(download.suggestedFilename()).toBe(`${report.slug}.${kind.toLowerCase()}`);
          if (kind === "CSV" && report.slug === "demand-ranking") {
            const csv = await readFile((await download.path())!, "utf8");
            expect(csv).toContain(titles.scored);
            // A report names each request by its code, and lists its tags.
            expect(csv.split("\n")[0]).toMatch(/^Rank,Code,Request,.*,Tags/);
            expect(csv).toContain("ENH-001");
          }
        }
      });
    }
  });
});
