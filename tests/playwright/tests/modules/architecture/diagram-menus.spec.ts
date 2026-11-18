import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { clickMenuRow } from "../../menuTree";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** Creates an active element through the API (setup) and returns its id. */
async function createElement(request: APIRequestContext, base: string, headers: Record<string, string>, name: string): Promise<string> {
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/** Opens the Add to diagram menu and returns the menu list. */
async function openAddMenu(page: Page) {
  await page.getByRole("button", { name: "Add to diagram" }).click();
  const menu = page.getByRole("menu", { name: "Add to diagram" });
  await expect(menu).toBeVisible();
  return menu;
}

/**
 * Job to be done: a menu opened over a diagram goes away when the person clicks elsewhere, and a menu with groups is a
 * tree that opens in place. The editors' canvas (React Flow) stops the mouse press before it reaches the page, so a
 * menu that listened for it stayed open over the diagram.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; records are created through the API as
 * setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: menus over a diagram", () => {
  test("the block diagram editor's Add menu closes on a click on empty canvas, a box and the page outside, and on Escape and Tab", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchMenu", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    await createElement(page.request, arch, adminHeaders, `Hub ${suffix}`);
    const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
    const diagram = await diagramRes.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    const hub = page.getByLabel(`Hub ${suffix}, node`, { exact: true });
    await expect(hub).toBeVisible();
    const trigger = page.getByRole("button", { name: "Add to diagram" });

    await test.step("a click on empty canvas closes it", async () => {
      await openAddMenu(page);
      const pane = page.locator(".react-flow__pane");
      const box = (await pane.boundingBox())!;
      await page.mouse.click(box.x + box.width - 20, box.y + box.height - 20);
      await expect(page.getByRole("menu", { name: "Add to diagram" })).toHaveCount(0);
    });

    await test.step("a click on a box closes it", async () => {
      await openAddMenu(page);
      await hub.click();
      await expect(page.getByRole("menu", { name: "Add to diagram" })).toHaveCount(0);
    });

    await test.step("a click on the page outside the editor closes it", async () => {
      await openAddMenu(page);
      await page.getByRole("heading", { level: 1 }).first().click();
      await expect(page.getByRole("menu", { name: "Add to diagram" })).toHaveCount(0);
    });

    await test.step("the settings gear and the Export menu close on a click on the canvas too", async () => {
      const pane = (await page.locator(".react-flow__pane").boundingBox())!;
      await page.getByRole("button", { name: /^Diagram settings/ }).click();
      await expect(page.getByRole("dialog", { name: "Diagram settings" })).toBeVisible();
      await page.mouse.click(pane.x + pane.width - 20, pane.y + pane.height - 20);
      await expect(page.getByRole("dialog", { name: "Diagram settings" })).toHaveCount(0);
      await page.getByRole("button", { name: "Export", exact: true }).click();
      await expect(page.getByRole("menu", { name: "Export diagram" })).toBeVisible();
      await page.mouse.click(pane.x + pane.width - 20, pane.y + pane.height - 20);
      await expect(page.getByRole("menu", { name: "Export diagram" })).toHaveCount(0);
    });

    await test.step("Escape and Tab close it and return focus to the trigger", async () => {
      await openAddMenu(page);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("menu", { name: "Add to diagram" })).toHaveCount(0);
      await expect(trigger).toBeFocused();
      await openAddMenu(page);
      await page.keyboard.press("Tab");
      await expect(page.getByRole("menu", { name: "Add to diagram" })).toHaveCount(0);
      await expect(trigger).toBeFocused();
    });

    await test.step("a group is a row that opens in place by keyboard, and its rows are text rows, not buttons", async () => {
      const menu = await openAddMenu(page);
      const other = menu.getByRole("menuitem", { name: "Other", exact: true });
      await expect(other).toHaveAttribute("aria-expanded", "false");
      await other.focus();
      await page.keyboard.press("ArrowRight");
      await expect(other).toHaveAttribute("aria-expanded", "true");
      await expect(menu.getByRole("menuitem", { name: "Add existing elements" })).toBeFocused();
      await expect(menu.getByRole("menuitem", { name: "Add existing elements" })).not.toHaveClass(/btn/);
      await page.keyboard.press("Escape");
      await expect(other).toBeFocused();
      await expect(other).toHaveAttribute("aria-expanded", "false");
      await expect(page.getByRole("menu", { name: "Add to diagram" })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("menu", { name: "Add to diagram" })).toHaveCount(0);
    });

    await test.step("an entry in an opened group still works", async () => {
      await openAddMenu(page);
      await clickMenuRow(page, "Add note");
      await expect(page.getByRole("menu", { name: "Add to diagram" })).toHaveCount(0);
      await expect(page.getByRole("region", { name: "Selection" })).toBeVisible();
    });
  });

  test("the state machine editor's Add menu closes on a click on the canvas", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdMenu", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Fan ${suffix}`);
    const created = await page.request.post(`${base}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Fan modes ${suffix}`, element_id: elementId } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    await expect(page.locator('[role="group"][aria-label^="State machine diagram "]')).toBeVisible();

    await openAddMenu(page);
    const pane = (await page.locator(".react-flow__pane").boundingBox())!;
    await page.mouse.click(pane.x + pane.width - 20, pane.y + pane.height - 20);
    await expect(page.getByRole("menu", { name: "Add to diagram" })).toHaveCount(0);
  });
});
