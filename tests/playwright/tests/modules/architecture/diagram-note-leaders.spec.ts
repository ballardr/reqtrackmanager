import { expect, test, type Locator, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { clickMenuRow } from "../../menuTree";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** Opens a fresh diagram with two placed elements and returns what a test needs to read the stored result. */
async function openDiagram(page: Page, label: string) {
  const { suffix, project, adminHeaders } = await setUpOrg(page, label, true, "System Architecture");
  const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
  const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
  const ids: string[] = [];
  for (const name of [`Alpha ${suffix}`, `Bravo ${suffix}`]) {
    const created = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, activate: true } });
    expect(created.ok(), await created.text()).toBeTruthy();
    ids.push((await created.json()).id);
  }
  const made = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
  expect(made.ok(), await made.text()).toBeTruthy();
  const diagram = await made.json();
  await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
  await expect(page.getByLabel(`Alpha ${suffix}, node`, { exact: true })).toBeVisible();
  const stored = async () => (await (await page.request.get(`${arch}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json()).notes;
  return { suffix, ids, stored, leaders: page.locator(".react-flow__edge.graph-leader") };
}

/** Places a note from the Add menu, with its text typed, and returns its canvas node. */
async function addNote(page: Page, text: string): Promise<Locator> {
  await page.getByRole("button", { name: "Add to diagram" }).click();
  await clickMenuRow(page, "Add note");
  await page.getByRole("textbox", { name: "Note text" }).fill(text);
  await page.getByRole("textbox", { name: "Note text" }).blur();
  return page.getByLabel(`${text}, node`, { exact: true });
}

async function saveLayout(page: Page) {
  const saved = page.waitForResponse((r) => r.url().includes("/layout") && r.request().method() === "PUT");
  await page.getByRole("button", { name: "Save diagram", exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeDisabled();
}

/** The middle of an element on the screen. */
async function centre(locator: Locator) {
  const box = (await locator.boundingBox())!;
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

/**
 * Presses `handle` of `from` and releases at `to`, moving in steps so the canvas sees the line being drawn (which also shows
 * the points of a box the pointer nears).
 */
async function drawLeader(page: Page, from: Locator, handleId: string, to: { x: number; y: number }) {
  const box = (await from.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const handle = from.locator(`.react-flow__handle[data-handleid="${handleId}"]`);
  const start = await centre(handle);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move((start.x + to.x) / 2, (start.y + to.y) / 2, { steps: 6 });
  await page.mouse.move(to.x, to.y, { steps: 6 });
  await page.mouse.up();
}

/**
 * Job to be done: an architect explains a drawing with notes and points each at what it describes, drawing the line from the
 * note's own attach point like any connection: to empty canvas, onto a box, with vertices and a dot or an arrowhead at either
 * end, several to one note. The leaders are stored with the drawing and survive a reload.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements and the diagram are created through
 * the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: leaders drawn from a note", () => {
  test("a leader drawn to empty canvas gets a vertex and a dot end, and is kept after a reload", async ({ page }) => {
    const { stored, leaders } = await openDiagram(page, "ArchLeaderDraw");
    const note = await addNote(page, "Watch this gap");

    await test.step("dragging from the note's attach point to empty canvas draws a selected leader", async () => {
      const pane = (await page.locator(".react-flow__pane").boundingBox())!;
      await drawLeader(page, note, "bottom", { x: pane.x + pane.width - 90, y: pane.y + pane.height - 60 });
      await expect(leaders).toHaveCount(1);
      await expect(page.getByText("Leader 1", { exact: true })).toBeVisible();
      await expect(page.getByRole("combobox", { name: "Points at", exact: true })).toHaveValue("spot");
      await expect(page.getByRole("combobox", { name: "Starts at", exact: true })).toHaveValue("bottom");
      await expect(page.getByRole("combobox", { name: "End style", exact: true })).toHaveValue("arrow");
    });

    await test.step("dragging the middle of the selected leader adds a vertex", async () => {
      const handle = page.locator(".graph-segment-handle");
      await expect(handle).toHaveCount(1);
      const from = await centre(handle);
      await page.mouse.move(from.x, from.y);
      await page.mouse.down();
      await page.mouse.move(from.x - 60, from.y - 50, { steps: 8 });
      await page.mouse.up();
      await expect(page.locator(".graph-waypoint")).toHaveCount(1);
    });

    await test.step("the end can be a dot, and the start too", async () => {
      await page.getByRole("combobox", { name: "End style", exact: true }).selectOption("dot");
      await page.getByRole("combobox", { name: "Start style", exact: true }).selectOption("arrow");
      await expect(leaders.locator("path.react-flow__edge-path")).toHaveAttribute("marker-end", /graph-dot-/);
      await expect(leaders.locator("path.react-flow__edge-path")).toHaveAttribute("marker-start", /.+/);
    });

    await test.step("Save stores the leader and a reload draws it", async () => {
      await saveLayout(page);
      const [saved] = await stored();
      expect(saved.leaders).toHaveLength(1);
      expect(saved.leaders[0]).toMatchObject({ kind: "point", start_point: "bottom", start_style: "arrow", end_style: "dot", smooth: false });
      expect(saved.leaders[0].points).toHaveLength(1);
      await page.reload();
      await expect(leaders).toHaveCount(1);
      await expect(leaders.locator("path.react-flow__edge-path")).toHaveAttribute("marker-end", /graph-dot-/);
    });
  });

  test("a leader drawn onto a box follows the box when it is moved", async ({ page }) => {
    const { ids, suffix, stored, leaders } = await openDiagram(page, "ArchLeaderBox");
    const note = await addNote(page, "About Bravo");
    const bravo = page.getByLabel(`Bravo ${suffix}, node`, { exact: true });

    await test.step("released on one of the box's attach points, the leader ends at that box", async () => {
      const target = bravo.locator('.react-flow__handle[data-handleid="top"]');
      const noteBox = (await note.boundingBox())!;
      const bravoBox = (await bravo.boundingBox())!;
      await page.mouse.move(noteBox.x + noteBox.width / 2, noteBox.y + noteBox.height / 2);
      const start = await centre(note.locator('.react-flow__handle[data-handleid="top"]'));
      await page.mouse.move(start.x, start.y);
      await page.mouse.down();
      await page.mouse.move(bravoBox.x + bravoBox.width / 2, bravoBox.y - 40, { steps: 10 });
      const end = await centre(target);
      await page.mouse.move(end.x, end.y, { steps: 6 });
      await page.mouse.up();
      await expect(leaders).toHaveCount(1);
      await expect(page.getByRole("combobox", { name: "Points at", exact: true })).toHaveValue(`element:${ids[1]}`);
    });

    await test.step("moving the box moves the end of the leader", async () => {
      const path = leaders.locator("path.react-flow__edge-path");
      const before = await path.getAttribute("d");
      const from = await centre(bravo);
      await page.mouse.move(from.x, from.y + 10);
      await page.mouse.down();
      await page.mouse.move(from.x + 80, from.y + 70, { steps: 8 });
      await page.mouse.up();
      await expect.poll(async () => path.getAttribute("d")).not.toBe(before);
    });

    await test.step("Save stores a leader to the element", async () => {
      await saveLayout(page);
      const [saved] = await stored();
      expect(saved.leaders).toMatchObject([{ kind: "element", element_id: ids[1], end_style: "arrow" }]);
    });
  });

  test("a note takes two leaders, added without a pointer, and removing one keeps the other", async ({ page }) => {
    const { ids, stored, leaders } = await openDiagram(page, "ArchLeaderTwo");
    const note = await addNote(page, "Two things");

    await test.step("Add leader twice and aim each from the Selection card", async () => {
      await page.getByRole("button", { name: "Add leader", exact: true }).click();
      await page.getByRole("combobox", { name: "Points at", exact: true }).selectOption(`element:${ids[0]}`);
      await page.getByRole("button", { name: "Select note", exact: true }).click();
      await page.getByRole("button", { name: "Add leader", exact: true }).click();
      await expect(page.getByText("Leader 2", { exact: true })).toBeVisible();
      await page.getByRole("combobox", { name: "Points at", exact: true }).selectOption(`element:${ids[1]}`);
      await expect(leaders).toHaveCount(2);
    });

    await test.step("the note lists both, and Save stores both in order", async () => {
      await page.getByRole("button", { name: "Select note", exact: true }).click();
      await expect(page.getByRole("list", { name: "Leaders" }).getByRole("listitem")).toHaveCount(2);
      await saveLayout(page);
      const [saved] = await stored();
      expect(saved.leaders.map((l: { element_id: string }) => l.element_id)).toEqual([ids[0], ids[1]]);
    });

    await test.step("removing the first leader keeps the second and the note", async () => {
      // A save gives the new note and leaders their stored ids, so the selection is made again.
      await note.click();
      await page.getByRole("button", { name: "Edit leader 1", exact: true }).click();
      await page.getByRole("button", { name: "Remove leader", exact: true }).click();
      await expect(leaders).toHaveCount(1);
      await saveLayout(page);
      const [saved] = await stored();
      expect(saved.text).toBe("Two things");
      expect(saved.leaders.map((l: { element_id: string }) => l.element_id)).toEqual([ids[1]]);
    });
  });
});
