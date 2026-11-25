import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a record's detail page lists its cards from what the record is to what is least often needed, with
 * the comments last, so a long thread never has to be scrolled past to reach other information (docs/ux-style-guide.md,
 * "Pattern: detail page card order").
 *
 * Covers: the requirement page (Components and codes below the details, not above them; discussion last) and one
 * module page of each shape (a record with attachments and comments, a record with its own discussion block).
 *
 * Builds one disposable organisation, so it depends on no seeded state.
 */
const cardHeadings = (page: Page) => page.locator("main section.card h2.detail-card__title").allTextContents();

test("a detail page draws its cards in the default order with the comments last", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "CardOrder");
  for (const key of ["context_strategy", "decisions", "stakeholders"]) {
    const resp = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/${key}`, { headers: adminHeaders, data: { enabled: true } });
    expect(resp.ok()).toBeTruthy();
  }
  const api = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  const post = async (path: string, data: object) => {
    const resp = await page.request.post(`${api}${path}`, { headers: adminHeaders, data });
    expect(resp.ok(), `${path}: ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };
  const component = await post("/components", { name: "Software", prefix: "SW" });
  const category = await post("/categories", { name: "Performance", prefix: "PERF", component_id: component.id });
  const requirement = await post("/requirements", { name: `Report in 30 seconds ${suffix}`, component_id: component.id, category_id: category.id });
  const decisionTypes = await (await page.request.get(`${api}/modules/decisions/decision-types`, { headers: adminHeaders })).json();
  const decision = await post("/modules/decisions", { title: `Use Postgres ${suffix}`, decision_statement: "We will.", decision_type_id: decisionTypes[0].id });
  const stakeholder = await post("/modules/stakeholders/stakeholders", { name: `Pat Regulator ${suffix}` });
  const base = `/projects/${project.id}`;

  await test.step("the requirement: details, then components and codes, then supporting cards, discussion last", async () => {
    await page.goto(`${base}/requirements/${requirement.id}`);
    await expect(page.getByRole("heading", { name: "Components and codes" })).toBeVisible();
    const headings = await cardHeadings(page);
    expect(headings.indexOf("Details")).toBeGreaterThanOrEqual(0);
    expect(headings.indexOf("Details")).toBeLessThan(headings.indexOf("Components and codes"));
    expect(headings.indexOf("Components and codes")).toBeLessThan(headings.indexOf("Versions"));
    expect(headings[headings.length - 1]).toBe("Discussion");
  });

  for (const [type, path] of [["Decision", `${base}/modules/decisions/${decision.id}`], ["Stakeholder", `${base}/modules/stakeholders/stakeholders/${stakeholder.id}`]]) {
    await test.step(`the ${type} page: details first, comments last`, async () => {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: "Comments" })).toBeVisible();
      const headings = await cardHeadings(page);
      expect(headings[0]).toBe("Details");
      expect(headings[headings.length - 1]).toBe("Comments");
    });
  }
});
