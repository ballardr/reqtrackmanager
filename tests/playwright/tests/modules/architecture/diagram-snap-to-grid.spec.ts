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

/** Drags a box by about `dx`, `dy` canvas units with the real mouse (the drag lands a few units short, so callers assert on the grid). */
async function dragBox(page: Page, label: string, dx: number, dy: number, holdShift = false) {
  const zoom = await zoomOf(page);
  const box = (await page.getByLabel(label, { exact: true }).boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  if (holdShift) await page.keyboard.down("Shift");
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + (dx * zoom) / 2, y + (dy * zoom) / 2, { steps: 5 });
  await page.mouse.move(x + dx * zoom, y + dy * zoom, { steps: 5 });
  await page.mouse.up();
  if (holdShift) await page.keyboard.up("Shift");
}

/** Switches Snap to grid in the editor's settings gear and closes the pop-over. */
async function setSnap(page: Page, on: boolean) {
  await page.getByRole("button", { name: /^Diagram settings/ }).click();
  const snap = page.getByRole("dialog", { name: "Diagram settings" }).getByRole("switch", { name: "Snap to grid" });
  if ((await snap.getAttribute("aria-checked")) !== String(on)) await snap.click();
  await expect(snap).toHaveAttribute("aria-checked", String(on));
  await page.keyboard.press("Escape");
}

const onGrid = (n: number) => Math.abs(n / 20 - Math.round(n / 20)) < 1e-6;

