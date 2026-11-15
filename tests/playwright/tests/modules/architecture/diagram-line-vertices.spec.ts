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

/** The numbers of a line's path, in order (a straight line with `n` vertices has `2 * (n + 2)` of them). */
async function pathNumbers(page: Page, edge: string): Promise<number[]> {
  const d = (await page.locator(`.react-flow__edge[data-id="${edge}"] path.react-flow__edge-path`).getAttribute("d")) ?? "";
  return (d.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
}

/** Selects a line the way the keyboard does: focus it and press Enter (the line is a thin target for a pointer). */
async function selectLine(page: Page, edge: string) {
  await page.locator(`.react-flow__edge[data-id="${edge}"]`).focus();
  await page.keyboard.press("Enter");
}

/** Drags from one screen position to another with the real mouse. */
async function drag(page: Page, from: { x: number; y: number }, to: { x: number; y: number }) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move((from.x + to.x) / 2, (from.y + to.y) / 2, { steps: 5 });
  await page.mouse.move(to.x, to.y, { steps: 5 });
  await page.mouse.up();
}

async function centre(page: Page, selector: string, index = 0) {
  const box = (await page.locator(selector).nth(index).boundingBox())!;
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

/**
 * Job to be done: an architect routes a line around another box. They drag the middle of the selected line to add a vertex,
 * drag a vertex to move it, remove it by double-click or Delete, and use the Selection card's Vertices list when they cannot
 * drag; the route is stored with the drawing and survives a reload, on a block diagram and on a state machine diagram alike.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements, connections and diagrams are
 * created through the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: vertices on lines", () => {
  test("a block diagram line gets a vertex by dragging, keeps it after a save and a reload, and loses it by double-click", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchVertex", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const alpha = await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
    const bravo = await createElement(page.request, arch, adminHeaders, `Bravo ${suffix}`);
    const types = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
    const connection = await page.request.post(`${arch}/connections`, {
      headers: adminHeaders, data: { connection_type_id: types[0].id, source_element_id: alpha, target_element_id: bravo, activate: true },
    });
    expect(connection.ok(), await connection.text()).toBeTruthy();
    const made = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const diagram = await made.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`Alpha ${suffix}, node`, { exact: true })).toBeVisible();

    const line = page.locator(".react-flow__edge").first();
    await expect(line).toBeVisible();
    const edgeId = (await line.getAttribute("data-id"))!;

    await test.step("selecting the line shows a handle on the middle of its one segment and no vertex", async () => {
      await selectLine(page, edgeId);
      await expect(page.locator(".graph-segment-handle")).toHaveCount(1);
      await expect(page.locator(".graph-waypoint")).toHaveCount(0);
      expect((await pathNumbers(page, edgeId)).length).toBe(4);
    });

    await test.step("dragging the segment's middle adds a vertex and Save is offered", async () => {
      const from = await centre(page, ".graph-segment-handle");
      await drag(page, from, { x: from.x, y: from.y - 110 });
      await expect(page.locator(".graph-waypoint")).toHaveCount(1);
      expect((await pathNumbers(page, edgeId)).length).toBe(6);
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
    });

    await test.step("the Selection card lists the vertex and moves it from its fields", async () => {
      const x = page.getByRole("spinbutton", { name: "Vertex 1 X" });
      const before = Number(await x.inputValue());
      await x.fill(String(before + 40));
      await x.press("Tab");
      await expect(x).toHaveValue(String(before + 40));
      await page.getByRole("switch", { name: "Smooth curve" }).click();
      await expect(page.locator(`.react-flow__edge[data-id="${edgeId}"] path.react-flow__edge-path`)).toHaveAttribute("d", / C /);
    });

    await test.step("Save stores the route and a reload draws it", async () => {
      const saved = page.waitForResponse((r) => r.url().includes(`/diagrams/${diagram.id}/layout`) && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      const view = await (await page.request.get(`${arch}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json();
      expect(view.anchors).toHaveLength(1);
      expect(view.anchors[0].points).toHaveLength(1);
      expect(view.anchors[0].smooth).toBe(true);
      await page.reload();
      await expect(page.getByLabel(`Alpha ${suffix}, node`, { exact: true })).toBeVisible();
      await expect(page.locator(`.react-flow__edge[data-id="${edgeId}"] path.react-flow__edge-path`)).toHaveAttribute("d", / C /);
    });

    await test.step("double-clicking the vertex removes it and the line is straight again", async () => {
      await selectLine(page, edgeId);
      await page.locator(".graph-waypoint").first().dblclick();
      await expect(page.locator(".graph-waypoint")).toHaveCount(0);
      expect((await pathNumbers(page, edgeId)).length).toBe(4);
    });
  });

  test("Delete on a focused vertex removes the vertex and not the line, and Undo brings it back", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchVertexKey", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const alpha = await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
    const bravo = await createElement(page.request, arch, adminHeaders, `Bravo ${suffix}`);
    const types = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
    const connection = await page.request.post(`${arch}/connections`, {
      headers: adminHeaders, data: { connection_type_id: types[0].id, source_element_id: alpha, target_element_id: bravo, activate: true },
    });
    expect(connection.ok(), await connection.text()).toBeTruthy();
    const made = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Keys ${suffix}`, activate: true, populate: true } });
    const diagram = await made.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`Alpha ${suffix}, node`, { exact: true })).toBeVisible();
    const line = page.locator(".react-flow__edge").first();
    const edgeId = (await line.getAttribute("data-id"))!;
    await selectLine(page, edgeId);

    // The keyboard route: add a vertex from the Selection card, then remove it with Delete on its handle.
    await page.getByRole("button", { name: "Add vertex" }).click();
    await expect(page.locator(".graph-waypoint")).toHaveCount(1);
    await page.locator(".graph-waypoint").first().focus();
    await page.keyboard.press("Delete");
    await expect(page.locator(".graph-waypoint")).toHaveCount(0);
    await expect(page.locator(`.react-flow__edge[data-id="${edgeId}"]`)).toHaveCount(1);
    await expect(page.getByLabel(`Alpha ${suffix}, node`, { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Undo" }).click();
    await expect(page.locator(".graph-waypoint")).toHaveCount(1);
  });

  test("a state machine transition is routed the same way and the Outline counts its vertices", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchVertexSmd", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, arch, adminHeaders, `Pump ${suffix}`);
    const created = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Pump modes ${suffix}`, element_id: elementId } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const machine = await created.json();
    let version = machine.version;
    const ids: string[] = [];
    for (const [index, name] of ["Idle", "Running"].entries()) {
      const added = await page.request.post(`${arch}/state-machine-diagrams/${machine.id}/states`, {
        headers: adminHeaders, data: { version, name, kind: "state", x: 40 + index * 320, y: 40, width: 160, height: 64 },
      });
      expect(added.ok(), await added.text()).toBeTruthy();
      const body = await added.json();
      ids.push(body.id);
      version = body.state_machine_diagram_version;
    }
    const added = await page.request.post(`${arch}/state-machine-diagrams/${machine.id}/transitions`, {
      headers: adminHeaders, data: { version, source_state_id: ids[0], target_state_id: ids[1], event: "start" },
    });
    expect(added.ok(), await added.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${machine.id}`);
    await expect(page.getByLabel("Idle, node", { exact: false })).toBeVisible();
    const line = page.locator(".react-flow__edge").first();
    const edgeId = (await line.getAttribute("data-id"))!;
    await selectLine(page, edgeId);

    const from = await centre(page, ".graph-segment-handle");
    await drag(page, from, { x: from.x, y: from.y - 90 });
    await expect(page.locator(".graph-waypoint")).toHaveCount(1);
    const saved = page.waitForResponse((r) => r.url().includes(`/state-machine-diagrams/${machine.id}/layout`) && r.request().method() === "PUT");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    expect((await saved).ok()).toBeTruthy();

    const model = await (await page.request.get(`${arch}/state-machine-diagrams/${machine.id}/model`, { headers: adminHeaders })).json();
    expect(model.transitions[0].points).toHaveLength(1);

    await page.reload();
    await expect(page.locator(`.react-flow__edge[data-id="${edgeId}"]`)).toHaveCount(1);
    await page.getByRole("tab", { name: "Outline" }).click();
    const row = page.getByRole("row", { name: /Transition from .*Idle/ }).or(page.locator("tr", { hasText: "start" })).first();
    await expect(row.getByRole("cell").last()).toHaveText("1");
  });
});
