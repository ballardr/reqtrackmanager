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

/** Drags from one screen position to another with the real mouse. */
async function drag(page: Page, from: { x: number; y: number }, to: { x: number; y: number }) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move((from.x + to.x) / 2, (from.y + to.y) / 2, { steps: 5 });
  await page.mouse.move(to.x, to.y, { steps: 5 });
  await page.mouse.up();
}

async function centre(page: Page, selector: string) {
  const box = (await page.locator(selector).first().boundingBox())!;
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

/**
 * Creates two active connections between one pair of elements, and a diagram that places the pair, through the API (setup).
 *
 * @returns The project id, the diagram id, the element names' suffix, the element ids and the connection ids in creation order.
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
      data: { name, connection_type_id: types[0].id, source_element_id: a, target_element_id: b, activate: true },
    });
    expect(made.ok(), await made.text()).toBeTruthy();
    connectionIds.push((await made.json()).id);
  }
  const created = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Routes ${suffix}`, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const diagram = await created.json();
  const laid = await page.request.put(`${arch}/diagrams/${diagram.id}/layout`, {
    headers: adminHeaders,
    data: { version: diagram.version, placements: [{ element_id: a, x: 0, y: 0 }, { element_id: b, x: 400, y: 0 }], notes: [] },
  });
  expect(laid.ok(), await laid.text()).toBeTruthy();
  return { suffix, projectId: project.id as string, diagramId: diagram.id as string, connectionIds, arch, adminHeaders };
}

/**
 * Job to be done: an architect routes one connection of a merged line without moving the others. With a connection chosen in
 * the Selection card, dragging the line's segment adds a vertex to that connection only: it becomes a line of its own, stays
 * selected and keeps its route after a save and a reload, while the other connection keeps the straight line. Using the shared
 * route draws it with the other again.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements, connections and the diagram are created
 * through the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: a route per connection", () => {
  test("dragging a vertex with one connection chosen routes that connection only, and it survives a save and a reload", async ({ page }) => {
    const { suffix, projectId, diagramId, connectionIds, arch, adminHeaders } = await mergedLineSetUp(page, "ArchOwnRoute");
    await page.goto(`/projects/${projectId}/modules/architecture/diagrams/${diagramId}`);
    await expect(page.getByLabel(`Bravo ${suffix}, node`, { exact: true })).toBeVisible();
    await page.getByLabel(/^×2, connection from/).focus();
    await page.keyboard.press("Enter");

    const card = page.getByRole("region", { name: "Selection" });
    await card.getByRole("list", { name: "Connections of this line" }).getByRole("button", { name: /^\S*CON-002 / }).click();
    await expect(card.getByText(/^Route of \S*CON-002$/)).toBeVisible();

    await test.step("dragging the middle of the line adds a vertex, and the connection becomes a line of its own", async () => {
      // Choosing a row scrolls the page down to the card, so the line is brought back into view before the pointer drags it.
      await page.locator(".graph-segment-handle").first().scrollIntoViewIfNeeded();
      const from = await centre(page, ".graph-segment-handle");
      await drag(page, from, { x: from.x, y: from.y - 110 });
      await expect(page.locator(".react-flow__edge")).toHaveCount(2);
      await expect(page.locator(".graph-waypoint")).toHaveCount(1);
      await expect(card.getByRole("group", { name: "Chosen connection" })).toHaveCount(0);
      await expect(card.getByRole("spinbutton", { name: "Vertex 1 X" })).toBeVisible();
      await expect(card.getByRole("button", { name: "Use the shared route" })).toBeVisible();
    });

    await test.step("Save stores the route for the connection, not for the pair", async () => {
      const saved = page.waitForResponse((r) => r.url().includes(`/diagrams/${diagramId}/layout`) && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save diagram", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      const view = await (await page.request.get(`${arch}/diagrams/${diagramId}/view`, { headers: adminHeaders })).json();
      expect(view.anchors).toHaveLength(1);
      expect(view.anchors[0].connection_id).toBe(connectionIds[1]);
      expect(view.anchors[0].points).toHaveLength(1);
      expect(view.edges).toHaveLength(2);
    });

    await test.step("a reload draws two lines, one routed through the vertex", async () => {
      await page.reload();
      await expect(page.getByLabel(`Bravo ${suffix}, node`, { exact: true })).toBeVisible();
      await expect(page.locator(".react-flow__edge")).toHaveCount(2);
    });

    await test.step("using the shared route merges the connection back into one line", async () => {
      await page.locator(".react-flow__edge").first().focus();
      await page.keyboard.press("Enter");
      let shared = card.getByRole("button", { name: "Use the shared route" });
      if (!(await shared.isVisible())) {
        await page.locator(".react-flow__edge").nth(1).focus();
        await page.keyboard.press("Enter");
        shared = card.getByRole("button", { name: "Use the shared route" });
      }
      await shared.click();
      await expect(page.locator(".react-flow__edge")).toHaveCount(1);
      const removed = page.waitForResponse((r) => r.url().includes(`/diagrams/${diagramId}/layout`) && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save diagram", exact: true }).click();
      expect((await removed).ok()).toBeTruthy();
      const view = await (await page.request.get(`${arch}/diagrams/${diagramId}/view`, { headers: adminHeaders })).json();
      expect(view.anchors).toHaveLength(0);
      expect(view.edges).toHaveLength(1);
    });
  });
});
