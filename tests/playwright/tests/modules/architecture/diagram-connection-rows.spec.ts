import { expect, test, type APIRequestContext } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

type Headers = Record<string, string>;

/** Creates an active element through the API (setup) and returns its id. */
async function createElement(request: APIRequestContext, base: string, headers: Headers, name: string): Promise<string> {
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/**
 * Job to be done: an architect selects a line that stands for several connections and reads them in the Selection card, even
 * in a narrow window: each connection is a compact row (code and type, then the two ends) with its Edit control inside the card,
 * and no code is split over several lines.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements, connections and the diagram are created
 * through the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: the connections of a merged line", () => {
  test("the Selection card lists each connection as a row that fits the card at a narrow window", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchConRows", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const a = await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
    const b = await createElement(page.request, arch, adminHeaders, `Bravo ${suffix}`);
    const types = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
    for (const name of ["First link", "Second link"]) {
      const made = await page.request.post(`${arch}/connections`, {
        headers: adminHeaders,
        data: { name, connection_type_id: types[0].id, source_element_id: a, target_element_id: b, protocol: "Long protocol name 1.0", activate: true },
      });
      expect(made.ok(), await made.text()).toBeTruthy();
    }
    const created = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Merged ${suffix}`, activate: true } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    const laid = await page.request.put(`${arch}/diagrams/${diagram.id}/layout`, {
      headers: adminHeaders,
      data: { version: diagram.version, placements: [{ element_id: a, x: 0, y: 0 }, { element_id: b, x: 400, y: 0 }], notes: [] },
    });
    expect(laid.ok(), await laid.text()).toBeTruthy();

    await page.setViewportSize({ width: 800, height: 900 });
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`Bravo ${suffix}, node`, { exact: true })).toBeVisible();
    await page.getByLabel(/^×2, connection from/).focus();
    await page.keyboard.press("Enter");

    const card = page.getByRole("region", { name: "Selection" });
    const rows = card.getByRole("list", { name: "Connections of this line" }).getByRole("listitem");
    await expect(rows).toHaveCount(2);

    await test.step("every row, code and Edit control lies inside the card", async () => {
      const cardBox = await card.boundingBox();
      expect(cardBox).not.toBeNull();
      for (let i = 0; i < 2; i += 1) {
        const row = rows.nth(i);
        for (const control of [row.getByRole("link").first(), row.getByRole("button").first()]) {
          const box = await control.boundingBox();
          expect(box).not.toBeNull();
          expect(box!.x).toBeGreaterThanOrEqual(cardBox!.x - 1);
          expect(box!.x + box!.width).toBeLessThanOrEqual(cardBox!.x + cardBox!.width + 1);
        }
      }
      expect(await card.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    });

    await test.step("a code is one line of text", async () => {
      const code = rows.first().getByRole("link").first();
      const lines = await code.evaluate((el) => Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)));
      expect(lines).toBe(1);
    });

    await test.step("the row's ends read from one box to the other", async () => {
      await expect(rows.first()).toContainText(`Alpha ${suffix}`);
      await expect(rows.first()).toContainText(`Bravo ${suffix}`);
    });
  });
});
