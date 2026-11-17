import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

const SYMBOL_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect x="2" y="2" width="36" height="36" fill="none" stroke="#334155" stroke-width="3"/></svg>';

const LONG_NAME = "Flight controller and motor driver board";

/** Uploads a symbol to the project's library and returns its id. */
async function uploadSymbol(request: APIRequestContext, arch: string, headers: Record<string, string>, name: string): Promise<string> {
  const made = await request.post(`${arch}/symbols`, {
    headers, multipart: { file: { name: `${name}.svg`, mimeType: "image/svg+xml", buffer: Buffer.from(SYMBOL_SVG) }, name },
  });
  expect(made.ok(), await made.text()).toBeTruthy();
  return (await made.json()).id as string;
}

/** The size of the node's frame in canvas units (its own CSS size, not the zoomed one on the screen). */
async function frameOf(page: Page, name: string): Promise<{ width: number; height: number }> {
  return page.getByLabel(`${name}, node`, { exact: true }).evaluate((el) => {
    const frame = el as HTMLElement;
    return { width: frame.offsetWidth, height: frame.offsetHeight };
  });
}

/**
 * Job to be done: an architect gives an element a symbol, on the element or on its type, and the box on the diagram grows so the
 * symbol, the code and the whole name show, with no text cut; the size stored for the box is not changed by that.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the symbol, element and diagram are created
 * through the API as setup, the behaviour under test through the UI and the stored read.
 */
test.describe("System Architecture: an element box fits its symbol and text", () => {
  test("a symbol on an element or its type grows the drawn box and leaves the stored size alone", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchBoxFit", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    // The project's own type, so the test can change its symbol (the seeded types belong to the organisation).
    const type = await (await page.request.post(`${arch}/element-types`, { headers: adminHeaders, data: { name: "Board" } })).json();
    const name = `${LONG_NAME} ${suffix}`;
    const made = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: type.id, activate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const element = await made.json();
    const diagram = await (await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } })).json();
    const url = `/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`;
    const view = async () => (await (await page.request.get(`${arch}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json()).nodes;

    let plainHeight = 0;
    let version = element.version as number;
    await test.step("without a symbol the default box holds the long name whole", async () => {
      await page.goto(url);
      await expect(page.getByLabel(`${name}, node`, { exact: true })).toBeVisible();
      const frame = await frameOf(page, name);
      expect(frame.width).toBeGreaterThanOrEqual(160);
      plainHeight = frame.height;
      const label = page.getByLabel(`${name}, node`, { exact: true }).locator(".graph-node-label");
      const [scroll, client] = await label.evaluate((el) => [el.scrollHeight, el.clientHeight]);
      expect(scroll).toBeLessThanOrEqual(client);
    });

    const symbolId = await uploadSymbol(page.request, arch, adminHeaders, `Board ${suffix}`);

    await test.step("a symbol set on the element grows the box and no text is cut", async () => {
      const set = await page.request.put(`${arch}/elements/${element.id}`, { headers: adminHeaders, data: { symbol_id: symbolId, version: element.version } });
      expect(set.ok(), await set.text()).toBeTruthy();
      version = (await set.json()).version;
      await page.reload();
      const node = page.getByLabel(`${name}, node`, { exact: true });
      await expect(node.locator(".graph-node-symbol")).toBeVisible();
      await expect.poll(async () => (await frameOf(page, name)).height).toBeGreaterThan(plainHeight + 30);
      const label = node.locator(".graph-node-label");
      const [scroll, client] = await label.evaluate((el) => [el.scrollHeight, el.clientHeight]);
      expect(scroll).toBeLessThanOrEqual(client);
      const caption = node.locator(".graph-node-caption");
      const [captionScroll, captionClient] = await caption.evaluate((el) => [el.scrollWidth, el.clientWidth]);
      expect(captionScroll).toBeLessThanOrEqual(captionClient);
      // Nothing the box holds reaches beyond its frame.
      const frame = await node.locator(".graph-node").evaluate((el) => [el.scrollHeight, el.clientHeight]);
      expect(frame[0]).toBeLessThanOrEqual(frame[1]);
    });

    await test.step("the stored size is what it was: the layout keeps 160 by 80", async () => {
      const [placed] = await view();
      expect([placed.width, placed.height]).toEqual([160, 80]);
    });

    await test.step("the exported drawing frames the box the same way: the whole name, no ellipsis", async () => {
      const svg = await (await page.request.get(`${arch}/diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
      expect(svg).not.toContain("…");
      for (const word of name.split(" ")) expect(svg).toContain(word);
      const rect = svg.match(/<rect x="[\d.-]+" y="[\d.-]+" width="([\d.]+)" height="([\d.]+)" rx="6"/);
      expect(rect).not.toBeNull();
      expect(Number(rect![2])).toBeGreaterThan(80);
    });

    await test.step("a symbol changed later on the element's type reaches the box without the diagram being opened first", async () => {
      const set = await page.request.put(`${arch}/elements/${element.id}`, { headers: adminHeaders, data: { symbol_id: null, version } });
      expect(set.ok(), await set.text()).toBeTruthy();
      const typeSymbol = await uploadSymbol(page.request, arch, adminHeaders, `Type ${suffix}`);
      const patched = await page.request.patch(`${arch}/element-types/${type.id}`, { headers: adminHeaders, data: { symbol_id: typeSymbol } });
      expect(patched.ok(), await patched.text()).toBeTruthy();
      await page.goto(url);
      await expect(page.getByLabel(`${name}, node`, { exact: true }).locator(".graph-node-symbol")).toBeVisible();
      await expect.poll(async () => (await frameOf(page, name)).height).toBeGreaterThan(plainHeight + 30);
      const [placed] = await view();
      expect([placed.width, placed.height]).toEqual([160, 80]);
    });
  });

  test("a resize cannot make the box smaller than its content, and reloading keeps the size chosen", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchBoxMin", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
    const name = `${LONG_NAME} ${suffix}`;
    const symbolId = await uploadSymbol(page.request, arch, adminHeaders, `Board ${suffix}`);
    const made = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, symbol_id: symbolId, activate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const diagram = await (await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } })).json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    const node = page.getByLabel(`${name}, node`, { exact: true });
    await expect(node.locator(".graph-node-symbol")).toBeVisible();
    const fitted = await frameOf(page, name);

    await test.step("keyboard shrinking stops at the content's size", async () => {
      await node.focus();
      await page.keyboard.press("Enter");
      for (let i = 0; i < 12; i += 1) await page.keyboard.press("Alt+ArrowUp");
      await expect.poll(async () => (await frameOf(page, name)).height).toBe(fitted.height);
    });

    await test.step("growing the box is kept: saved, it is stored at that size and reloads at it", async () => {
      for (let i = 0; i < 4; i += 1) await page.keyboard.press("Alt+ArrowRight");
      const saved = page.waitForResponse((r) => r.url().includes("/layout") && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save diagram", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      const [placed] = (await (await page.request.get(`${arch}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json()).nodes;
      expect(placed.width).toBeGreaterThan(fitted.width);
      await page.reload();
      await expect.poll(async () => (await frameOf(page, name)).width).toBe(placed.width);
    });
  });
});