/** Creates an active element through the API (setup) and returns its id. */
async function createElement(request: APIRequestContext, base: string, headers: Record<string, string>, name: string): Promise<string> {
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/**
 * Job to be done: an architect lines boxes up on a diagram. Snap to grid is a personal setting in the editor's settings gear
 * (off by default, kept in this browser), Shift held during a drag does the opposite for that move, and arrow keys step by the
 * grid while it is on. Both editors share the choice.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements and diagrams are created through the
 * API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: snap to grid", () => {
  test("the block diagram editor snaps a dragged box, Shift reverses it, arrow keys step by the grid and the setting is kept", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSnap", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    await createElement(page.request, arch, adminHeaders, `Hub ${suffix}`);
    const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
    const diagram = await diagramRes.json();
    const hub = `Hub ${suffix}, node`;

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(hub, { exact: true })).toBeVisible();

    await test.step("snapping is off by default: no dot grid, and a drag lands off the grid", async () => {
      await expect(page.locator(".react-flow__background")).toHaveCount(0);
      await dragBox(page, hub, 27, 59);
      const at = await positionOf(page, hub);
      expect(onGrid(at.x) && onGrid(at.y)).toBe(false);
    });

    await test.step("switching it on draws the grid and snaps a drag", async () => {
      await setSnap(page, true);
      await expect(page.locator(".react-flow__background")).toHaveCount(1);
      await dragBox(page, hub, 41, 33);
      const at = await positionOf(page, hub);
      expect(onGrid(at.x), `x ${at.x}`).toBe(true);
      expect(onGrid(at.y), `y ${at.y}`).toBe(true);
    });

    await test.step("Shift held during a drag moves freely, and no selection rectangle starts", async () => {
      await dragBox(page, hub, 27, 59, true);
      const at = await positionOf(page, hub);
      expect(onGrid(at.x) && onGrid(at.y)).toBe(false);
      await expect(page.locator(".react-flow__selection, .react-flow__nodesselection")).toHaveCount(0);
    });

    await test.step("arrow keys move the selected box by one grid step", async () => {
      await dragBox(page, hub, 41, 33);
      const before = await positionOf(page, hub);
      await page.getByLabel(hub, { exact: true }).focus();
      await page.keyboard.press("Enter");
      await page.keyboard.press("ArrowRight");
      await page.keyboard.press("ArrowDown");
      await expect.poll(async () => (await positionOf(page, hub)).x).toBe(before.x + 20);
      expect((await positionOf(page, hub)).y).toBe(before.y + 20);
    });

    await test.step("with it off, Shift held during a drag snaps", async () => {
      await setSnap(page, false);
      await expect(page.locator(".react-flow__background")).toHaveCount(0);
      await dragBox(page, hub, 27, 59, true);
      const at = await positionOf(page, hub);
      expect(onGrid(at.x), `x ${at.x}`).toBe(true);
      expect(onGrid(at.y), `y ${at.y}`).toBe(true);
    });

    await test.step("the setting survives a reload", async () => {
      await setSnap(page, true);
      await page.reload();
      await expect(page.getByLabel(hub, { exact: true })).toBeVisible();
      await expect(page.locator(".react-flow__background")).toHaveCount(1);
    });
  });

  test("the state machine editor has the same setting and snaps a dragged state", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSnapSm", true, "System Architecture");
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

    await test.step("off by default; switching it on in the gear draws the grid", async () => {
      await expect(page.locator(".react-flow__background")).toHaveCount(0);
      await setSnap(page, true);
      await expect(page.locator(".react-flow__background")).toHaveCount(1);
    });

    await test.step("a dragged state lands on the grid and Shift reverses it", async () => {
      await dragBox(page, idle, 41, 33);
      const snapped = await positionOf(page, idle);
      expect(onGrid(snapped.x) && onGrid(snapped.y), `${snapped.x},${snapped.y}`).toBe(true);
      await dragBox(page, idle, 27, 59, true);
      const free = await positionOf(page, idle);
      expect(onGrid(free.x) && onGrid(free.y)).toBe(false);
    });
  });

  test("with Snap to grid off, every kind of symbol is stored where it is dropped, with the invert key's release lost or not", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchDropSm", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, arch, adminHeaders, `Gateway ${suffix}`);
    const created = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Drops ${suffix}`, element_id: elementId } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    // Every symbol starts on a grid line, so a snapped drop would end on one too.
    const kinds: { name: string; kind: string; x: number; y: number; width: number; height: number }[] = [
      { name: "Idle", kind: "state", x: 0, y: 0, width: 160, height: 64 },
      { name: "Branch", kind: "choice", x: 240, y: 0, width: 36, height: 36 },
      { name: "Start", kind: "initial", x: 340, y: 0, width: 20, height: 20 },
      { name: "Stop", kind: "final", x: 420, y: 0, width: 28, height: 28 },
    ];
    let version: number = diagram.version;
    const ids: Record<string, string> = {};
    for (const symbol of kinds) {
      const added = await page.request.post(`${arch}/state-machine-diagrams/${diagram.id}/states`, { headers: adminHeaders, data: { version, ...symbol } });
      expect(added.ok(), await added.text()).toBeTruthy();
      ids[symbol.name] = (await added.json()).id;
      version += 1;
    }
    const node = (name: string) => page.locator(`.react-flow__node[data-id="${ids[name]}"]`);
    const at = (name: string) => node(name).evaluate((el) => {
      const match = /translate\(\s*(-?[\d.]+)px,\s*(-?[\d.]+)px\s*\)/.exec((el as HTMLElement).style.transform);
      if (!match) throw new Error("no transform");
      return { x: Number(match[1]), y: Number(match[2]) };
    });
    const drag = async (name: string, dx: number, dy: number) => {
      const zoom = await zoomOf(page);
      const box = (await node(name).boundingBox())!;
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await page.mouse.move(x, y);
      await page.mouse.down();
      await page.mouse.move(x + (dx * zoom) / 2, y + (dy * zoom) / 2, { steps: 5 });
      await page.mouse.move(x + dx * zoom, y + dy * zoom, { steps: 5 });
      await page.mouse.up();
    };

    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    await expect(node("Idle")).toBeVisible();
    await expect(page.locator(".react-flow__background")).toHaveCount(0);

    const dropped: Record<string, { x: number; y: number }> = {};
    await test.step("each symbol lands off the grid, by the same amount", async () => {
      for (const symbol of kinds) {
        const before = await at(symbol.name);
        await drag(symbol.name, 37, 31);
        const after = await at(symbol.name);
        dropped[symbol.name] = after;
        expect(onGrid(after.x) || onGrid(after.y), `${symbol.name} ${after.x},${after.y}`).toBe(false);
        expect(Math.round(after.x - before.x) % 20, symbol.name).not.toBe(0);
      }
      const shifts = kinds.map((k) => Math.round(dropped[k.name].x - k.x));
      expect(new Set(shifts).size, `shifts ${shifts}`).toBe(1);
    });

    await test.step("a Shift key-up the page never received does not make the next drop snap", async () => {
      await page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Shift", shiftKey: true })));
      await drag("Branch", 23, 17);
      const after = await at("Branch");
      expect(onGrid(after.x) || onGrid(after.y), `${after.x},${after.y}`).toBe(false);
      dropped.Branch = after;
    });

    await test.step("saved and reloaded, every symbol is where it was dropped", async () => {
      await page.getByRole("button", { name: "Save diagram" }).click();
      await expect(page.getByRole("button", { name: "Save diagram" })).toBeDisabled();
      await page.reload();
      await expect(node("Idle")).toBeVisible();
      for (const symbol of kinds) {
        const stored = await at(symbol.name);
        expect(Math.abs(stored.x - dropped[symbol.name].x), symbol.name).toBeLessThanOrEqual(1);
        expect(Math.abs(stored.y - dropped[symbol.name].y), symbol.name).toBeLessThanOrEqual(1);
      }
    });
  });
});
