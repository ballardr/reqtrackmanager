import { readFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done:
 * Playwright e2e coverage for the Stakeholders &
 * Personas reports S1-S5 in the shared Reports UI: the project report picker
 * lists all five, the S1 power/interest grid places each Stakeholder in its
 * quadrant and links to it, the S1/S4 group controls re-run the report, and
 * every report downloads as PDF and CSV.
 *
 * Each test builds its own disposable org (see `./helpers.ts`), so none depends
 * on seeded state or on another test having run.
 */

type Headers = Record<string, string>;

const REPORTS = [
  "Power/interest grid", "Persona validation", "Need coverage", "Engagement staleness", "Engagement & research yield",
];

async function post<T>(page: Page, url: string, headers: Headers, data: object): Promise<T> {
  const resp = await page.request.post(url, { headers, data });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  return (await resp.json().catch(() => ({}))) as T;
}

const projectBase = (projectId: string) => `${API_BASE_URL}/api/v1/projects/${projectId}/modules/stakeholders`;

/** The "Report" picker on the project Reports page. */
function picker(page: Page) {
  return page.getByRole("combobox", { name: "Report", exact: true });
}

/** Creates a project Stakeholder rated by level name (Low/Medium/High); either may be left unset. */
async function stakeholder(
  page: Page, headers: Headers, orgId: string, projectId: string, name: string, influence: string | null, interest: string | null,
  extra: object = {},
): Promise<{ id: string }> {
  const scheme = await (await page.request.get(`${API_BASE_URL}/api/v1/orgs/${orgId}/scoring-schemes/stakeholder`, { headers })).json();
  const level = (axis: string, label: string): string =>
    scheme.axes.find((a: { key: string }) => a.key === axis).levels.find((l: { name: string }) => l.name === label).id;
  return post(page, `${projectBase(projectId)}/stakeholders`, headers, {
    name,
    ...(influence ? { influence_level_id: level("influence", influence) } : {}),
    ...(interest ? { interest_level_id: level("interest", interest) } : {}),
    ...extra,
  });
}

test.describe("Stakeholders & Personas: Reports", () => {
  test("the project report picker lists all five reports", async ({ page }) => {
    const { project } = await setUpOrg(page, "RepPick");
    await page.goto(`/projects/${project.id}/reports`);
    await expect(picker(page)).toBeVisible();
    const options = await picker(page).locator("option").allTextContents();
    expect(options).toEqual(expect.arrayContaining(REPORTS));

    await picker(page).selectOption({ label: "Power/interest grid" });
    await expect(page).toHaveURL(/report=power-interest-grid/);
    await page.reload();
    await expect(picker(page)).toHaveValue("power-interest-grid");
  });

  test("S1 places each Stakeholder in its quadrant, links to it and lists the unscored", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "RepGrid");
    const names = {
      manage: `Sponsor ${suffix}`, satisfied: `Regulator ${suffix}`, informed: `End user ${suffix}`, monitor: `Bystander ${suffix}`,
      unscored: `Unrated ${suffix}`,
    };
    const sponsor = await stakeholder(page, adminHeaders, org.id, project.id, names.manage, "High", "High");
    await stakeholder(page, adminHeaders, org.id, project.id, names.satisfied, "High", "Low");
    await stakeholder(page, adminHeaders, org.id, project.id, names.informed, "Low", "High");
    await stakeholder(page, adminHeaders, org.id, project.id, names.monitor, "Low", "Low");
    await stakeholder(page, adminHeaders, org.id, project.id, names.unscored, "High", null);

    await page.goto(`/projects/${project.id}/reports?report=power-interest-grid`);
    const quadrant = (name: string) => page.getByRole("region", { name, exact: true });
    await expect(quadrant("Manage closely").getByRole("link", { name: names.manage })).toBeVisible();
    await expect(quadrant("Keep satisfied").getByText(names.satisfied)).toBeVisible();
    await expect(quadrant("Keep informed").getByText(names.informed)).toBeVisible();
    await expect(quadrant("Monitor").getByText(names.monitor)).toBeVisible();
    await expect(quadrant("Not scored").getByText(names.unscored)).toBeVisible();
    // The quadrant names are labels, never the wire keys.
    await expect(page.getByText("manage_closely")).toHaveCount(0);

    await quadrant("Manage closely").getByRole("link", { name: names.manage }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/stakeholders/${sponsor.id}$`));
  });

  test("the S1 and S4 group controls narrow the run and the view owns the parameter", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "RepGroup");
    const inside = `Inside ${suffix}`;
    const outside = `Outside ${suffix}`;
    const group = await post<{ id: string }>(page, `${projectBase(project.id)}/stakeholder-groups`, adminHeaders, { name: `Team ${suffix}` });
    const member = await stakeholder(page, adminHeaders, org.id, project.id, inside, "High", "High", { target_cadence: "weekly" });
    await stakeholder(page, adminHeaders, org.id, project.id, outside, "High", "High", { target_cadence: "weekly" });
    await post(page, `${projectBase(project.id)}/stakeholder-groups/${group.id}/members`, adminHeaders, { stakeholder_id: member.id });

    await page.goto(`/projects/${project.id}/reports?report=power-interest-grid`);
    await expect(page.getByRole("region", { name: "Manage closely" }).getByText(outside)).toBeVisible();
    // The view draws the group controls itself, so the generic form shows no raw id box for them.
    await expect(page.getByLabel("Group", { exact: true })).toHaveCount(1);
    const narrowed = page.waitForRequest((r) => r.url().includes("power-interest-grid") && r.url().includes(`group_id=${group.id}`));
    await page.getByLabel("Group", { exact: true }).selectOption({ label: `Team ${suffix}` });
    await narrowed;
    await expect(page.getByText(outside)).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Manage closely" }).getByText(inside)).toBeVisible();

    await picker(page).selectOption({ label: "Engagement staleness" });
    await expect(page.getByLabel("Group", { exact: true })).toHaveCount(1);
    const stale = page.waitForRequest((r) => r.url().includes("engagement-staleness") && r.url().includes(`group_id=${group.id}`));
    await page.getByLabel("Group", { exact: true }).selectOption({ label: `Team ${suffix}` });
    await stale;
    await expect(page.getByText(outside)).toHaveCount(0); // waits for the narrowed result to replace the full one
    const overdue = page.getByRole("region", { name: "Overdue for engagement" });
    await expect(overdue.getByText(inside)).toBeVisible();
    await expect(overdue.getByRole("cell", { name: "Never engaged" })).toBeVisible();
  });

  test("every Stakeholders & Personas report downloads as PDF and CSV", async ({ page }) => {
    const { org, project, adminHeaders, suffix } = await setUpOrg(page, "RepDownload");
    await stakeholder(page, adminHeaders, org.id, project.id, `Downloader ${suffix}`, "High", "High", { target_cadence: "weekly" });
    await page.goto(`/projects/${project.id}/reports`);
    await expect(picker(page)).toBeVisible();

    for (const title of REPORTS) {
      await test.step(`${title}: PDF and CSV`, async () => {
        await picker(page).selectOption({ label: title });
        await expect(page.getByRole("button", { name: "Export" })).toBeVisible();
        for (const kind of ["PDF", "CSV"] as const) {
          await page.getByRole("button", { name: "Export" }).click();
          const [download] = await Promise.all([
            page.waitForEvent("download"),
            page.getByRole("button", { name: `Download ${kind} report` }).click(),
          ]);
          expect(download.suggestedFilename()).toMatch(new RegExp(`\\.${kind.toLowerCase()}$`));
          await expect(page.getByText(`Downloaded ${title} (${kind}).`)).toBeVisible();
          if (kind === "CSV" && title === "Power/interest grid") {
            // A report names each record by its code, and lists its tags.
            const csv = await readFile((await download.path())!, "utf8");
            expect(csv.split("\n")[0]).toMatch(/^Code,Stakeholder,.*,Tags\r?$/);
            expect(csv).toContain("STK-001,");
          }
        }
      });
    }
  });
  test("S1 caps a crowded quadrant at ten and shows the rest in a scrolling modal", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "RepCap");
    for (let i = 1; i <= 12; i++) {
      await stakeholder(page, adminHeaders, org.id, project.id, `Crowd ${String(i).padStart(2, "0")} ${suffix}`, "High", "High");
    }
    await page.goto(`/projects/${project.id}/reports?report=power-interest-grid`);
    const manage = page.getByRole("region", { name: "Manage closely", exact: true });
    await expect(manage.getByRole("listitem")).toHaveCount(10);
    await manage.getByRole("button", { name: "Show all 12 Stakeholders" }).click();
    const dialog = page.getByRole("dialog", { name: "Manage closely" });
    await expect(dialog.getByRole("listitem")).toHaveCount(12);
    await expect(dialog.getByRole("link", { name: `Crowd 12 ${suffix}` })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });
});
