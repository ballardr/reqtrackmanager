import { expect, test, type Locator, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

const SYMBOL_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" fill="none" stroke="#334155" stroke-width="3"/></svg>';

/** Asserts the symbol panel's bubble lies inside the window and holds its Search field, its tiles and its view buttons. */
async function expectPanelFits(page: Page, bubble: Locator): Promise<void> {
  const geometry = await bubble.evaluate((el) => {
    const box = el.getBoundingClientRect();
    const inside = (selector: string) => {
      const found = el.querySelector(selector);
      if (!found) return null;
      const rect = found.getBoundingClientRect();
      return rect.left >= box.left - 1 && rect.right <= box.right + 1;
    };
    return {
      left: box.left, right: box.right, width: window.innerWidth,
      scrollsSideways: el.scrollWidth > el.clientWidth + 1,
      search: inside('[aria-label="Filter symbols"]'), views: inside('[aria-label="Symbol view"]'), list: inside('[role="listbox"], [role="radiogroup"]'),
    };
  });
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(geometry.width);
  expect(geometry.scrollsSideways).toBe(false);
  expect(geometry.search).toBe(true);
  expect(geometry.views).toBe(true);
  expect(geometry.list).toBe(true);
}

/**
 * Job to be done: an architect on a narrow screen selects a box on a diagram and chooses its symbol from the Selection
 * card: the panel the field opens holds the Search field, the symbols and the view buttons inside the window, whatever the
 * card's width, and the choice is stored.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the symbol, element and diagram are API
 * setup, the behaviour under test goes through the UI and the stored read.
 */
test.describe("System Architecture: the symbol picker panel fits a narrow Selection card", () => {
  test("open the picker at a phone width in each view, search, choose, and the choice is stored", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchPickFit", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
    const name = `Gateway ${suffix}`;
    const made = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, activate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const element = await made.json();
    const symbolName = `Edge ${suffix}`;
    const upload = await page.request.post(`${arch}/symbols`, {
      headers: adminHeaders, multipart: { file: { name: `${symbolName}.svg`, mimeType: "image/svg+xml", buffer: Buffer.from(SYMBOL_SVG) }, name: symbolName },
    });
    expect(upload.ok(), await upload.text()).toBeTruthy();
    const diagram = await (await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } })).json();

    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await page.getByLabel(`${name}, node`, { exact: true }).click();
    const trigger = page.getByRole("button", { name: /^Symbol:/ });
    await trigger.scrollIntoViewIfNeeded();
    await trigger.click();
    const bubble = page.getByRole("dialog", { name: "Choose symbol" });
    await expect(bubble).toBeVisible();

    await test.step("the List view fits the window", async () => {
      await expectPanelFits(page, bubble);
    });

    await test.step("the Gallery view fits the window", async () => {
      await bubble.getByRole("group", { name: "Symbol view" }).getByRole("button", { name: "Gallery", exact: true }).click();
      await expect(bubble.getByRole("radiogroup", { name: "Symbols" })).toBeVisible();
      await expectPanelFits(page, bubble);
    });

    await test.step("a search narrows the symbols and a tile is chosen", async () => {
      await bubble.getByLabel("Filter symbols").fill(symbolName.slice(0, 6));
      await bubble.getByRole("radio", { name: symbolName }).click();
      await expect(bubble).toBeHidden();
      await expect(page.getByRole("button", { name: `Symbol: ${symbolName}` })).toBeVisible();
    });

    await test.step("the choice is stored once the card is saved", async () => {
      await page.getByRole("button", { name: "Save element", exact: true }).click();
      await expect.poll(async () => {
        const read = await (await page.request.get(`${arch}/elements/${element.id}`, { headers: adminHeaders })).json();
        return read.symbol_id;
      }).not.toBeNull();
    });
  });

  test("the Selection card holds an element's ports and is no taller than the drawing", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchCardFit", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
    const name = `Gateway ${suffix}`;
    const made = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, activate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const element = await made.json();
    for (let index = 1; index <= 12; index += 1) {
      const port = await page.request.post(`${arch}/elements/${element.id}/ports`, { headers: adminHeaders, data: { name: `Port ${index} with a long descriptive name`, direction: "both" } });
      expect(port.ok(), await port.text()).toBeTruthy();
    }
    const diagram = await (await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } })).json();

    for (const size of [{ width: 390, height: 800 }, { width: 1280, height: 720 }]) {
      await test.step(`at ${size.width} pixels wide the card holds every port and scrolls inside`, async () => {
        await page.setViewportSize(size);
        await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
        await page.getByLabel(`${name}, node`, { exact: true }).click();
        const card = page.getByRole("region", { name: "Selection", exact: true });
        await expect(card.getByLabel(/^Connection type of Port 1 /)).toBeVisible();
        const geometry = await card.evaluate((el) => {
          const scroller = el.querySelector<HTMLElement>(".detail-card__scroll");
          const drawing = document.querySelector<HTMLElement>(".react-flow");
          const box = el.getBoundingClientRect();
          const out = Array.from(el.querySelectorAll<HTMLElement>("select, button, input")).filter((c) => {
            const r = c.getBoundingClientRect();
            return r.width > 0 && r.right > box.right + 1.5;
          }).length;
          const sc = el.querySelector<HTMLElement>('.detail-card__scroll');
          const offenders = sc ? Array.from(sc.querySelectorAll<HTMLElement>('*')).filter((c) => { const r = c.getBoundingClientRect(); return r.width > 0 && r.right > sc.getBoundingClientRect().right + 1; }).slice(0, 8).map((c) => `${c.tagName}.${c.className} ${c.getAttribute('aria-label') ?? ''} ${Math.round(c.getBoundingClientRect().right)}>${Math.round(sc.getBoundingClientRect().right)}`) : [];
          return {
            offenders,
            sideways: scroller ? scroller.scrollWidth > scroller.clientWidth + 1 : true,
            cardHeight: box.height, drawingHeight: drawing ? drawing.getBoundingClientRect().height : 0, controlsOutside: out,
            scrolls: scroller ? scroller.scrollHeight > scroller.clientHeight : false,
          };
        });
        expect(geometry.offenders).toEqual([]);
        expect(geometry.sideways).toBe(false);
        expect(geometry.controlsOutside).toBe(0);
        expect(geometry.cardHeight).toBeLessThanOrEqual(geometry.drawingHeight + 1);
        expect(geometry.scrolls).toBe(true);
      });
    }
  });

  test("the Selection card is titled with the selected element and its Save button sits beside the title", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchCardSave", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
    const name = `Gateway ${suffix}`;
    const made = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, activate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const element = await made.json();
    for (let index = 1; index <= 12; index += 1) {
      const port = await page.request.post(`${arch}/elements/${element.id}/ports`, { headers: adminHeaders, data: { name: `Port ${index}`, direction: "both" } });
      expect(port.ok(), await port.text()).toBeTruthy();
    }
    const diagram = await (await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } })).json();
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await page.getByLabel(`${name}, node`, { exact: true }).click();
    const card = page.getByRole("region", { name: "Selection", exact: true });

    await test.step("the heading names the selected element and Save is beside it, unavailable until something changes", async () => {
      await expect(card.locator(".detail-card__title")).toContainText(name);
      await expect(card.getByRole("button", { name: "Save element" })).toBeDisabled();
    });

    await test.step("scrolled to the foot of a long card, Save is still in view and stores the change", async () => {
      await card.getByRole("textbox", { name: /^Name/ }).fill(`${name} renamed`);
      await card.getByRole("group", { name: "Selection content" }).evaluate((el) => { el.scrollTop = el.scrollHeight; });
      const save = card.getByRole("button", { name: "Save element" });
      await expect(save).toBeInViewport();
      await expect(save).toBeEnabled();
      const stored = page.waitForResponse((r) => r.url().includes(`/elements/${element.id}`) && r.request().method() === "PUT");
      await save.click();
      expect((await stored).ok()).toBeTruthy();
      await expect.poll(async () => (await (await page.request.get(`${arch}/elements/${element.id}`, { headers: adminHeaders })).json()).name).toBe(`${name} renamed`);
      await expect(card.locator(".detail-card__title")).toContainText(`${name} renamed`);
    });
  });
});
