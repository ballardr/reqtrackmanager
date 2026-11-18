import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** A box's attach point (a hidden point keeps its size and stays in the page, so it can be measured when not drawn). */
const pointOf = (page: Page, label: string, point: string): Locator =>
  page.getByLabel(label, { exact: true }).locator(`.react-flow__handle[data-handleid="${point}"]`);

/** Moves the real mouse to a spot a few screen pixels outside a box's left edge, level with its middle. */
async function approachFromLeft(page: Page, label: string, gap = 10) {
  const box = (await page.getByLabel(label, { exact: true }).boundingBox())!;
  await page.mouse.move(box.x - gap, box.y + box.height / 2, { steps: 4 });
}

/** Moves the mouse to the canvas's bottom right corner, far from every box. */
async function leaveToCorner(page: Page) {
  const pane = (await page.locator(".react-flow__pane").boundingBox())!;
  await page.mouse.move(pane.x + pane.width - 6, pane.y + pane.height - 6, { steps: 4 });
}

/** Creates an active element through the API (setup) and returns its id. */
async function createElement(request: APIRequestContext, base: string, headers: Record<string, string>, name: string): Promise<string> {
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/**
 * Job to be done: an architect reads a diagram without eight dots on every box, and still starts a line from a box's edge with
 * only the pointer. A box shows its attach points while the pointer is near it, while it is selected or focused, and while a
 * line is being drawn near it.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements and diagrams are created through the
 * API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: attach points near the pointer", () => {
  test("the block diagram editor draws a box's points on approach, on selection and while a line is drawn", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchPts", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
    await createElement(page.request, arch, adminHeaders, `Bravo ${suffix}`);
    const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
    const diagram = await diagramRes.json();
    const alpha = `Alpha ${suffix}, node`;
    const bravo = `Bravo ${suffix}, node`;

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(alpha, { exact: true })).toBeVisible();
    await expect(page.getByLabel(bravo, { exact: true })).toBeVisible();

    // Alpha is approached from the left, so the box that lies further left is the one to approach; the other must stay hidden.
    const [first, second] = ((await page.getByLabel(alpha, { exact: true }).boundingBox())!.x <= (await page.getByLabel(bravo, { exact: true }).boundingBox())!.x)
      ? [alpha, bravo] : [bravo, alpha];

    await test.step("at rest no box draws its points, though they are in the page", async () => {
      await leaveToCorner(page);
      await expect(pointOf(page, first, "top")).toHaveCSS("opacity", "0");
      await expect(pointOf(page, second, "top")).toHaveCSS("opacity", "0");
      await expect(pointOf(page, first, "right")).toHaveCount(1);
    });

    await test.step("bringing the pointer near a box draws its points and no other box's; leaving hides them", async () => {
      await approachFromLeft(page, first);
      await expect(pointOf(page, first, "top")).toHaveCSS("opacity", "1");
      await expect(pointOf(page, second, "top")).toHaveCSS("opacity", "0");
      await leaveToCorner(page);
      await expect(pointOf(page, first, "top")).toHaveCSS("opacity", "0");
    });

    await test.step("a selected box keeps its points while the pointer is elsewhere", async () => {
      await page.getByLabel(first, { exact: true }).focus();
      await page.keyboard.press("Enter");
      await leaveToCorner(page);
      await expect(pointOf(page, first, "top")).toHaveCSS("opacity", "1");
      await expect(pointOf(page, second, "top")).toHaveCSS("opacity", "0");
    });
  });

  test("a line can be started from a box's edge with the pointer alone, and the box it nears shows its points", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchPtsLine", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
    await createElement(page.request, arch, adminHeaders, `Bravo ${suffix}`);
    const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
    const diagram = await diagramRes.json();
    const alpha = `Alpha ${suffix}, node`;
    const bravo = `Bravo ${suffix}, node`;

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(alpha, { exact: true })).toBeVisible();
    await expect(page.getByLabel(bravo, { exact: true })).toBeVisible();

    const [from, to] = ((await page.getByLabel(alpha, { exact: true }).boundingBox())!.x <= (await page.getByLabel(bravo, { exact: true }).boundingBox())!.x)
      ? [alpha, bravo] : [bravo, alpha];

    await test.step("press a point of the first box (drawn on approach), drag toward the second and see its points", async () => {
      await leaveToCorner(page);
      const point = pointOf(page, from, "right");
      const start = (await point.boundingBox())!;
      const origin = { x: start.x + start.width / 2, y: start.y + start.height / 2 };
      await page.mouse.move(origin.x - 12, origin.y, { steps: 4 });
      await expect(pointOf(page, from, "right")).toHaveCSS("opacity", "1");
      await page.mouse.move(origin.x, origin.y);
      await page.mouse.down();
      const target = (await page.getByLabel(to, { exact: true }).boundingBox())!;
      await page.mouse.move(target.x - 12, target.y + target.height / 2, { steps: 12 });
      await expect(pointOf(page, to, "left")).toHaveCSS("opacity", "1");
      // The box the line starts from keeps its start point drawn while the pointer is far from it.
      await expect(pointOf(page, from, "right")).toHaveCSS("opacity", "1");
      await page.mouse.up();
    });
  });

  test("the state machine editor draws a state's points only near the pointer", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchPtsSm", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, arch, adminHeaders, `Gateway ${suffix}`);
    const created = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Modes ${suffix}`, element_id: elementId } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    const added = await page.request.post(`${arch}/state-machine-diagrams/${diagram.id}/states`, {
      headers: adminHeaders, data: { version: diagram.version, name: "Idle", kind: "state", x: 0, y: 0, width: 160, height: 64 },
    });
    expect(added.ok(), await added.text()).toBeTruthy();
    const idle = "Idle, node";

    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    await expect(page.getByLabel(idle, { exact: true })).toBeVisible();

    await leaveToCorner(page);
    await expect(pointOf(page, idle, "top")).toHaveCSS("opacity", "0");
    await approachFromLeft(page, idle);
    await expect(pointOf(page, idle, "top")).toHaveCSS("opacity", "1");
    await leaveToCorner(page);
    await expect(pointOf(page, idle, "top")).toHaveCSS("opacity", "0");
  });

  test("Always show attach points is a setting in both editors' gears, kept for the person across a reload", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchPtsSet", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
    const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
    const diagram = await diagramRes.json();
    const machineRes = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Modes ${suffix}`, element_id: elementId } });
    expect(machineRes.ok(), await machineRes.text()).toBeTruthy();
    const machine = await machineRes.json();
    const stateRes = await page.request.post(`${arch}/state-machine-diagrams/${machine.id}/states`, {
      headers: adminHeaders, data: { version: machine.version, name: "Idle", kind: "state", x: 0, y: 0, width: 160, height: 64 },
    });
    expect(stateRes.ok(), await stateRes.text()).toBeTruthy();
    const alpha = `Alpha ${suffix}, node`;

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(alpha, { exact: true })).toBeVisible();

    await test.step("off by default: the points are not drawn at rest", async () => {
      await leaveToCorner(page);
      await expect(pointOf(page, alpha, "top")).toHaveCSS("opacity", "0");
    });

    await test.step("switching it on in the gear draws the points at rest", async () => {
      const saved = page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH");
      await page.getByRole("button", { name: /^Diagram settings/ }).click();
      await page.getByRole("dialog", { name: "Diagram settings" }).getByRole("switch", { name: "Always show attach points" }).click();
      await saved;
      await page.keyboard.press("Escape");
      await leaveToCorner(page);
      await expect(pointOf(page, alpha, "top")).toHaveCSS("opacity", "1");
    });

    await test.step("the choice is kept after a reload and is the same in the state machine editor", async () => {
      await page.reload();
      await expect(page.getByLabel(alpha, { exact: true })).toBeVisible();
      await leaveToCorner(page);
      await expect(pointOf(page, alpha, "top")).toHaveCSS("opacity", "1");
      await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${machine.id}`);
      await expect(page.getByLabel("Idle, node", { exact: true })).toBeVisible();
      await leaveToCorner(page);
      await expect(pointOf(page, "Idle, node", "top")).toHaveCSS("opacity", "1");
    });

    await test.step("switching it off returns to the points near the pointer", async () => {
      const saved = page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH");
      await page.getByRole("button", { name: /^Diagram settings/ }).click();
      await page.getByRole("dialog", { name: "Diagram settings" }).getByRole("switch", { name: "Always show attach points" }).click();
      await saved;
      await page.keyboard.press("Escape");
      await leaveToCorner(page);
      await expect(pointOf(page, "Idle, node", "top")).toHaveCSS("opacity", "0");
    });
  });
});
