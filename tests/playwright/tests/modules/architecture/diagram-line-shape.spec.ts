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

/** A line's path as drawn. */
async function pathOf(page: Page, edge: string): Promise<string> {
  return (await page.locator(`.react-flow__edge[data-id="${edge}"] path.react-flow__edge-path`).getAttribute("d")) ?? "";
}

/** Selects a line the way the keyboard does: focus it and press Enter (the line is a thin target for a pointer). */
async function selectLine(page: Page, edge: string) {
  await page.locator(`.react-flow__edge[data-id="${edge}"]`).focus();
  await page.keyboard.press("Enter");
}

/** Sets the diagram's default line shape in the settings button; the change is stored at once. */
async function chooseDefaultShape(page: Page, url: RegExp, shape: "Straight" | "Curved" | "Spline") {
  await page.getByRole("button", { name: /^Diagram settings/ }).click();
  const dialog = page.getByRole("dialog", { name: "Diagram settings" });
  const stored = page.waitForResponse((r) => url.test(r.url()) && r.request().method() === "PUT");
  await dialog.getByRole("combobox", { name: "Default line shape" }).selectOption({ label: shape });
  expect((await stored).ok()).toBeTruthy();
  // A click outside closes the pop-over (Escape is taken by the select that holds the focus).
  await page.getByRole("heading", { level: 1 }).click();
  await expect(dialog).toHaveCount(0);
}

/**
 * Job to be done: an architect chooses how lines are drawn on a diagram. The diagram has a default line shape (Straight,
 * Curved or Spline) and any one line can keep its own shape or follow the default again; the choice is stored with the
 * diagram, survives a reload and is the same on a block diagram and a state machine diagram.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements, connections and diagrams are
 * created through the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: line shape", () => {
  test("a block diagram follows its default shape, a line keeps its own, and both survive a reload", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchShape", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const alpha = await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
    const bravo = await createElement(page.request, arch, adminHeaders, `Bravo ${suffix}`);
    const types = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
    const connection = await page.request.post(`${arch}/connections`, {
      headers: adminHeaders, data: { connection_type_id: types[0].id, source_element_id: alpha, target_element_id: bravo, activate: true },
    });
    expect(connection.ok(), await connection.text()).toBeTruthy();
    const made = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Shapes ${suffix}`, activate: true, populate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const diagram = await made.json();
    expect(diagram.line_shape).toBe("straight");
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`Alpha ${suffix}, node`, { exact: true })).toBeVisible();
    const edgeId = (await page.locator(".react-flow__edge").first().getAttribute("data-id"))!;

    await test.step("a new diagram draws a straight line", async () => {
      expect(await pathOf(page, edgeId)).not.toContain(" C ");
    });

    await test.step("the default line shape Curved draws one arc, with no vertex", async () => {
      await chooseDefaultShape(page, new RegExp(`/diagrams/${diagram.id}$`), "Curved");
      await expect.poll(() => pathOf(page, edgeId)).toMatch(/ C /);
      expect((await pathOf(page, edgeId)).match(/ C /g)).toHaveLength(1);
      await expect(page.locator(".graph-waypoint")).toHaveCount(0);
      const stored = await (await page.request.get(`${arch}/diagrams/${diagram.id}`, { headers: adminHeaders })).json();
      expect(stored.line_shape).toBe("curved");
    });

    await test.step("the Selection card says what the line follows and a line can have its own shape", async () => {
      await selectLine(page, edgeId);
      const shape = page.getByRole("combobox", { name: "Line shape", exact: true });
      await expect(shape).toContainText("Diagram default (Curved)");
      await shape.selectOption({ label: "Straight" });
      await expect.poll(() => pathOf(page, edgeId)).not.toMatch(/ C /);
    });

    await test.step("Save stores the line's own shape and a reload draws it", async () => {
      const saved = page.waitForResponse((r) => r.url().includes(`/diagrams/${diagram.id}/layout`) && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save diagram", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      const view = await (await page.request.get(`${arch}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json();
      expect(view.anchors).toHaveLength(1);
      expect(view.anchors[0]).toMatchObject({ line_shape: "straight", points: [] });
      await page.reload();
      await expect(page.getByLabel(`Alpha ${suffix}, node`, { exact: true })).toBeVisible();
      expect(await pathOf(page, edgeId)).not.toContain(" C ");
    });

    await test.step("choosing the diagram default again drops the line's own shape", async () => {
      await selectLine(page, edgeId);
      await page.getByRole("combobox", { name: "Line shape", exact: true }).selectOption({ label: "Diagram default (Curved)" });
      await expect.poll(() => pathOf(page, edgeId)).toMatch(/ C /);
      const saved = page.waitForResponse((r) => r.url().includes(`/diagrams/${diagram.id}/layout`) && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save diagram", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      const view = await (await page.request.get(`${arch}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json();
      expect(view.anchors).toHaveLength(0);
    });

    await test.step("the server's SVG draws the same arc", async () => {
      const svg = await (await page.request.get(`${arch}/diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
      expect(svg.match(/ C /g)).toHaveLength(1);
    });
  });

  test("a state machine transition follows the default shape and can keep its own", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchShapeSmd", true, "System Architecture");
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
    const edgeId = (await page.locator(".react-flow__edge").first().getAttribute("data-id"))!;
    expect(await pathOf(page, edgeId)).not.toContain(" C ");

    // A spline with no vertices is straight; Curved is the shape that needs none.
    await chooseDefaultShape(page, new RegExp(`/state-machine-diagrams/${machine.id}$`), "Curved");
    await expect.poll(() => pathOf(page, edgeId)).toMatch(/ C /);

    await selectLine(page, edgeId);
    const shape = page.getByRole("combobox", { name: "Line shape", exact: true });
    await expect(shape).toContainText("Diagram default (Curved)");
    await shape.selectOption({ label: "Straight" });
    await expect.poll(() => pathOf(page, edgeId)).not.toMatch(/ C /);
    const saved = page.waitForResponse((r) => r.url().includes(`/state-machine-diagrams/${machine.id}/layout`) && r.request().method() === "PUT");
    await page.getByRole("button", { name: "Save diagram", exact: true }).click();
    expect((await saved).ok()).toBeTruthy();
    const model = await (await page.request.get(`${arch}/state-machine-diagrams/${machine.id}/model`, { headers: adminHeaders })).json();
    expect(model.diagram.line_shape).toBe("curved");
    expect(model.transitions[0].line_shape).toBe("straight");
  });
});
