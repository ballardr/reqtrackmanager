import { expect, test, type Page } from "@playwright/test";

import { gridLayout } from "../../../../frontend/src/testing/gridStability";
import { createDisposableProject, installCleanupHook, loginAs, PERSONAS, selectOrgAdminGroup } from "./helpers";
import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: long text in a grid never changes the grid's shape. Organisation Settings, Connection Types is a
 * grid of a name, a summary, colour dots and an Edit button; several rows with a name of nearly the 100-character limit and a long
 * default protocol (up to the 200-character limit) must keep the Name column its width, keep the dots and the Edit button on their own row, and keep
 * the right-hand text aligned (`gridLayout`, the same check the Storybook `LongText` stories run).
 *
 * Builds its own organisation, administrator and connection types, so it depends on no seeded state.
 */
const LONG_NAME = "An exceptionally long connection type name that keeps going well past one line of the grid";
const LONG_PROTOCOL = "A default protocol description that keeps going and going so that the summary of the row is far longer "
  + "than the space the grid has for it, which is exactly the case that broke the layout";

/** The grids on the page, measured at one width. */
async function measure(page: Page, width: number) {
  await page.setViewportSize({ width, height: 900 });
  return page.evaluate(gridLayout, undefined);
}

test("Connection Types keeps its grid when rows hold long text", async ({ page }) => {
  const { org, adminHeaders } = await setUpOrg(page, "GridText", false, "System Architecture");
  const create = async (name: string, protocol: string) => {
    const response = await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/architecture/connection-types`, {
      headers: adminHeaders,
      data: { name, line_style: "solid", directional: true, default_protocol: protocol, domain_ids: [] },
    });
    expect(response.ok()).toBeTruthy();
  };
  await create("Short", "");
  await create(`${LONG_NAME} (one)`, LONG_PROTOCOL);
  await create(`${LONG_NAME} (two)`, LONG_PROTOCOL);
  await create("Spare feed", "HTTPS");

  await page.goto(`/orgs/${org.id}/admin`);
  await selectOrgAdminGroup(page, "Connection Types", "System Architecture");
  await expect(page.getByRole("button", { name: /^Edit Short$/ })).toBeVisible();

  for (const width of [1280, 1440]) {
    await test.step(`the grid keeps its shape at ${width}px`, async () => {
      const { grids, violations } = await measure(page, width);
      expect(grids.length).toBeGreaterThan(0);
      expect(violations).toEqual([]);
    });
  }

  await test.step("every row's Edit button ends the row, in the same column", async () => {
    const boxes = await page.getByRole("button", { name: /^Edit / }).evaluateAll((buttons) => buttons.map((b) => b.getBoundingClientRect()));
    expect(boxes.length).toBeGreaterThanOrEqual(4);
    const lefts = boxes.map((b) => Math.round(b.left));
    expect(Math.max(...lefts) - Math.min(...lefts)).toBeLessThanOrEqual(1);
  });
});

/**
 * The audit of the product's own views: a project with long-named requirements, actions and a long-named component
 * and category, and the pages that list them, each measured with `gridLayout` (rules 1 to 3). Set `GRID_REPORT=1` to
 * print every grid's measurement per page. A page that fails names the grid and the rule, so the fix is made on
 * the shared component, not on the page.
 */
const api = "http://localhost:8000/api/v1";
const LONG = "An exceptionally long record title that keeps going well past any sensible single line of text "
  + "so that every control placed beside it is put under real pressure to stay where it belongs";

test("lists, tables and settings pages keep their grids with long names", async ({ page, request }) => {
  test.setTimeout(180_000);
  const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Grid Long Text");
  const post = async (path: string, data: object) => {
    const resp = await request.post(`${api}/projects/${project.projectId}/${path}`, { headers: project.headers, data });
    expect(resp.ok(), `${path}: ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };
  const [hw, fn] = [project.components[0], project.categories[0]];
  for (const n of [1, 2, 3]) {
    await post("requirements", { name: `${LONG} (${n})`, reasoning: LONG, component_id: hw.id, category_id: fn.id, keywords: [] });
  }
  // A long-named component, category and tags, for the Structure and Tags pages.
  const longComponent = await post("components", { name: `${LONG}`.slice(0, 95), prefix: "LNG" });
  await post("categories", { name: `${LONG} category`.slice(0, 95), prefix: "LNC", component_id: longComponent.id });
  for (const n of [1, 2]) await post("tags", { name: `${LONG}`.slice(0, 36).trim() + ` ${n}` });
  const actionTypes: { id: string }[] = await (await request.get(`${api}/projects/${project.projectId}/action-types`, { headers: project.headers })).json();
  for (const n of [1, 2]) await post("actions", { title: `${LONG} (${n})`, description: LONG, action_type_id: actionTypes[0].id });

  const base = `/projects/${project.projectId}`;
  const pages: [string, string][] = [
    ["requirements list", `${base}/requirements`],
    ["actions list", `${base}/actions`],
    ["change requests list", `${base}/change-requests`],
    ["project history", `${base}/history`],
    ["project admin", `${base}/admin`],
    ["project structure", `${base}/admin/structure`],
    ["project tags", `${base}/admin/tags`],
    ["project files", `${base}/files`],
    ["projects list", "/projects"],
    ["organisations list", "/orgs"],
    ["organisation admin", `/orgs/${project.organizationId}/admin`],
    ["organisation overview", `/orgs/${project.organizationId}/overview`],
    ["organisation resources", `/orgs/${project.organizationId}/resources`],
    ["preferences", "/preferences"],
  ];
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  for (const [label, url] of pages) {
    await page.goto(url);
    await page.waitForLoadState("networkidle");
    for (const width of [1280, 1440]) {
      const { grids, rowsChecked, violations } = await measure(page, width);
      if (process.env.GRID_REPORT) console.log(`GRID_REPORT ${JSON.stringify({ label, width, grids, rowsChecked, violations })}`);
      expect.soft(violations, `${label} at ${width}px`).toEqual([]);
    }
  }
});
