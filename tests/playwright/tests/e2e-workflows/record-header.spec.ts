import { expect, test, type Page } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

// Archives the disposable project after each test (see createDisposableProject).
installCleanupHook();

/**
 * Job to be done: every record's object actions live in one place, the "{Record} actions" menu at the
 * right edge of the header's title row, at every viewport width and however long the title is, so a
 * user can learn once where Archive, Restore and Subscribe are.
 *
 * Covers: the requirement and action detail pages (200-character titles) at 375, 1024 and 1440px:
 * the menu trigger sits on the title row, at the header's right edge, and opens to the record's actions.
 * Archive/Restore through the menu is covered by requirement-and-action-restore.spec.ts.
 *
 * Builds its own project and records through the API, so it depends on no shared fixture.
 */

const api = "http://localhost:8000/api/v1";
const WIDTHS = [375, 1024, 1440];
const LONG = "An exceptionally long record title that keeps going well past any sensible single line of text "
  + "so that every control placed beside it is put under real pressure to stay where it belongs";

/** The menu trigger must share the title's row and end at the header's right edge. */
async function expectMenuAtHeaderRightEdge(page: Page, recordLabel: string, width: number): Promise<void> {
  await page.setViewportSize({ width, height: 900 });
  const header = page.locator(".record-header");
  const trigger = page.getByRole("button", { name: `${recordLabel} actions` });
  await expect(trigger).toBeVisible();
  await expect.poll(async () => {
    const [h, t, title] = await Promise.all([
      header.boundingBox(), trigger.boundingBox(), header.getByRole("heading", { level: 1 }).boundingBox(),
    ]);
    if (!h || !t || !title) return "no box";
    const atRightEdge = Math.abs(h.x + h.width - (t.x + t.width)) <= 2;
    const onTitleRow = t.y >= title.y - 2 && t.y < title.y + title.height;
    return atRightEdge && onTitleRow ? "ok" : `right edge ${h.x + h.width} vs ${t.x + t.width}; title y ${title.y}-${title.y + title.height}, trigger y ${t.y}`;
  }, { message: `${recordLabel} actions at ${width}px` }).toBe("ok");
}

test.describe("record header", () => {
  test("the object-action menu is on the title row at the right edge on every width", async ({ page, request }) => {
    const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Record Header");
    const post = async (path: string, data: object) => {
      const resp = await request.post(`${api}/projects/${project.projectId}/${path}`, { headers: project.headers, data });
      expect(resp.ok()).toBeTruthy();
      return resp.json();
    };
    const requirement = await post("requirements", {
      name: `${LONG} (requirement)`, reasoning: "e2e", component_id: project.components[0].id,
      category_id: project.categories[0].id, keywords: [],
    });
    const actionTypes: { id: string }[] = await (
      await request.get(`${api}/projects/${project.projectId}/action-types`, { headers: project.headers })
    ).json();
    const action = await post("actions", { title: `${LONG} (action)`, description: "e2e", action_type_id: actionTypes[0].id });

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    const base = `/projects/${project.projectId}`;
    const pages: [string, string, string][] = [
      ["requirement", "Requirement", `${base}/requirements/${requirement.id}`],
      ["action", "Action", `${base}/actions/${action.id}`],
    ];
    for (const [label, recordLabel, url] of pages) {
      await test.step(`${label} detail`, async () => {
        await page.goto(url);
        for (const width of WIDTHS) await expectMenuAtHeaderRightEdge(page, recordLabel, width);

        await page.getByRole("button", { name: `${recordLabel} actions` }).click();
        const menu = page.getByRole("menu", { name: `${recordLabel} actions` });
        await expect(menu.getByRole("menuitem", { name: "Archive", exact: true })).toBeVisible();
        await page.keyboard.press("Escape");
      });
    }

    await test.step("requirement: Subscribe is in the menu and flips to Unsubscribe", async () => {
      await page.goto(`${base}/requirements/${requirement.id}`);
      await page.getByRole("button", { name: "Requirement actions" }).click();
      await page.getByRole("menuitem", { name: "Subscribe", exact: true }).click();
      await expect(page.getByText("Subscribed", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Requirement actions" }).click();
      await expect(page.getByRole("menuitem", { name: "Unsubscribe", exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
    });
  });
});
