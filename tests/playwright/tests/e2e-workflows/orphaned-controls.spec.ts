import { expect, test, type Page } from "@playwright/test";

import { iconSizeGeometry } from "../../../../frontend/src/testing/iconSizes";
import { controlGeometry } from "../../../../frontend/src/testing/orphanedControls";
import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

// Archives the disposable project after each test (see createDisposableProject).
installCleanupHook();

/**
 * Job to be done: a record with a very long title, or a status with a long name, must not push its
 * Delete/Edit control onto a new line or make a pill change height. Text wraps; the controls beside
 * it do not.
 *
 * Also asserts every icon inside a button is the size its button calls for (16px medium, 14px small;
 * `iconSizeGeometry`, the same check the Storybook stories run). Set `ICON_REPORT=1` to print each
 * icon measurement per page.
 *
 * Covers: the main project lists and detail pages (with a 200-character requirement name and action
 * title, one link between two such requirements) and the admin pages, at 1280px and 1440px, against
 * `orphanedControlViolations` (the same check the Storybook stories run).
 *
 * Builds its own project and long-titled records through the API, so it depends on no shared fixture
 * or earlier run. Set `ORPHAN_REPORT=1` to print every pill and button measurement for the pages
 * visited (the baseline table for the layout contract).
 */

const api = "http://localhost:8000/api/v1";
const WIDTHS = [1280, 1440];
const LONG = "An exceptionally long record title that keeps going well past any sensible single line of text "
  + "so that every control placed beside it is put under real pressure to stay where it belongs";

async function expectNoOrphans(page: Page, label: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    // Polled: a resize re-renders responsive chrome over a few frames; a real defect stays wrong.
    await expect.soft
      .poll(async () => (await page.evaluate(controlGeometry, undefined)).violations, {
        message: `${label} at ${width}px`, timeout: 5_000,
      })
      .toEqual([]);
  }
}

/** Prints every pill and button measurement for the page (the baseline table), when asked. */
async function reportControls(page: Page, label: string): Promise<void> {
  if (!process.env.ORPHAN_REPORT) return;
  await page.setViewportSize({ width: 1280, height: 900 });
  const { measurements, violations } = await page.evaluate(controlGeometry, undefined);
  console.log(`ORPHAN_REPORT ${JSON.stringify({ label, measurements, violations })}`);
}

/** Asserts every icon in a button is the size the button's size calls for. */
async function expectButtonIconsSized(page: Page, label: string): Promise<void> {
  await page.setViewportSize({ width: 1280, height: 900 });
  const { measurements, violations } = await page.evaluate(iconSizeGeometry, undefined);
  if (process.env.ICON_REPORT) console.log(`ICON_REPORT ${JSON.stringify({ label, measurements, violations })}`);
  expect.soft(violations, `${label}: button icon sizes`).toEqual([]);
}

test.describe("controls beside long text", () => {
  test("long titles never orphan a control or stretch a pill", async ({ page, request }) => {
    const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Long Titles");
    const post = async (path: string, data: object) => {
      const resp = await request.post(`${api}/projects/${project.projectId}/${path}`, { headers: project.headers, data });
      expect(resp.ok()).toBeTruthy();
      return resp.json();
    };
    const [hw, fn] = [project.components[0], project.categories[0]];
    const requirement = async (name: string) =>
      post("requirements", { name, reasoning: "e2e", component_id: hw.id, category_id: fn.id, keywords: [] });
    const first = await requirement(`${LONG} (first)`);
    const second = await requirement(`${LONG} (second)`);

    const options: { link_type_id: string; direction: string; other_types: { key?: string; type?: string }[] }[] = await (
      await request.get(`${api}/projects/${project.projectId}/artefacts/requirement/${first.id}/link-types`, { headers: project.headers })
    ).json();
    const option = options.find((o) => o.direction === "outgoing")!;
    const linkResp = await request.post(`${api}/projects/${project.projectId}/artefacts/requirement/${first.id}/links`, {
      headers: project.headers,
      data: { link_type_id: option.link_type_id, direction: "outgoing", other_type: "requirement", other_id: second.id },
    });
    expect(linkResp.ok()).toBeTruthy();

    const actionTypes: { id: string }[] = await (
      await request.get(`${api}/projects/${project.projectId}/action-types`, { headers: project.headers })
    ).json();
    const action = await post("actions", { title: `${LONG} (action)`, description: LONG, action_type_id: actionTypes[0].id });

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    const base = `/projects/${project.projectId}`;
    const pages: [string, string][] = [
      ["project overview", base],
      ["requirements list", `${base}/requirements`],
      ["requirement detail", `${base}/requirements/${first.id}`],
      ["actions list", `${base}/actions`],
      ["action detail", `${base}/actions/${action.id}`],
      ["change requests list", `${base}/change-requests`],
      ["project history", `${base}/history`],
      ["project admin", `${base}/admin`],
      ["project files", `${base}/files`],
      ["reports dialog", `${base}?reports=choose`],
      ["projects list", "/projects"],
      ["organisations list", "/orgs"],
      ["organisation admin", `/orgs/${project.organizationId}/admin`],
      ["organisation overview", `/orgs/${project.organizationId}/overview`],
      ["preferences", "/preferences"],
    ];
    for (const [label, url] of pages) {
      await test.step(label, async () => {
        await page.goto(url);
        await page.waitForLoadState("networkidle");
        await reportControls(page, label);
        await expectNoOrphans(page, label);
        await expectButtonIconsSized(page, label);
      });
    }
  });
});
