import { expect, test, type Locator, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { clickMenuRow } from "../../menuTree";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/**
 * Creates an element and a state machine diagram on it (Start, Idle and Running, with a transition from Idle to Running) through
 * the API as setup, opens it, and returns what a test needs to read the stored result.
 */
async function openMachine(page: Page, label: string) {
  const { suffix, project, adminHeaders } = await setUpOrg(page, label, true, "System Architecture");
  const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
  const types = await (await page.request.get(`${base}/element-types`, { headers: adminHeaders })).json();
  const element = await page.request.post(`${base}/elements`, { headers: adminHeaders, data: { name: `Gateway ${suffix}`, element_type_id: types[0].id, activate: true } });
  expect(element.ok(), await element.text()).toBeTruthy();
  const created = await page.request.post(`${base}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Modes ${suffix}`, element_id: (await element.json()).id } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const diagram = await created.json();
  let version = diagram.version;
  const ids: Record<string, string> = {};
  for (const [name, kind, x] of [["Start", "initial", 40], ["Idle", "state", 160], ["Running", "state", 420]] as const) {
    const added = await page.request.post(`${base}/state-machine-diagrams/${diagram.id}/states`, {
      headers: adminHeaders,
      data: { version, name, kind, x, y: 40, width: kind === "initial" ? 20 : 160, height: kind === "initial" ? 20 : 64 },
    });
    expect(added.ok(), await added.text()).toBeTruthy();
    const body = await added.json();
    ids[name] = body.id;
    version = body.state_machine_diagram_version;
  }
  const line = await page.request.post(`${base}/state-machine-diagrams/${diagram.id}/transitions`, {
    headers: adminHeaders, data: { version, source_state_id: ids.Idle, target_state_id: ids.Running, event: "start" },
  });
  expect(line.ok(), await line.text()).toBeTruthy();
  const transitionId = (await line.json()).id;
  await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
  await expect(page.getByLabel("Idle, node", { exact: true })).toBeVisible();
  const model = async () => (await (await page.request.get(`${base}/state-machine-diagrams/${diagram.id}/model`, { headers: adminHeaders })).json());
  const exported = async (kind: "svg" | "mermaid") => (await page.request.get(`${base}/state-machine-diagrams/${diagram.id}/${kind}`, { headers: adminHeaders })).text();
  return { ids, transitionId, model, exported, leaders: page.locator(".react-flow__edge.graph-leader") };
}

async function saveDrawing(page: Page) {
  const saved = page.waitForResponse((r) => r.url().endsWith("/layout") && r.request().method() === "PUT");
  await page.getByRole("button", { name: "Save diagram", exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeDisabled();
}

/**
 * Focuses a note and presses Enter until it is selected (its text field is in the Selection card). A box that has just been
 * redrawn (after Undo) can lose the focus between the two steps under load, and Delete acts on the selection, so the key is
 * pressed only once the selection has reached the page.
 */
async function selectNoteWithTheKeyboard(page: Page, note: Locator) {
  await expect(async () => {
    await note.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("textbox", { name: "Note text" })).toBeVisible({ timeout: 1500 });
  }).toPass();
}

/** Places a note from the Add menu with its text typed, and returns it. */
async function addNote(page: Page, text: string) {
  await page.getByRole("button", { name: "Add to diagram" }).click();
  await clickMenuRow(page, "Add note");
  await page.getByRole("textbox", { name: "Note text" }).fill(text);
  await page.getByRole("textbox", { name: "Note text" }).blur();
  await page.locator(".graph-canvas").first().scrollIntoViewIfNeeded();
  return page.getByLabel(`${text}, node`, { exact: true });
}

/**
 * Job to be done: an architect explains a state machine diagram with notes and points each at the state or transition it is about.
 * The notes and their leaders are saved with the drawing, survive a reload, and appear in the server's SVG and Mermaid exports.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the element and the diagram are created through
 * the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: notes on a state machine diagram", () => {
  test("a note with a leader to a state and one to a transition is saved and kept after a reload", async ({ page }) => {
    const { ids, transitionId, model, leaders } = await openMachine(page, "ArchSmdNote");

    await test.step("Add note places a note and its text is typed in the Selection card", async () => {
      await addNote(page, "Wait for the motor");
      await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeEnabled();
    });

    await test.step("Add leader twice and aim each from the card: one at a state, one at a transition", async () => {
      await page.getByRole("button", { name: "Add leader", exact: true }).click();
      await page.getByRole("combobox", { name: "Points at", exact: true }).selectOption(`state:${ids.Idle}`);
      await page.getByRole("button", { name: "Select note", exact: true }).click();
      await page.getByRole("button", { name: "Add leader", exact: true }).click();
      await expect(page.getByText("Leader 2", { exact: true })).toBeVisible();
      await page.getByRole("combobox", { name: "Points at", exact: true }).selectOption(`transition:${transitionId}`);
      await expect(leaders).toHaveCount(2);
    });

    await test.step("Save stores the note and both leaders in order", async () => {
      await saveDrawing(page);
      const [note] = (await model()).notes;
      expect(note.text).toBe("Wait for the motor");
      expect(note.leaders.map((l: { kind: string }) => l.kind)).toEqual(["state", "transition"]);
      expect(note.leaders[0].state_id).toBe(ids.Idle);
      expect(note.leaders[1].transition_id).toBe(transitionId);
    });

    await test.step("a reload draws the note and both leaders", async () => {
      await page.reload();
      await expect(page.getByLabel("Wait for the motor, node", { exact: true })).toBeVisible();
      await expect(leaders).toHaveCount(2);
    });
  });

  test("the server's SVG and Mermaid exports carry the note beside its state", async ({ page }) => {
    const { ids, model, exported } = await openMachine(page, "ArchSmdExport");
    await addNote(page, "Check the limit");
    await page.getByRole("button", { name: "Add leader", exact: true }).click();
    await page.getByRole("combobox", { name: "Points at", exact: true }).selectOption(`state:${ids.Running}`);
    await saveDrawing(page);
    expect((await model()).notes).toHaveLength(1);
    const svg = await exported("svg");
    expect(svg).toContain("Check the limit");
    expect(svg).toContain("data-note=");
    expect(await exported("mermaid")).toMatch(/note (left|right) of s\d+\n\s+Check the limit\n\s+end note/);
  });

  test("the Delete key removes a selected note at once, Undo brings it back, and Note and Comment are never both on", async ({ page }) => {
    const { model } = await openMachine(page, "ArchSmdDelete");
    const note = await addNote(page, "Temporary");
    await saveDrawing(page);

    await test.step("Delete removes the note with no question, and Save stores the removal", async () => {
      await selectNoteWithTheKeyboard(page, note);
      await page.keyboard.press("Delete");
      await expect(page.getByLabel("Temporary, node", { exact: true })).toHaveCount(0);
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await page.getByRole("button", { name: "Undo", exact: true }).click();
      await expect(page.getByLabel("Temporary, node", { exact: true })).toBeVisible();
      await selectNoteWithTheKeyboard(page, page.getByLabel("Temporary, node", { exact: true }));
      await page.keyboard.press("Delete");
      await saveDrawing(page);
      expect((await model()).notes).toEqual([]);
    });

    await test.step("Note and Comment switch each other off", async () => {
      const noteToggle = page.getByRole("button", { name: "Note", exact: true });
      const commentToggle = page.getByRole("button", { name: "Comment", exact: true });
      await noteToggle.click();
      await expect(noteToggle).toHaveAttribute("aria-pressed", "true");
      await commentToggle.click();
      await expect(commentToggle).toHaveAttribute("aria-pressed", "true");
      await expect(noteToggle).toHaveAttribute("aria-pressed", "false");
      await page.keyboard.press("Escape");
      await expect(commentToggle).toHaveAttribute("aria-pressed", "false");
    });
  });
});
