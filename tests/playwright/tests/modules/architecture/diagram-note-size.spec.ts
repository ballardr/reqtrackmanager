import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { clickMenuRow } from "../../menuTree";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** Opens a fresh diagram with one placed element and returns what a test needs to read the stored and exported result. */
async function openDiagram(page: Page, label: string) {
  const { suffix, project, adminHeaders } = await setUpOrg(page, label, true, "System Architecture");
  const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
  const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
  const created = await page.request.post(`${arch}/elements`, {
    headers: adminHeaders, data: { name: `Alpha ${suffix}`, element_type_id: types[0].id, activate: true },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const made = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
  expect(made.ok(), await made.text()).toBeTruthy();
  const diagram = await made.json();
  await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
  const alpha = page.getByLabel(`Alpha ${suffix}, node`, { exact: true });
  await expect(alpha).toBeVisible();
  const stored = async () => (await (await page.request.get(`${arch}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json()).notes;
  const svg = async () => (await page.request.get(`${arch}/diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
  return { alpha, stored, svg };
}

async function saveLayout(page: Page) {
  const saved = page.waitForResponse((r) => r.url().includes("/layout") && r.request().method() === "PUT");
  await page.getByRole("button", { name: "Save diagram", exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeDisabled();
}

/** The width of an element on the screen. */
async function widthOf(locator: ReturnType<Page["getByLabel"]>) {
  return (await locator.boundingBox())!.width;
}

/**
 * Job to be done: an architect writes a short text note with no box; the note is only as large as its words, so a line drawn to
 * it ends next to the text, and the box follows the text as more is typed. Resizing the note by hand makes its size Manual.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the element and the diagram are created through
 * the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: a note sizes itself to its text", () => {
  test("a note with no tone is as wide as its words, follows the text, and its leader ends next to it", async ({ page }) => {
    const { alpha, stored, svg } = await openDiagram(page, "ArchNoteSize");
    const element = await widthOf(alpha); // a box is 160 units wide, so a note's width is judged against it

    await test.step("a new Automatic note with no tone is much narrower than the default note", async () => {
      await page.getByRole("button", { name: "Add to diagram" }).click();
      await clickMenuRow(page, "Add note");
      await page.getByRole("combobox", { name: "Tone", exact: true }).selectOption("none");
      await expect(page.getByRole("combobox", { name: "Size", exact: true })).toHaveValue("automatic");
      await page.getByRole("textbox", { name: "Note text" }).fill("Short");
      await page.getByRole("textbox", { name: "Note text" }).blur();
      await page.locator(".graph-canvas").first().scrollIntoViewIfNeeded();
      const note = page.getByLabel("Short, node", { exact: true });
      await expect(note).toBeVisible();
      await expect.poll(() => widthOf(note)).toBeLessThan(element / 2);
    });

    await test.step("typing more text makes the box wider and then taller", async () => {
      const note = page.getByLabel("Short, node", { exact: true });
      const before = await note.boundingBox();
      await page.getByRole("textbox", { name: "Note text" }).fill("Short note with a few more words in it");
      await page.getByRole("textbox", { name: "Note text" }).blur();
      const longer = page.getByLabel("Short note with a few more words in it, node", { exact: true });
      await expect.poll(async () => (await longer.boundingBox())!.width).toBeGreaterThan(before!.width);
      await page.getByRole("textbox", { name: "Note text" }).fill(`${"A fairly long remark that has to wrap onto several lines. ".repeat(3)}`);
      await page.getByRole("textbox", { name: "Note text" }).blur();
      await expect.poll(async () => (await page.locator(".react-flow__node-graph").last().boundingBox())!.height).toBeGreaterThan(before!.height * 2);
    });

    await test.step("a leader added from the card starts at the note's edge, next to the text, and is stored and drawn so", async () => {
      await page.getByRole("textbox", { name: "Note text" }).fill("Short");
      await page.getByRole("textbox", { name: "Note text" }).blur();
      await page.getByRole("button", { name: "Add leader" }).click();
      await saveLayout(page);
      const [note] = await stored();
      expect(note).toMatchObject({ size_mode: "automatic", tone: "none", text: "Short" });
      // The stored size is kept, but the drawing uses the frame of the text: its right edge is far less than 160 units away.
      const leader = (await svg()).match(/<line x1="([\d.-]+)" y1="([\d.-]+)"/);
      expect(leader).not.toBeNull();
      expect(Number(leader![1]) - note.x).toBeLessThan(80);
    });
  });

  test("resizing an Automatic note makes it Manual and the choice is kept after a reload", async ({ page }) => {
    const { stored } = await openDiagram(page, "ArchNoteManual");
    await page.getByRole("button", { name: "Add to diagram" }).click();
    await clickMenuRow(page, "Add note");
    await page.getByRole("textbox", { name: "Note text" }).fill("Resize me");
    await page.getByRole("textbox", { name: "Note text" }).blur();
    await page.locator(".graph-canvas").first().scrollIntoViewIfNeeded();
    const size = page.getByRole("combobox", { name: "Size", exact: true });
    await expect(size).toHaveValue("automatic");

    await test.step("a keyboard resize of the selected note makes its size Manual", async () => {
      const note = page.getByLabel("Resize me, node", { exact: true });
      await note.focus();
      await page.keyboard.press("Alt+ArrowRight");
      await expect(size).toHaveValue("manual");
    });

    await test.step("saving stores Manual and a size, and a reload shows Manual in the card", async () => {
      await saveLayout(page);
      const [note] = await stored();
      expect(note.size_mode).toBe("manual");
      await page.reload();
      await page.getByLabel("Resize me, node", { exact: true }).click();
      await expect(page.getByRole("combobox", { name: "Size", exact: true })).toHaveValue("manual");
    });

    await test.step("choosing Automatic again fits the box to the text", async () => {
      await page.getByRole("combobox", { name: "Size", exact: true }).selectOption("automatic");
      await saveLayout(page);
      expect((await stored())[0].size_mode).toBe("automatic");
    });
  });
});
