import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { clickMenuRow } from "../../menuTree";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** The editors' Selection card. */
const selectionCard = (page: Page) => page.getByRole("region", { name: "Selection" });

/** Creates an active element through the API (setup) and returns its id. */
async function createElement(request: APIRequestContext, base: string, headers: Record<string, string>, name: string): Promise<string> {
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/**
 * Creates an element and a state machine diagram on it (Start, Idle and Running, and a transition from Idle to Running) through
 * the API as setup, and opens it.
 */
async function openMachine(page: Page, label: string) {
  const { suffix, project, adminHeaders } = await setUpOrg(page, label, true, "System Architecture");
  const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
  const elementId = await createElement(page.request, base, adminHeaders, `Gateway ${suffix}`);
  const created = await page.request.post(`${base}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Modes ${suffix}`, element_id: elementId } });
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
  const transitionId = (await line.json()).id as string;
  await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
  await expect(page.getByLabel("Idle, node", { exact: true })).toBeVisible();
  const model = async () => (await (await page.request.get(`${base}/state-machine-diagrams/${diagram.id}/model`, { headers: adminHeaders })).json());
  return { suffix, ids, transitionId, model, base, adminHeaders };
}

/** The names of the states the stored model holds. */
async function stateNames(model: () => Promise<{ states: { name: string }[] }>): Promise<string[]> {
  return (await model()).states.map((s) => s.name).sort();
}

/** Moves the focus off every field and the canvas, to the page heading, the way a click on empty page space does. */
async function focusNowhere(page: Page) {
  await page.getByRole("heading", { level: 1 }).click();
}

