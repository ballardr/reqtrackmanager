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
  await expect(page.getByLabel(`Alpha ${suffix}, node`, { exact: true })).toBeVisible();
  const stored = async () => (await (await page.request.get(`${arch}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json()).notes;
  const svg = async () => (await page.request.get(`${arch}/diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
  return { stored, svg };
}

async function saveLayout(page: Page) {
  const saved = page.waitForResponse((r) => r.url().includes("/layout") && r.request().method() === "PUT");
  await page.getByRole("button", { name: "Save diagram", exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeDisabled();
}

/**
 * Job to be done: an architect writes a note with a heading and two paragraphs, aligns it, and gets the same lines on the
 * canvas, after a reload and in the server's drawing of the diagram.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the element and the diagram are created through
 * the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: a note's title, line breaks and alignment", () => {
  test("a title and two paragraphs are drawn, aligned, kept after a reload and drawn the same by the server", async ({ page }) => {
    const { stored, svg } = await openDiagram(page, "ArchNoteText");

    await test.step("a new note takes a title, two paragraphs and an alignment from its card", async () => {
      await page.getByRole("button", { name: "Add to diagram" }).click();
      await clickMenuRow(page, "Add note");
      await page.getByRole("textbox", { name: "Title" }).fill("Gateway rule");
      await page.getByRole("textbox", { name: "Title" }).blur();
      await page.getByRole("textbox", { name: "Note text" }).fill("First paragraph\n\nSecond paragraph");
      await page.getByRole("textbox", { name: "Note text" }).blur();
      await page.getByRole("combobox", { name: "Alignment", exact: true }).selectOption("right");
      const node = page.getByLabel(/^Gateway rule: First paragraph\s+Second paragraph, node$/);
      await expect(node.locator(".graph-node-title")).toHaveText("Gateway rule");
      await expect(node.locator(".graph-node-label")).toHaveCSS("white-space", "pre-line");
      await expect(node.locator(".graph-node")).toHaveClass(/graph-node-align-right/);
    });

    await test.step("saving stores the title, the typed breaks and the alignment", async () => {
      await saveLayout(page);
      const [note] = await stored();
      expect(note).toMatchObject({ title: "Gateway rule", text: "First paragraph\n\nSecond paragraph", text_align: "right" });
    });

    await test.step("a reload shows them again in the card and on the canvas", async () => {
      await page.reload();
      const node = page.getByLabel(/^Gateway rule: First paragraph\s+Second paragraph, node$/);
      await expect(node).toBeVisible();
      await node.click();
      await expect(page.getByRole("textbox", { name: "Title" })).toHaveValue("Gateway rule");
      await expect(page.getByRole("textbox", { name: "Note text" })).toHaveValue("First paragraph\n\nSecond paragraph");
      await expect(page.getByRole("combobox", { name: "Alignment", exact: true })).toHaveValue("right");
    });

    await test.step("the server's drawing has the title in bold, each typed line and the right alignment", async () => {
      const group = (await svg()).match(/<g data-note="[^"]+">(.*?)<\/g>/)![1];
      const lines = [...group.matchAll(/<text ([^>]*)>(.*?)<\/text>/g)];
      expect(lines.map((l) => l[2])).toEqual(["Gateway rule", "First paragraph", "", "Second paragraph"]);
      expect(lines[0][1]).toContain('font-weight="bold"');
      expect(lines.every((l) => l[1].includes('text-anchor="end"'))).toBe(true);
    });
  });

  test("a title and an alignment are one undo step each and clear with the field", async ({ page }) => {
    await openDiagram(page, "ArchNoteUndo");
    await page.getByRole("button", { name: "Add to diagram" }).click();
    await clickMenuRow(page, "Add note");
    await page.getByRole("textbox", { name: "Note text" }).fill("Body");
    await page.getByRole("textbox", { name: "Note text" }).blur();
    await page.getByRole("textbox", { name: "Title" }).fill("Head");
    await page.getByRole("textbox", { name: "Title" }).blur();
    await expect(page.getByLabel("Head: Body, node", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(page.getByLabel("Body, node", { exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Title" })).toHaveValue("");
  });
});
