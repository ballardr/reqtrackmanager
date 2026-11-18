import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

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
 * Creates two active connections between one pair of elements, and a diagram that places the pair, through the API (setup).
 *
 * @returns The project id, the diagram id, both element names and the connection ids in creation order.
 */
async function mergedLineSetUp(page: Page, label: string) {
  const { suffix, project, adminHeaders } = await setUpOrg(page, label, true, "System Architecture");
  const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
  const a = await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
  const b = await createElement(page.request, arch, adminHeaders, `Bravo ${suffix}`);
  const types = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
  const connectionIds: string[] = [];
  for (const name of ["First link", "Second link"]) {
    const made = await page.request.post(`${arch}/connections`, {
      headers: adminHeaders,
      data: { name, connection_type_id: types[0].id, source_element_id: a, target_element_id: b, protocol: "Long protocol name 1.0", activate: true },
    });
    expect(made.ok(), await made.text()).toBeTruthy();
    connectionIds.push((await made.json()).id);
  }
  const created = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Merged ${suffix}`, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const diagram = await created.json();
  const laid = await page.request.put(`${arch}/diagrams/${diagram.id}/layout`, {
    headers: adminHeaders,
    data: { version: diagram.version, placements: [{ element_id: a, x: 0, y: 0 }, { element_id: b, x: 400, y: 0 }], notes: [] },
  });
  expect(laid.ok(), await laid.text()).toBeTruthy();
  return { suffix, projectId: project.id as string, diagramId: diagram.id as string, connectionIds };
}

/**
 * Job to be done: an architect selects a line that stands for several connections and reads them in the Selection card, even
 * in a narrow window: each connection is a compact row (code and type, then the two ends) with its Open and Edit controls inside
 * the card, and no code is split over several lines.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements, connections and the diagram are created
 * through the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: the connections of a merged line", () => {
  test("the Selection card lists each connection as a row that fits the card at a narrow window", async ({ page }) => {
    const { suffix, projectId, diagramId } = await mergedLineSetUp(page, "ArchConRows");

    await page.setViewportSize({ width: 800, height: 900 });
    await page.goto(`/projects/${projectId}/modules/architecture/diagrams/${diagramId}`);
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
        for (const control of [row.getByRole("button").first(), row.getByRole("link").first(), row.getByRole("button").last()]) {
          const box = await control.boundingBox();
          expect(box).not.toBeNull();
          expect(box!.x).toBeGreaterThanOrEqual(cardBox!.x - 1);
          expect(box!.x + box!.width).toBeLessThanOrEqual(cardBox!.x + cardBox!.width + 1);
        }
      }
      expect(await card.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    });

    await test.step("a code is one line of text", async () => {
      const code = rows.first().getByRole("button").first().getByText(/CON-\d{3}$/);
      const lines = await code.evaluate((el) => Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)));
      expect(lines).toBe(1);
    });

    await test.step("the row's ends read from one box to the other", async () => {
      await expect(rows.first()).toContainText(`Alpha ${suffix}`);
      await expect(rows.first()).toContainText(`Bravo ${suffix}`);
    });
  });

  /**
   * Job to be done: an architect works on one connection of a merged line from the drawing: choosing its row shows that
   * connection's fields in the card (the line stays selected), an edit is stored and the row shows it, Open goes to the record's
   * page, and choosing another box ends the choice.
   */
  test("choosing a connection of a merged line edits it in the Selection card and leaves the line selected", async ({ page }) => {
    const { suffix, projectId, diagramId } = await mergedLineSetUp(page, "ArchConPick");
    await page.goto(`/projects/${projectId}/modules/architecture/diagrams/${diagramId}`);
    await expect(page.getByLabel(`Bravo ${suffix}, node`, { exact: true })).toBeVisible();
    await page.getByLabel(/^×2, connection from/).focus();
    await page.keyboard.press("Enter");

    const card = page.getByRole("region", { name: "Selection" });
    const list = card.getByRole("list", { name: "Connections of this line" });
    await expect(list.getByRole("listitem")).toHaveCount(2);

    await test.step("choosing the second row shows its fields and the line's own below", async () => {
      await list.getByRole("button", { name: /^\S*CON-002 / }).click();
      const chosen = card.getByRole("group", { name: "Chosen connection" });
      await expect(chosen.getByRole("textbox", { name: /^Name/ })).toHaveValue("Second link");
      await expect(card.getByRole("combobox", { name: "Line starts at" })).toBeVisible();
      await expect(list).toHaveCount(0);
    });

    await test.step("renaming it and saving updates its row, and Back lists both", async () => {
      const name = card.getByRole("textbox", { name: /^Name/ });
      await name.fill("Renamed link");
      const stored = page.waitForResponse((r) => r.request().method() === "PUT" && /\/connections\//.test(r.url()) && r.ok());
      await card.getByRole("button", { name: "Save connection" }).click();
      await stored;
      await expect(card.getByRole("group", { name: "Chosen connection" })).toBeVisible();
      await card.getByRole("button", { name: /^Back to the 2 connections/ }).click();
      await expect(list.getByRole("listitem")).toHaveCount(2);
      await expect(card.getByRole("button", { name: /^\S*CON-002 / })).toBeFocused();
    });

    await test.step("Open goes to the connection's record page", async () => {
      await card.getByRole("link", { name: /^Open .*CON-002$/ }).click();
      await expect(page).toHaveURL(new RegExp(`/modules/architecture/connections/`));
      await expect(page.getByRole("heading", { name: "Renamed link" })).toBeVisible();
    });

    await test.step("choosing another box ends the choice", async () => {
      await page.goto(`/projects/${projectId}/modules/architecture/diagrams/${diagramId}`);
      await page.getByLabel(/^×2, connection from/).focus();
      await page.keyboard.press("Enter");
      await card.getByRole("button", { name: /^\S*CON-001 / }).click();
      await expect(card.getByRole("group", { name: "Chosen connection" })).toBeVisible();
      await page.getByLabel(`Alpha ${suffix}, node`, { exact: true }).click();
      await expect(card.getByRole("group", { name: "Chosen connection" })).toHaveCount(0);
      await page.getByLabel(/^×2, connection from/).focus();
      await page.keyboard.press("Enter");
      await expect(list.getByRole("listitem")).toHaveCount(2);
    });
  });
});
