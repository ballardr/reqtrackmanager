import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** The open thread's pop-over. */
const thread = (page: Page) => page.getByRole("dialog", { name: "Comment thread" });

/** The canvas's current viewport transform (pan and zoom), the way React Flow stores it. */
const viewport = (page: Page) => page.locator(".react-flow__viewport").evaluate((el) => (el as HTMLElement).style.transform);

/** Stores a free comment (a thread pinned to a place, not to a box) through the API as setup. */
async function pinFreeComment(request: APIRequestContext, base: string, headers: Record<string, string>, type: string, id: string, at: { x: number; y: number }) {
  const stored = await request.post(`${base}/artefacts/${type}/${id}/comments`, {
    headers, data: { body: "Is this still the plan?", pin: { anchor_kind: "none", anchor_key: null, x: at.x, y: at.y } },
  });
  expect(stored.ok(), await stored.text()).toBeTruthy();
  const read = await request.get(`${base}/artefacts/${type}/${id}/comments`, { headers });
  const pins = ((await read.json()) as { pins: { id: string }[] }).pins;
  return { pin_id: pins[0].id };
}

/**
 * Job to be done: a person opens a diagram from an element's page. The diagram never starts with a comment thread open; one
 * opens only from a link that names it, after the view is fitted to the drawing, and it closes by Escape, a click on empty canvas
 * or its own symbol, after which a reload keeps it closed.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the element, diagram and comment are created
 * through the API as setup.
 */
test.describe("System Architecture: a diagram opened from a comment link", () => {
  test("the block diagram has no thread open unless a link names it, and every way of closing one clears the link", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchPin", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}`;
    const arch = `${base}/modules/architecture`;
    const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
    const element = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name: `Hub ${suffix}`, element_type_id: types[0].id, activate: true } });
    expect(element.ok(), await element.text()).toBeTruthy();
    const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
    const diagram = await diagramRes.json();
    const comment = await pinFreeComment(page.request, base, adminHeaders, "architecture_diagram", diagram.id, { x: 700, y: 400 });
    const path = `/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`;
    const hub = page.getByLabel(`Hub ${suffix}, node`, { exact: true });

    // A second diagram of the same boxes with no thread: the view a thread must never change.
    const bareRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Bare ${suffix}`, activate: true, populate: true } });
    expect(bareRes.ok(), await bareRes.text()).toBeTruthy();
    const bare = await bareRes.json();

    let fitted = "";
    await test.step("opened plainly, no thread is open and the view is the fit of the drawing alone", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${bare.id}`);
      await expect(hub).toBeVisible();
      await expect(page.getByRole("button", { name: /Comment thread by/ })).toHaveCount(0);
      const withoutThread = await viewport(page);
      await page.goto(path);
      await expect(hub).toBeVisible();
      await expect(page.getByRole("button", { name: /Comment thread by/ })).toBeVisible();
      await expect(thread(page)).toHaveCount(0);
      fitted = await viewport(page);
      expect(fitted).toBe(withoutThread);
    });

    await test.step("a link naming the thread opens it and moves the view to it, after the fit", async () => {
      await page.goto(`${path}?pin=${comment.pin_id}`);
      await expect(thread(page)).toBeVisible();
      // The view moves to the thread (an animation), so it settles on a different pan from the fit.
      await expect.poll(() => viewport(page)).not.toBe(fitted);
      const marker = await page.getByRole("button", { name: /Comment thread by/ }).boundingBox();
      const pane = await page.locator(".react-flow__pane").boundingBox();
      expect(marker!.x).toBeGreaterThan(pane!.x);
      expect(marker!.x + marker!.width).toBeLessThan(pane!.x + pane!.width);
      expect(marker!.y).toBeGreaterThan(pane!.y);
      expect(marker!.y + marker!.height).toBeLessThan(pane!.y + pane!.height);
    });

    await test.step("Escape closes it and clears the link, so a reload keeps it closed", async () => {
      await page.keyboard.press("Escape");
      await expect(thread(page)).toHaveCount(0);
      await expect(page).not.toHaveURL(/pin=/);
      await page.reload();
      await expect(hub).toBeVisible();
      await expect(thread(page)).toHaveCount(0);
      expect(await viewport(page)).toBe(fitted);
    });

    await test.step("a click on empty canvas closes it and clears the link", async () => {
      await page.goto(`${path}?pin=${comment.pin_id}`);
      await expect(thread(page)).toBeVisible();
      const area = await page.locator(".react-flow__pane").boundingBox();
      await page.mouse.click(area!.x + 8, area!.y + area!.height - 8);
      await expect(thread(page)).toHaveCount(0);
      await expect(page).not.toHaveURL(/pin=/);
    });

    await test.step("its own symbol closes it and clears the link", async () => {
      await page.goto(`${path}?pin=${comment.pin_id}`);
      await expect(thread(page)).toBeVisible();
      await page.getByRole("button", { name: /Comment thread by/ }).click();
      await expect(thread(page)).toHaveCount(0);
      await expect(page).not.toHaveURL(/pin=/);
    });
  });

  test("the state machine diagram follows the same rule", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "SmdPin", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}`;
    const arch = `${base}/modules/architecture`;
    const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
    const element = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name: `Valve ${suffix}`, element_type_id: types[0].id, activate: true } });
    expect(element.ok(), await element.text()).toBeTruthy();
    const created = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Modes ${suffix}`, element_id: (await element.json()).id } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    const added = await page.request.post(`${arch}/state-machine-diagrams/${diagram.id}/states`, {
      headers: adminHeaders, data: { version: diagram.version, name: "Open", kind: "state", x: 140, y: 40, width: 160, height: 64 },
    });
    expect(added.ok(), await added.text()).toBeTruthy();
    const comment = await pinFreeComment(page.request, base, adminHeaders, "architecture_state_machine_diagram", diagram.id, { x: 500, y: 300 });
    const path = `/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`;
    const open = page.getByLabel("Open, node", { exact: true });

    await page.goto(path);
    await expect(open).toBeVisible();
    await expect(page.getByRole("button", { name: /Comment thread by/ })).toBeVisible();
    await expect(thread(page)).toHaveCount(0);

    await page.goto(`${path}?pin=${comment.pin_id}`);
    await expect(thread(page)).toBeVisible();
    const area = await page.locator(".react-flow__pane").boundingBox();
    await page.mouse.click(area!.x + 8, area!.y + area!.height - 8);
    await expect(thread(page)).toHaveCount(0);
    await expect(page).not.toHaveURL(/pin=/);
    await page.reload();
    await expect(open).toBeVisible();
    await expect(thread(page)).toHaveCount(0);
  });
});
