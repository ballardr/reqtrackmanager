import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** A box's top-left corner in canvas units, from the transform React Flow gives the node (a top-level box is absolute). */
async function positionOf(page: Page, label: string): Promise<{ x: number; y: number }> {
  return page.getByLabel(label, { exact: true }).locator("xpath=ancestor-or-self::*[contains(@class,'react-flow__node')][1]").evaluate((el) => {
    const match = /translate\(\s*(-?[\d.]+)px,\s*(-?[\d.]+)px\s*\)/.exec((el as HTMLElement).style.transform);
    if (!match) throw new Error(`no transform on ${(el as HTMLElement).className}`);
    return { x: Number(match[1]), y: Number(match[2]) };
  });
}

/** The canvas zoom (screen pixels per canvas unit). */
const zoomOf = (page: Page) =>
  page.locator(".react-flow__viewport").evaluate((el) => Number(/scale\(([\d.]+)\)/.exec((el as HTMLElement).style.transform)?.[1] ?? 1));

/** Drags a box by about `dx`, `dy` canvas units with the real mouse. */
async function dragBox(page: Page, label: string, dx: number, dy: number) {
  const zoom = await zoomOf(page);
  const box = (await page.getByLabel(label, { exact: true }).boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + (dx * zoom) / 2, y + (dy * zoom) / 2, { steps: 5 });
  await page.mouse.move(x + dx * zoom, y + dy * zoom, { steps: 5 });
  await page.mouse.up();
}

/** Creates an active element through the API (setup) and returns its id. */
async function createElement(request: APIRequestContext, base: string, headers: Record<string, string>, name: string): Promise<string> {
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/** Waits until a box has moved from `from` (a drag lands near, not exactly on, the requested offset). */
async function expectMovedFrom(page: Page, label: string, from: { x: number; y: number }) {
  await expect.poll(async () => {
    const at = await positionOf(page, label);
    return at.x !== from.x || at.y !== from.y;
  }).toBe(true);
}

/**
 * Job to be done: an architect expects the usual Undo and Redo keys (Cmd or Ctrl with Z, Shift for Redo, Ctrl+Y outside Apple
 * devices) to act on the drawing, as the toolbar buttons do, without disturbing text being typed or an open dialog.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements and diagrams are created through the
 * API as setup, the behaviour under test through the UI. `ControlOrMeta` is the platform's own modifier.
 */
test.describe("System Architecture: Undo and Redo keys", () => {
  test("the block diagram editor undoes and redoes a move with the keys, leaves a typed name and an open dialog alone", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchUndo", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    await createElement(page.request, arch, adminHeaders, `Hub ${suffix}`);
    const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
    const diagram = await diagramRes.json();
    const hub = `Hub ${suffix}, node`;

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(hub, { exact: true })).toBeVisible();
    const start = await positionOf(page, hub);

    await test.step("the keys do nothing with nothing to undo", async () => {
      await page.keyboard.press("ControlOrMeta+z");
      await expect(page.getByRole("button", { name: "Undo" })).toBeDisabled();
      expect(await positionOf(page, hub)).toEqual(start);
    });

    await test.step("Undo and Redo keys move the box back and forth", async () => {
      await dragBox(page, hub, 120, 80);
      await expectMovedFrom(page, hub, start);
      const moved = await positionOf(page, hub);
      await page.keyboard.press("ControlOrMeta+z");
      await expect.poll(() => positionOf(page, hub)).toEqual(start);
      await page.keyboard.press("ControlOrMeta+Shift+z");
      await expect.poll(() => positionOf(page, hub)).toEqual(moved);
      await page.keyboard.press("ControlOrMeta+z");
      await expect.poll(() => positionOf(page, hub)).toEqual(start);
    });

    await test.step("the tooltip names the key and says a created record is not removed", async () => {
      await dragBox(page, hub, 120, 80);
      await expectMovedFrom(page, hub, start);
      await page.getByRole("button", { name: "Undo" }).hover();
      const tip = page.getByRole("tooltip");
      await expect(tip).toContainText(/(Ctrl|Cmd)\+Z/);
      await expect(tip).toContainText("created at once");
    });

    await test.step("a name typed in the Selection card is undone as text and the layout is not touched", async () => {
      await page.getByLabel(hub, { exact: true }).click();
      const moved = await positionOf(page, hub);
      const name = page.getByRole("group", { name: "Element details" }).getByRole("textbox", { name: /^Name/ });
      await name.click();
      await page.keyboard.press("End");
      await page.keyboard.type(" extra");
      await expect(name).toHaveValue(`Hub ${suffix} extra`);
      await page.keyboard.press("ControlOrMeta+z");
      await expect(name).not.toHaveValue(`Hub ${suffix} extra`);
      expect(await positionOf(page, hub)).toEqual(moved);
      await expect(page.getByRole("button", { name: "Undo" })).toBeEnabled();
      await name.blur();
    });

    await test.step("the keys do nothing while a dialog is open", async () => {
      const before = await positionOf(page, hub);
      await page.getByRole("button", { name: /^Diagram settings/ }).click();
      await expect(page.getByRole("dialog", { name: "Diagram settings" })).toBeVisible();
      await page.keyboard.press("ControlOrMeta+z");
      expect(await positionOf(page, hub)).toEqual(before);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog", { name: "Diagram settings" })).toHaveCount(0);
      await page.getByRole("button", { name: "Undo" }).focus();
      await page.keyboard.press("ControlOrMeta+z");
      await expect.poll(() => positionOf(page, hub)).toEqual(start);
    });
  });

  test("the state machine editor undoes and redoes a move with the keys", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchUndoSm", true, "System Architecture");
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
    const start = await positionOf(page, idle);

    await dragBox(page, idle, 120, 80);
    await expectMovedFrom(page, idle, start);
    const moved = await positionOf(page, idle);
    await page.keyboard.press("ControlOrMeta+z");
    await expect.poll(() => positionOf(page, idle)).toEqual(start);
    await page.keyboard.press("ControlOrMeta+Shift+z");
    await expect.poll(() => positionOf(page, idle)).toEqual(moved);
    await page.keyboard.press("ControlOrMeta+z");
    await expect.poll(() => positionOf(page, idle)).toEqual(start);
    // Ctrl+Y is the other Redo, outside Apple devices.
    if (!process.platform.startsWith("darwin")) {
      await page.keyboard.press("Control+y");
      await expect.poll(() => positionOf(page, idle)).toEqual(moved);
    }
  });
});
