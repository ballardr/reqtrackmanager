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

/** Opens a fresh diagram with one placed element and returns the page's project id and diagram id. */
async function openDiagram(page: Page, label: string) {
  const { suffix, project, adminHeaders } = await setUpOrg(page, label, true, "System Architecture");
  const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
  await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
  const res = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
  expect(res.ok(), await res.text()).toBeTruthy();
  const diagram = await res.json();
  await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
  await expect(page.getByLabel(`Alpha ${suffix}, node`, { exact: true })).toBeVisible();
  return { project, diagram, arch, adminHeaders, suffix };
}

/** Clicks an empty spot of the canvas, a given distance in from its bottom left corner. */
async function clickEmptyCanvas(page: Page, fromLeft: number) {
  const pane = (await page.locator(".react-flow__pane").boundingBox())!;
  await page.mouse.click(pane.x + fromLeft, pane.y + pane.height - 60);
}

/**
 * Job to be done: an architect labels a drawing with plain text, and places notes as quickly as a comment: a note with no
 * tone shows only its words, and a Note mode turns each click on empty canvas into a note with the cursor in its text.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the element and diagram are created through
 * the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: notes with no tone and Note mode", () => {
  test("a note with no tone draws only its text, and the tone is kept after a save and a reload", async ({ page }) => {
    const { diagram } = await openDiagram(page, "ArchNone");
    await page.getByRole("button", { name: "Add to diagram" }).click();
    await clickMenuRow(page, "Add note");
    await page.getByRole("textbox", { name: "Note text" }).fill("Plain label");
    await page.getByRole("combobox", { name: "Tone" }).selectOption("none");
    const saved = page.waitForResponse((r) => r.url().includes(`/diagrams/${diagram.id}/layout`) && r.request().method() === "PUT");
    await page.getByRole("button", { name: "Save diagram", exact: true }).click();
    expect((await saved).ok()).toBeTruthy();

    await page.reload();
    const note = page.getByLabel("Plain label, node", { exact: true });
    await expect(note).toBeVisible();
    await expect(note.locator(".graph-node-caption")).toHaveCount(0);
    await expect(note.locator(".graph-node")).not.toHaveClass(/graph-node-dashed/);
    await expect(note.locator(".graph-node")).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  });

  test("Note mode places a note at each click, selects it for typing, and Escape leaves the mode", async ({ page }) => {
    await openDiagram(page, "ArchNmode");
    const noteSwitch = page.getByRole("button", { name: "Note", exact: true });
    const commentSwitch = page.getByRole("button", { name: "Comment", exact: true });
    await noteSwitch.click();
    await expect(noteSwitch).toHaveAttribute("aria-pressed", "true");

    await clickEmptyCanvas(page, 120);
    const text = page.getByRole("textbox", { name: "Note text" });
    await expect(text).toBeFocused();
    await text.fill("First");
    await page.getByRole("combobox", { name: "Tone" }).focus();

    await clickEmptyCanvas(page, 420);
    await expect(page.getByRole("textbox", { name: "Note text" })).toBeFocused();
    await expect(page.locator(".graph-node-tone")).toHaveCount(2);

    await test.step("Comment and Note are never both on", async () => {
      await commentSwitch.click();
      await expect(commentSwitch).toHaveAttribute("aria-pressed", "true");
      await expect(noteSwitch).toHaveAttribute("aria-pressed", "false");
      await noteSwitch.click();
      await expect(noteSwitch).toHaveAttribute("aria-pressed", "true");
      await expect(commentSwitch).toHaveAttribute("aria-pressed", "false");
    });

    await test.step("Escape leaves the mode and a click no longer places a note", async () => {
      await page.getByRole("heading", { level: 1 }).click();
      await page.keyboard.press("Escape");
      await expect(noteSwitch).toHaveAttribute("aria-pressed", "false");
      await clickEmptyCanvas(page, 700);
      await expect(page.locator(".graph-node-tone")).toHaveCount(2);
    });
  });

  test("Add note from the menu still places a note, and the cursor is in its text", async ({ page }) => {
    await openDiagram(page, "ArchNmenu");
    await page.getByRole("button", { name: "Add to diagram" }).click();
    await clickMenuRow(page, "Add note");
    await expect(page.getByRole("textbox", { name: "Note text" })).toBeFocused();
    await expect(page.locator(".graph-node-tone")).toHaveCount(1);
  });
});