/**
 * Job to be done: an architect removes a symbol with the Delete key (the key labelled Delete on a Mac sends Backspace), however
 * the symbol came to be selected and wherever the focus is, as long as it is not in a text field or a dialog. A state or a
 * transition asks first, naming what goes with it; a box on a block diagram comes off the drawing at once and Undo puts it back.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements and diagrams are created through the
 * API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: the Delete key", () => {
  for (const key of ["Delete", "Backspace"]) {
    test(`${key} asks to delete the selected state and a Cancel keeps everything`, async ({ page }) => {
      const { model } = await openMachine(page, `ArchDel${key}`);
      await page.getByLabel("Idle, node", { exact: true }).click();
      await expect(selectionCard(page).getByRole("textbox", { name: /^Name/ })).toHaveValue("Idle");
      await page.keyboard.press(key);
      const dialog = page.getByRole("dialog", { name: "Delete this state?" });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).toHaveCount(0);
      expect(await stateNames(model)).toEqual(["Idle", "Running", "Start"]);
      await expect(page.getByLabel("Idle, node", { exact: true })).toBeVisible();
    });
  }

  test("the key reaches a state selected from anywhere: the card, the outline and a click on the page", async ({ page }) => {
    const { model } = await openMachine(page, "ArchDelFocus");
    const dialog = page.getByRole("dialog", { name: "Delete this state?" });

    await test.step("with the focus on a card heading after the state was selected", async () => {
      await page.getByLabel("Running, node", { exact: true }).click();
      await selectionCard(page).getByRole("heading").first().click();
      await page.keyboard.press("Backspace");
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Cancel" }).click();
    });

    await test.step("with the focus on the page after the state was selected", async () => {
      await page.getByLabel("Running, node", { exact: true }).click();
      await focusNowhere(page);
      await page.keyboard.press("Delete");
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Cancel" }).click();
    });

    await test.step("with the focus on the toolbar", async () => {
      await page.getByLabel("Running, node", { exact: true }).click();
      await page.getByRole("button", { name: "Add to diagram" }).focus();
      await page.keyboard.press("Delete");
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Cancel" }).click();
    });
    expect(await stateNames(model)).toEqual(["Idle", "Running", "Start"]);
  });

  test("an initial symbol is deleted by the key like any other state", async ({ page }) => {
    const { model } = await openMachine(page, "ArchDelMarker");
    await page.getByLabel("Initial state, node", { exact: true }).click();
    await page.keyboard.press("Backspace");
    const dialog = page.getByRole("dialog", { name: "Delete this state?" });
    await expect(dialog).toBeVisible();
    const code = ((await model()).states as { name: string; unique_code: string }[]).find((s) => s.name === "Start")!.unique_code;
    await dialog.getByRole("textbox").fill(code);
    const removed = page.waitForResponse((r) => /\/states\/[^/]+$/.test(r.url()) && r.request().method() === "DELETE");
    await dialog.getByRole("button", { name: "Delete" }).click();
    expect((await removed).ok()).toBeTruthy();
    await expect(page.getByLabel("Initial state, node", { exact: true })).toHaveCount(0);
    expect(await stateNames(model)).toEqual(["Idle", "Running"]);
  });

  test("a state added at once is deleted by the key once the name field is left", async ({ page }) => {
    const { model } = await openMachine(page, "ArchDelAdded");
    const created = page.waitForResponse((r) => r.url().endsWith("/states") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Add to diagram" }).click();
    await clickMenuRow(page, "State");
    expect((await created).ok()).toBeTruthy();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const name = selectionCard(page).getByRole("textbox", { name: /^Name/ });
    await expect(name).toBeFocused();
    await expect(name).toHaveValue(/^State \d+$/);

    await test.step("in the name field the key edits the text and asks nothing", async () => {
      // A name just added is selected in its field, so the first Backspace clears it, as typing would replace it.
      await page.keyboard.press("Backspace");
      await expect(name).toHaveValue("");
      await page.keyboard.type("Gatewa");
      await page.keyboard.press("Delete");
      await page.keyboard.press("Backspace");
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await page.keyboard.type("ay");
      await expect(name).toHaveValue("Gateway");
    });

    await test.step("Escape returns the focus to the symbol and the key then asks to delete it", async () => {
      await page.keyboard.press("Escape");
      await expect(page.getByLabel("Gateway, node", { exact: true })).toBeFocused();
      await page.keyboard.press("Backspace");
      await expect(page.getByRole("dialog", { name: "Delete this state?" })).toBeVisible();
      await page.getByRole("dialog", { name: "Delete this state?" }).getByRole("button", { name: "Cancel" }).click();
    });
    expect((await stateNames(model)).length).toBe(4);
  });

  test("the key does nothing in a text field or a dialog, and for a read-only moment of nothing selected", async ({ page }) => {
    const { model } = await openMachine(page, "ArchDelBlocked");
    await test.step("nothing is selected", async () => {
      await focusNowhere(page);
      await page.keyboard.press("Delete");
      await expect(page.getByRole("dialog")).toHaveCount(0);
    });
    await test.step("a text field keeps the key for its text", async () => {
      await page.getByLabel("Idle, node", { exact: true }).click();
      const name = selectionCard(page).getByRole("textbox", { name: /^Name/ });
      await name.click();
      await page.keyboard.press("End");
      await page.keyboard.press("Backspace");
      await expect(name).toHaveValue("Idl");
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await page.keyboard.press("Control+z");
      await name.fill("Idle");
      await name.blur();
    });
    await test.step("a second press while the dialog is open leaves one dialog", async () => {
      await page.getByLabel("Idle, node", { exact: true }).click();
      await page.keyboard.press("Delete");
      await expect(page.getByRole("dialog", { name: "Delete this state?" })).toBeVisible();
      await page.keyboard.press("Delete");
      await page.keyboard.press("Backspace");
      await expect(page.getByRole("dialog")).toHaveCount(1);
      await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
    });
    expect((await stateNames(model)).length).toBe(3);
  });

  test("a selected transition asks to delete it, from the canvas and with the focus elsewhere", async ({ page }) => {
    const { model, transitionId } = await openMachine(page, "ArchDelTransition");
    const edge = page.locator(`.react-flow__edge[data-id="${transitionId}"]`);
    await edge.focus();
    await page.keyboard.press("Enter");
    await expect(selectionCard(page).getByRole("group", { name: "Transition details" })).toBeVisible();
    await focusNowhere(page);
    await page.keyboard.press("Backspace");
    const dialog = page.getByRole("dialog", { name: "Delete this transition?" });
    await expect(dialog).toBeVisible();
    const removed = page.waitForResponse((r) => /\/transitions\/[^/]+$/.test(r.url()) && r.request().method() === "DELETE");
    await dialog.getByRole("button", { name: "Delete" }).click();
    expect((await removed).ok()).toBeTruthy();
    await expect.poll(async () => (await model()).transitions.length).toBe(0);
    expect(await stateNames(model)).toEqual(["Idle", "Running", "Start"]);
  });

  test("the block diagram editor takes a box off the drawing with the key and Undo puts it back", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchDelBlock", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    await createElement(page.request, arch, adminHeaders, `Hub ${suffix}`);
    await createElement(page.request, arch, adminHeaders, `Spoke ${suffix}`);
    const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
    const diagram = await diagramRes.json();
    const hub = page.getByLabel(`Hub ${suffix}, node`, { exact: true });
    const spoke = page.getByLabel(`Spoke ${suffix}, node`, { exact: true });
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(hub).toBeVisible();
    await expect(spoke).toBeVisible();

    await test.step("a clicked box is removed from the drawing by Backspace", async () => {
      await hub.click();
      await page.keyboard.press("Backspace");
      await expect(hub).toHaveCount(0);
      await expect(spoke).toBeVisible();
    });

    await test.step("Undo puts it back, and with the focus on the page Delete removes it again", async () => {
      await page.getByRole("button", { name: "Undo" }).click();
      await expect(hub).toBeVisible();
      await hub.click();
      await focusNowhere(page);
      await page.keyboard.press("Delete");
      await expect(hub).toHaveCount(0);
      await page.getByRole("button", { name: "Undo" }).click();
      await expect(hub).toBeVisible();
    });

    await test.step("the Selection card's name field keeps the key for its text", async () => {
      await hub.click();
      const name = page.getByRole("group", { name: "Element details" }).getByRole("textbox", { name: /^Name/ });
      await name.click();
      await page.keyboard.press("End");
      await page.keyboard.press("Backspace");
      await expect(name).toHaveValue(`Hub ${suffix.toString().slice(0, -1)}`);
      await expect(hub).toBeVisible();
      await name.fill(`Hub ${suffix}`);
      await name.blur();
    });

    await test.step("Remove from diagram's tooltip and the toolbar help name the key", async () => {
      await hub.click();
      await selectionCard(page).getByRole("button", { name: "Remove from diagram" }).hover();
      await expect(page.getByRole("tooltip")).toContainText(/Delete|Backspace/);
    });
  });
});
