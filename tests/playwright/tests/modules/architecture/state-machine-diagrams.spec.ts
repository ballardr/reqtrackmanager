import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { buttonHeightGeometry } from "../../../../../frontend/src/testing/buttonHeights";
import { chooseRecordAction, installCleanupHook, loginAs, logout, PASSWORD } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";
import { clickMenuRow } from "../../menuTree";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** Selects a node by keyboard (focus, Enter), the way the canvas documents. */
async function selectNode(page: Page, name: string) {
  const node = page.getByLabel(`${name}, node`, { exact: true });
  await node.focus();
  await page.keyboard.press("Enter");
  return node;
}

/** The Selection card of the editor. */
const selectionCard = (page: Page) => page.getByRole("region", { name: "Selection" });

/** The toolbar's Validation button; its accessible name carries the counts ("Validation: 1 error and 1 warning"). */
const validationButton = (page: Page) => page.getByRole("button", { name: /^Validation:/ });

/** Opens the Validation list and returns it. */
async function openValidation(page: Page) {
  await validationButton(page).click();
  const list = page.getByRole("group", { name: "Validation issues" });
  await expect(list).toBeVisible();
  return list;
}

/** The canvas of the editor (the group named for the diagram; the toolbar's name starts the same way but is not a group). */
const canvasOf = (page: Page) => page.locator('[role="group"][aria-label^="State machine diagram "]');

/** The canvas's top edge on the page itself (the viewport scrolls when the focus moves to the Selection card). */
async function canvasTop(page: Page): Promise<number> {
  return canvasOf(page).evaluate((el) => el.getBoundingClientRect().top + window.scrollY);
}

/**
 * The canvas's top edge once the page above it has finished loading: the record header, tags and cards arrive after the canvas is
 * visible, so a first reading taken under load is a still-moving baseline. Waits until two readings a moment apart agree.
 */
async function settledCanvasTop(page: Page): Promise<number> {
  let last = Number.NaN;
  await expect.poll(async () => {
    const now = await canvasTop(page);
    const same = now === last;
    last = now;
    return same;
  }, { intervals: [300] }).toBe(true);
  return last;
}

/**
 * Adds a state (or marker) from the Add to diagram menu: it is created at once with no form, selected, and its name field in
 * the Selection card holds the focus. `name`, when given, replaces the default name and is stored when the focus leaves the card.
 */
async function addState(page: Page, item: "State" | "Initial state" | "Final state" | "Choice", name?: string) {
  const created = page.waitForResponse((r) => r.url().endsWith("/states") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Add to diagram" }).click();
  await clickMenuRow(page, item);
  expect((await created).ok()).toBeTruthy();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const nameField = selectionCard(page).getByRole("textbox", { name: /^Name/ });
  await expect(nameField).toBeFocused();
  await expect(nameField).toHaveValue(item === "State" ? /^State \d+$/ : item);
  if (name !== undefined) {
    await nameField.fill(name);
    const stored = page.waitForResponse((r) => /\/states\/[^/]+$/.test(r.url()) && r.request().method() === "PUT");
    await page.getByRole("heading", { level: 1 }).click();
    expect((await stored).ok()).toBeTruthy();
    // The model is read again after the store, so the drawing and the lists show the new name.
    await expect(page.getByLabel(`${name}, node`, { exact: true })).toBeVisible();
  }
}

/**
 * Adds a transition from the selected state to another (or itself, named "itself") through the Selection card: it is created at
 * once and empty, selected with the cursor in its event (its guard when it leaves a choice); `event` is then typed there and stored
 * when the focus leaves the card.
 */
async function addTransition(page: Page, targetLabel: RegExp, event = "") {
  const created = page.waitForResponse((r) => r.url().endsWith("/transitions") && r.request().method() === "POST");
  await selectionCard(page).getByLabel("Add transition to").selectOption({ label: await optionLabel(page, targetLabel) });
  expect((await created).ok()).toBeTruthy();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const details = selectionCard(page).getByRole("group", { name: "Transition details" });
  await expect(details.getByLabel("Event", { exact: true })).toBeFocused();
  if (!event) return;
  await details.getByLabel("Event", { exact: true }).fill(event);
  const stored = page.waitForResponse((r) => /\/transitions\/[^/]+$/.test(r.url()) && r.request().method() === "PUT");
  await page.getByRole("heading", { level: 1 }).click();
  expect((await stored).ok()).toBeTruthy();
}

/** The full text of the "Add transition to" option matching `pattern`. */
async function optionLabel(page: Page, pattern: RegExp): Promise<string> {
  const labels = await selectionCard(page).getByLabel("Add transition to").locator("option").allTextContents();
  const found = labels.find((label) => pattern.test(label));
  if (!found) throw new Error(`No "Add transition to" option matches ${pattern}: ${labels.join(", ")}`);
  return found;
}

/** Creates an active element through the API (setup) and returns its id. */
async function createElement(request: APIRequestContext, base: string, headers: Record<string, string>, name: string): Promise<string> {
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/** Creates a state machine diagram with the states and transitions named through the API (setup); returns ids by state name. */
async function createMachine(
  request: APIRequestContext, base: string, headers: Record<string, string>, elementId: string, name: string,
  states: { name: string; kind?: string; x: number; y: number; label?: string }[], transitions: [string, string, string?][],
) {
  const created = await request.post(`${base}/state-machine-diagrams`, { headers, data: { name, element_id: elementId } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const diagram = await created.json();
  let version = diagram.version;
  const ids: Record<string, string> = {};
  for (const state of states) {
    const added = await request.post(`${base}/state-machine-diagrams/${diagram.id}/states`, {
      headers, data: { version, name: state.name, kind: state.kind ?? "state", ...(state.label ? { label: state.label } : {}), x: state.x, y: state.y, width: state.kind && state.kind !== "state" ? 20 : 160, height: state.kind && state.kind !== "state" ? 20 : 64 },
    });
    expect(added.ok(), await added.text()).toBeTruthy();
    const body = await added.json();
    ids[state.name] = body.id;
    version = body.state_machine_diagram_version;
  }
  for (const [from, to, event] of transitions) {
    const added = await request.post(`${base}/state-machine-diagrams/${diagram.id}/transitions`, {
      headers, data: { version, source_state_id: ids[from], target_state_id: ids[to], event: event ?? "" },
    });
    expect(added.ok(), await added.text()).toBeTruthy();
    version = (await added.json()).state_machine_diagram_version;
  }
  return { diagram, ids };
}

/**
 * Job to be done: an architect draws the behaviour of a part: the states it can be in and the transitions between them. The
 * checks tell them what is wrong as they draw (an error blocks activation, a warning never does), a state can sit inside
 * another, the drawing is stored by Save and survives a reload, and reviewers comment on a state.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; the element (and, where the test is about
 * something else, the diagram) are created through the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: state machine diagrams", () => {
  test("an architect creates a state machine diagram, the checks guide the drawing, and it is activated once it is sound", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmd", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gateway = `Gateway ${suffix}`;
    await createElement(page.request, base, adminHeaders, gateway);

    await test.step("New diagram starts with the Type and creates a state machine diagram on the element", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture?tab=diagrams`);
      await page.getByRole("button", { name: "New diagram" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("combobox", { name: "Type" }).selectOption("state_machine");
      await dialog.getByLabel("Name", { exact: true }).fill(`Modes ${suffix}`);
      // The element list loads when the dialog opens, so the option is awaited before it is chosen.
      await expect(dialog.getByLabel("Element").locator("option", { hasText: gateway })).toHaveCount(1);
      const elements = await dialog.getByLabel("Element").locator("option").allTextContents();
      await dialog.getByLabel("Element").selectOption({ label: elements.find((label) => label.includes(gateway))! });
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page).toHaveURL(/\/state-machine-diagrams\//);
      await expect(page.getByRole("heading", { name: `Modes ${suffix}` })).toBeVisible();
    });

    await test.step("the toolbar's buttons and menu triggers are one height", async () => {
      await expect(page.getByRole("toolbar", { name: "State machine diagram editing" })).toBeVisible();
      expect((await page.evaluate(buttonHeightGeometry, undefined)).violations).toEqual([]);
    });

    await test.step("an empty diagram has an error, and activating it is refused with the reason", async () => {
      await expect(validationButton(page)).toHaveAccessibleName("Validation: 1 error");
      const list = await openValidation(page);
      await expect(list.getByText(/no initial state at the top level/)).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(list).toBeHidden();
      await chooseRecordAction(page, "State machine diagram", "Activate directly");
      await expect(page.getByRole("alert").filter({ hasText: /cannot be activated until its errors are resolved/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "Reload state machine diagram" })).toHaveCount(0);
    });

    await test.step("the empty drawing shows no how-to text; the guide is the Add to diagram tooltip", async () => {
      await expect(page.getByText(/No states yet/)).toHaveCount(0);
      await page.getByRole("button", { name: "Add to diagram" }).hover();
      await expect(page.getByRole("tooltip").filter({ hasText: "Initial state: where the machine starts" })).toBeVisible();
    });

    await test.step("an initial state clears the error; a state nobody can reach or leave is a warning", async () => {
      await addState(page, "Initial state");
      await expect(validationButton(page)).toHaveAccessibleName("Validation: no issues");
      await addState(page, "State", "Idle");
      await expect(validationButton(page)).toHaveAccessibleName("Validation: 2 warnings");
      const list = await openValidation(page);
      await expect(list.getByText(/cannot be reached from the initial state/)).toBeVisible();
      // A row selects its state, and the Selection card keeps one line that opens the list again.
      await list.getByRole("button", { name: /cannot be reached from the initial state/ }).click();
      await expect(list).toBeHidden();
      await expect(selectionCard(page).getByText("Idle", { exact: false }).first()).toBeVisible();
      await selectionCard(page).getByRole("button", { name: /^Show \d issues? in Validation$/ }).click();
      await expect(page.getByRole("group", { name: "Validation issues" })).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("a transition from the initial state clears one warning, a loop on Idle clears the other", async () => {
      await selectNode(page, "Initial state");
      await addTransition(page, /Idle/);
      await expect(validationButton(page)).toHaveAccessibleName("Validation: 1 warning");
      await selectNode(page, "Idle");
      await addTransition(page, /\(itself\)/, "poll");
      await expect(validationButton(page)).toHaveAccessibleName("Validation: no issues");
      await expect(page.getByLabel(/poll, connection from Idle to Idle/)).toBeVisible();
    });

    await test.step("the Selection card's actions are icon buttons: named, one height, and reached by keyboard", async () => {
      await selectNode(page, "Idle");
      const actions = selectionCard(page).getByRole("group", { name: "Actions" });
      for (const name of ["Comment on this box", "Delete state…"]) {
        const button = actions.getByRole("button", { name });
        await expect(button).toBeVisible();
        expect((await button.textContent())?.trim()).toBe("");
      }
      expect((await page.evaluate(buttonHeightGeometry, undefined)).violations).toEqual([]);
      await actions.getByRole("button", { name: "Delete state…" }).focus();
      await expect(page.getByRole("tooltip")).toContainText("Delete state");
    });

    await test.step("a state's values are set in the Selection card, stored when the focus leaves it, and survive a reload", async () => {
      await selectNode(page, "Idle");
      await selectionCard(page).getByLabel("Entry action").fill("stop motor");
      const stored = page.waitForResponse((r) => /\/states\/[^/]+$/.test(r.url()) && r.request().method() === "PUT");
      const saveState = selectionCard(page).getByRole("button", { name: "Save state" });
      await expect(saveState).toHaveText("Save");
      await expect(page.getByRole("button", { name: "Save diagram" })).toHaveText("Save");
      await saveState.click();
      expect((await stored).ok()).toBeTruthy();
      await page.reload();
      await selectNode(page, "Idle");
      await expect(selectionCard(page).getByLabel("Entry action")).toHaveValue("stop motor");
    });

    await test.step("double-clicking a state opens the same fields in a dialog", async () => {
      await page.getByLabel("Idle, node", { exact: true }).dblclick();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByLabel("Entry action")).toHaveValue("stop motor");
      await dialog.getByRole("button", { name: "Close" }).click();
    });

    await test.step("a sound diagram is activated", async () => {
      await chooseRecordAction(page, "State machine diagram", "Activate directly");
      await expect(page.getByText("Active", { exact: true }).first()).toBeVisible();
      await expect(page.getByText(/moved to Active/).first()).toBeVisible();
    });
  });

  test("dropping an Add to diagram item on an empty canvas adds the state there at once, named and selected, without moving the canvas", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdDrop", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Fan ${suffix}`);
    const { diagram } = await createMachine(page.request, base, adminHeaders, elementId, `Fan modes ${suffix}`, [], []);
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    await expect(canvasOf(page)).toBeVisible();
    const top = await settledCanvasTop(page);

    const created = page.waitForResponse((r) => r.url().endsWith("/states") && r.request().method() === "POST");
    // A drag out of a menu is not driven reliably by the browser harness, so the drop is sent as the browser would send it: the
    // item the menu entry puts on the drag, released over the canvas.
    const box = (await canvasOf(page).boundingBox())!;
    const dataTransfer = await page.evaluateHandle(() => {
      const transfer = new DataTransfer();
      transfer.setData("application/x-graph-item", "state-kind:state");
      return transfer;
    });
    await canvasOf(page).dispatchEvent("drop", { dataTransfer, clientX: box.x + 400, clientY: box.y + 160 });
    const response = await created;
    expect(response.ok()).toBeTruthy();
    // The state lands where it was dropped (the box is centred on the drop), not at the next free spot.
    expect((await response.request().postDataJSON()).x).toBeGreaterThan(200);
    await expect(selectionCard(page).getByRole("textbox", { name: /^Name/ })).toHaveValue("State 1");
    await expect(selectionCard(page).getByRole("textbox", { name: /^Name/ })).toBeFocused();
    await expect(page.getByLabel("State 1, node", { exact: true })).toBeVisible();
    // The first state does not move the canvas: nothing above it appears or goes away.
    expect(await canvasTop(page)).toBe(top);
  });

  test("a transition is added at once and empty, its values are set in the Selection card, and a refused add adds nothing", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdTrn", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Charger ${suffix}`);
    const { diagram } = await createMachine(page.request, base, adminHeaders, elementId, `Charger modes ${suffix}`, [
      { name: "Start", kind: "initial", x: 40, y: 60 }, { name: "Branch", kind: "choice", x: 240, y: 60 },
      { name: "Idle", x: 420, y: 40 },
    ], [["Start", "Branch"]]);
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);

    await test.step("a line leaving a choice is added at once and its guard takes the focus", async () => {
      await selectNode(page, "Choice");
      const created = page.waitForResponse((r) => r.url().endsWith("/transitions") && r.request().method() === "POST");
      await selectionCard(page).getByLabel("Add transition to").selectOption({ label: await optionLabel(page, /Idle/) });
      const response = await created;
      expect(response.ok()).toBeTruthy();
      expect(await response.request().postDataJSON()).toMatchObject({ event: "", guard: "", action: "" });
      await expect(page.getByRole("dialog")).toHaveCount(0);
      const details = selectionCard(page).getByRole("group", { name: "Transition details" });
      await expect(details.getByLabel("Condition (guard)", { exact: true })).toBeFocused();
    });

    await test.step("the condition is stored when the focus leaves the card and survives a reload", async () => {
      const details = selectionCard(page).getByRole("group", { name: "Transition details" });
      await details.getByLabel("Condition (guard)", { exact: true }).fill("battery low");
      const stored = page.waitForResponse((r) => /\/transitions\/[^/]+$/.test(r.url()) && r.request().method() === "PUT");
      await page.getByRole("heading", { level: 1 }).click();
      expect((await stored).ok()).toBeTruthy();
      await page.reload();
      await expect(page.getByLabel(/\[battery low\], connection from Choice to Idle/)).toBeVisible();
    });

    await test.step("double-clicking a line opens its fields in a dialog", async () => {
      const line = page.getByLabel("Connection from Initial state to Choice", { exact: true });
      await line.click();
      // The selected line shows a dot over its middle (to add a vertex); a double-click on it opens the line too.
      await page.locator(".graph-segment-handle").first().dblclick();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByRole("heading", { name: "Edit transition" })).toBeVisible();
      await expect(dialog.getByLabel("Event", { exact: true })).toHaveValue("");
      await dialog.getByRole("button", { name: "Close" }).click();
      await expect(dialog).toHaveCount(0);
    });

    await test.step("a refused add shows an error and adds nothing", async () => {
      await selectNode(page, "Idle");
      await page.route(/\/transitions$/, (route) => (route.request().method() === "POST" ? route.fulfill({ status: 400, json: { detail: "Refused." } }) : route.continue()));
      await selectionCard(page).getByLabel("Add transition to").selectOption({ label: await optionLabel(page, /\(itself\)/) });
      await expect(page.getByText("Could not add the transition.")).toBeVisible();
      await expect(selectionCard(page).getByRole("group", { name: "Transition details" })).toHaveCount(0);
      await page.unroute(/\/transitions$/);
    });
  });

  test("a symbol label is set on a choice in the Selection card, drawn inside a larger diamond, kept by a reload and not offered for an ordinary state", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdLabel", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Drone ${suffix}`);
    const { diagram } = await createMachine(page.request, base, adminHeaders, elementId, `Drone modes ${suffix}`, [
      { name: "Start", kind: "initial", x: 40, y: 60 }, { name: "Branch", kind: "choice", x: 240, y: 60 }, { name: "Idle", x: 420, y: 40 },
    ], [["Start", "Branch"]]);
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    const choice = page.getByLabel("Choice, node", { exact: true });
    await expect(choice).toBeVisible();
    const plain = (await choice.boundingBox())!;

    await test.step("the Selection card of a choice offers a Symbol label, and an ordinary state does not", async () => {
      await selectNode(page, "Idle");
      await expect(selectionCard(page).getByLabel("Symbol label")).toHaveCount(0);
      await selectNode(page, "Choice");
      await expect(selectionCard(page).getByLabel("Symbol label")).toBeVisible();
    });

    await test.step("the label is stored when the focus leaves the card and the diamond grows to hold it", async () => {
      await selectionCard(page).getByLabel("Symbol label").fill("Battery low?");
      const stored = page.waitForResponse((r) => /\/states\/[^/]+$/.test(r.url()) && r.request().method() === "PUT");
      await page.getByRole("heading", { level: 1 }).click();
      const response = await stored;
      expect(response.ok()).toBeTruthy();
      expect(await response.request().postDataJSON()).toMatchObject({ label: "Battery low?" });
      await expect(choice.getByText("Battery low?")).toBeVisible();
      expect((await choice.boundingBox())!.width).toBeGreaterThan(plain.width * 2);
    });

    await test.step("a reload keeps the label and the Outline lists it", async () => {
      await page.reload();
      await expect(page.getByLabel("Choice, node", { exact: true }).getByText("Battery low?")).toBeVisible();
      await page.getByRole("tab", { name: "Outline" }).click();
      await expect(page.getByText("Symbol label: Battery low?")).toBeVisible();
    });
  });

  test("a long symbol label is kept whole, never split inside a word, in a symbol that grows to hold it, on the screen and in the server drawing", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdLong", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Tank ${suffix}`);
    const { diagram } = await createMachine(page.request, base, adminHeaders, elementId, `Tank modes ${suffix}`, [
      { name: "Start", kind: "initial", x: 40, y: 60 }, { name: "Branch", kind: "choice", x: 240, y: 60 },
    ], [["Start", "Branch"]]);
    const label = "Is the tank level above the high-level alarm threshold for more than ten seconds";
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    const choice = page.getByLabel("Choice, node", { exact: true });
    await expect(choice).toBeVisible();
    await selectNode(page, "Choice");

    await test.step("a label of more than forty characters can be typed and is stored", async () => {
      await selectionCard(page).getByLabel("Symbol label").fill(label);
      const stored = page.waitForResponse((r) => /\/states\/[^/]+$/.test(r.url()) && r.request().method() === "PUT");
      await page.getByRole("heading", { level: 1 }).click();
      const response = await stored;
      expect(response.ok()).toBeTruthy();
      expect(await response.request().postDataJSON()).toMatchObject({ label });
    });

    const drawnLines = async () => (await choice.locator(".graph-node-marker-text").innerText()).split("\n");
    await test.step("the screen draws every word whole and the symbol is larger than a one-line label needs", async () => {
      const lines = await drawnLines();
      expect(lines.length).toBeGreaterThan(1);
      expect(lines.join(" ").replace(/- /g, "-")).toBe(label);
      expect((await choice.boundingBox())!.width).toBeGreaterThan(120);
    });

    await test.step("a reload keeps the label and the server's drawing breaks it at the same words", async () => {
      await page.reload();
      const screen = await drawnLines();
      expect(screen.join(" ")).toContain("tank level");
      const svg = await (await page.request.get(`${base}/state-machine-diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
      const drawn = [...svg.matchAll(/<text[^>]*fill="#1E293B"[^>]*>([^<]+)<\/text>/g)].map((m) => m[1]).filter((t) => label.includes(t.trim().replace(/-$/, "")));
      expect(drawn).toEqual(screen);
    });
  });

  test("text inside an initial, final or choice symbol keeps its padding from the symbol's inner edge and is centred, for a short and a long label", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdPad", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Valve ${suffix}`);
    const { diagram } = await createMachine(page.request, base, adminHeaders, elementId, `Valve modes ${suffix}`, [
      { name: "Begin", kind: "initial", x: 40, y: 200, label: "Power on and warm up the heater" },
      { name: "Done", kind: "final", x: 340, y: 200, label: "Shut down complete" },
      { name: "Branch", kind: "choice", x: 700, y: 200, label: "Is the tank level above the high-level alarm threshold?" },
      { name: "Idle", x: 40, y: 20 },
    ], []);
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    const padding = 4; // LABEL_PADDING, in canvas units
    const kinds = [
      { node: "Initial state", shape: "circle" }, { node: "Final state", shape: "disc" }, { node: "Choice", shape: "diamond" },
    ] as const;
    for (const { node, shape } of kinds) {
      await test.step(`${node}: the text is centred and at least ${padding} units inside the ${shape}'s inner edge`, async () => {
        const symbol = page.getByLabel(`${node}, node`, { exact: true });
        await expect(symbol.locator(".graph-node-marker-text")).toBeVisible();
        const measured = await symbol.evaluate((el) => {
          const viewport = el.closest(".react-flow__viewport") as HTMLElement;
          const scale = new DOMMatrix(getComputedStyle(viewport).transform).a;
          const image = el.querySelector(".graph-node-marker-image")!.getBoundingClientRect();
          const text = el.querySelector(".graph-node-marker-text")!.getBoundingClientRect();
          return {
            scale, size: image.width / scale, textWidth: text.width / scale, textHeight: text.height / scale,
            offsetX: (text.x + text.width / 2 - (image.x + image.width / 2)) / scale,
            offsetY: (text.y + text.height / 2 - (image.y + image.height / 2)) / scale,
          };
        });
        const a = measured.textWidth / 2;
        const b = measured.textHeight / 2;
        const half = Math.round(measured.size / 2);
        const clearance = shape === "diamond"
          ? ((half - 2) - (a + b)) / Math.SQRT2
          : (shape === "circle" ? half - 1 : Math.floor((26 * Math.round(measured.size) + 36) / 72)) - Math.hypot(a, b);
        expect(Math.abs(measured.offsetX)).toBeLessThan(1.5);
        expect(Math.abs(measured.offsetY)).toBeLessThan(1.5);
        // The browser's real glyphs are no wider than the layout's table, so the clearance is at least the padding (0.5 for rounding).
        expect(clearance).toBeGreaterThanOrEqual(padding - 0.5);
        // The text sits inside the symbol, not past it.
        expect(measured.size).toBeGreaterThan(measured.textHeight);
      });
    }
  });

  test("a label can sit inside, left, right, above or below its symbol: the symbol keeps its plain size, the text sits beside it, a line avoids that side, and a reload and the server's drawing agree", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdPos", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Boiler ${suffix}`);
    const { diagram, ids } = await createMachine(page.request, base, adminHeaders, elementId, `Boiler modes ${suffix}`, [
      { name: "Start", kind: "initial", x: 40, y: 60 }, { name: "Branch", kind: "choice", x: 240, y: 60, label: "Pressure high?" },
    ], [["Start", "Branch"]]);
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    const choice = page.getByLabel("Choice, node", { exact: true });
    await expect(choice).toBeVisible();
    const inside = (await choice.boundingBox())!;
    expect(inside.width).toBeGreaterThan(60); // the label inside grew the diamond

    const setPosition = async (position: "Inside" | "Left" | "Right" | "Above" | "Below") => {
      await selectNode(page, "Choice");
      await selectionCard(page).getByLabel("Label position").selectOption({ label: position });
      const stored = page.waitForResponse((r) => /\/states\/[^/]+$/.test(r.url()) && r.request().method() === "PUT");
      await selectionCard(page).getByRole("button", { name: "Save state" }).click();
      const response = await stored;
      expect(response.ok()).toBeTruthy();
      expect(await response.request().postDataJSON()).toMatchObject({ label_position: position.toLowerCase() });
    };
    /** The symbol's and the text's rectangles in canvas units, relative to the symbol's top left corner. */
    const placed = async () => choice.evaluate((el) => {
      const scale = new DOMMatrix(getComputedStyle(el.closest(".react-flow__viewport") as HTMLElement).transform).a;
      const box = el.getBoundingClientRect();
      const text = el.querySelector(".graph-node-marker-text-block")?.getBoundingClientRect();
      return {
        width: box.width / scale, height: box.height / scale,
        text: text ? { left: (text.left - box.left) / scale, top: (text.top - box.top) / scale, right: (text.right - box.left) / scale, bottom: (text.bottom - box.top) / scale } : null,
      };
    });
    /** Where the line from Start ends, in canvas units (the end of its path). */
    const lineEnd = async () => page.locator(".react-flow__edge-path").first().evaluate((el) => {
      const numbers = (el.getAttribute("d") ?? "").match(/-?\d+(\.\d+)?/g)!.map(Number);
      return { x: numbers[numbers.length - 2], y: numbers[numbers.length - 1] };
    });

    await test.step("Right: the diamond returns to its plain 20 unit size and the text sits 4 units to its right, centred on it", async () => {
      await setPosition("Right");
      await expect(choice.locator(".graph-node-marker-text-block")).toHaveText("Pressure high?");
      await expect.poll(async () => (await placed()).text!.left).toBeCloseTo(24, 0);
      const right = await placed();
      expect(right.width).toBeCloseTo(20, 0);
      // The label beside the symbol does not zoom the drawing out: a 20 unit symbol is drawn at about 20 pixels.
      expect((await choice.boundingBox())!.width).toBeGreaterThan(16);
      expect((right.text!.top + right.text!.bottom) / 2).toBeCloseTo(right.height / 2, 0);
      expect((await choice.boundingBox())!.width).toBeLessThan(inside.width / 2);
    });

    await test.step("a line left to choose its own end still meets the symbol on its left, at its edge", async () => {
      const end = await lineEnd();
      expect(Math.abs(end.x - 240)).toBeLessThan(4);
      expect(Math.abs(end.y - 70)).toBeLessThan(4);
    });

    await test.step("Left: the text sits 4 units to the left and the line now meets another side, never running through the text", async () => {
      await setPosition("Left");
      await expect.poll(async () => (await placed()).text!.right).toBeCloseTo(-4, 0);
      await expect.poll(async () => Math.abs((await lineEnd()).x - 240)).toBeGreaterThan(4); // not the left side where the text is
    });

    await test.step("Above and Below: the text is centred over or under the symbol, 4 units from it", async () => {
      await setPosition("Above");
      await expect.poll(async () => (await placed()).text!.bottom).toBeCloseTo(-4, 0);
      const above = await placed();
      expect((above.text!.left + above.text!.right) / 2).toBeCloseTo(above.width / 2, 0);
      await setPosition("Below");
      await expect.poll(async () => { const now = await placed(); return now.text!.top - now.height; }).toBeCloseTo(4, 0);
      const below = await placed();
      expect((below.text!.left + below.text!.right) / 2).toBeCloseTo(below.width / 2, 0);
    });

    await test.step("a reload keeps the position, the Outline lists it and the server draws the symbol at its stored box with the text outside", async () => {
      await page.reload();
      await expect(page.getByLabel("Choice, node", { exact: true }).locator(".graph-node-marker-text-block")).toHaveText("Pressure high?");
      await page.getByRole("tab", { name: "Outline" }).click();
      await expect(page.getByText("Label position: Below")).toBeVisible();
      const svg = await (await page.request.get(`${base}/state-machine-diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
      // The 36 unit diamond is drawn into its stored 20 unit box (a scale of 20/36), at the stored corner, not grown for the text.
      expect(svg).toContain("translate(240.0 60.0) scale(0.5556 0.5556)");
      const drawn = [...svg.matchAll(/<text[^>]*text-anchor="middle"[^>]*fill="#1E293B"[^>]*>([^<]+)<\/text>/g)].map((m) => m[1]);
      expect(drawn).toContain("Pressure high?");
    });

    await test.step("Inside puts the text back in a larger symbol", async () => {
      await page.getByRole("tab", { name: "Drawing" }).click();
      await setPosition("Inside");
      await expect(choice.locator(".graph-node-marker-text-block")).toHaveCount(0);
      expect((await choice.boundingBox())!.width).toBeGreaterThan(60);
    });
    expect(ids.Branch).toBeTruthy();
  });

  test("a loop on a choice leaves its top vertex and returns to its right vertex, on the diamond itself, on the screen and in the server drawing", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdLoop", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Gauge ${suffix}`);
    const { diagram } = await createMachine(page.request, base, adminHeaders, elementId, `Gauge modes ${suffix}`, [
      { name: "Start", kind: "initial", x: 40, y: 60 }, { name: "Branch", kind: "choice", x: 300, y: 100 },
    ], [["Start", "Branch"], ["Branch", "Branch", "retry"]]);
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    await expect(page.getByLabel("Choice, node", { exact: true })).toBeVisible();
    // The choice is stored as a 20 by 20 box at (300, 100): its top vertex is (310, 100) and its right vertex (320, 110).
    const numbers = (d: string) => (d.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);
    await expect.poll(async () => {
      const paths = await page.locator(".react-flow__edge-path").evaluateAll((els) => els.map((el) => el.getAttribute("d") ?? ""));
      const loop = paths.map(numbers).find((n) => n.length === 8 && n[0] === 310 && n[1] === 100);
      return loop ? [loop[6], loop[7]] : null;
    }).toEqual([320, 110]);
    const svg = await (await page.request.get(`${base}/state-machine-diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
    expect(svg).toContain('d="M 310 100 C ');
    expect(svg).toMatch(/d="M 310 100 C [^"]* 320 110"/);
  });

  test("moving a symbol with a label inside it leaves it where it is dropped, not shifted by the growth the label gave it", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdDrop", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Press ${suffix}`);
    const { diagram, ids } = await createMachine(page.request, base, adminHeaders, elementId, `Press modes ${suffix}`, [
      { name: "Branch", kind: "choice", x: 300, y: 200, label: "Is the pressure above the safe limit for the vessel?" },
    ], []);
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    await expect(page.getByLabel("Choice, node", { exact: true })).toBeVisible();
    const stored = async () => {
      const model = await (await page.request.get(`${base}/state-machine-diagrams/${diagram.id}/model`, { headers: adminHeaders })).json();
      const state = model.states.find((s: { id: string }) => s.id === ids.Branch);
      return { x: state.x as number, y: state.y as number };
    };
    const before = await stored();
    await selectNode(page, "Choice");
    await page.keyboard.press("ArrowRight");
    await page.getByRole("button", { name: "Save diagram", exact: true }).click();
    await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeDisabled();
    await expect.poll(async () => (await stored()).x).not.toBe(before.x);
    const after = await stored();
    // A key press moves the drawing by a few units; the symbol is about 130 units wide, so a jump by half its growth would be over 50.
    expect(Math.abs(after.x - before.x)).toBeLessThanOrEqual(20);
    expect(Math.abs(after.y - before.y)).toBeLessThanOrEqual(20);
  });

  test("a state is nested in another, the drawing is stored by Save and survives a reload, and a state is deleted with what goes with it", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdDraw", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Pump ${suffix}`);
    const { diagram, ids } = await createMachine(page.request, base, adminHeaders, elementId, `Pump modes ${suffix}`, [
      { name: "Start", kind: "initial", x: 40, y: 60 }, { name: "Idle", x: 140, y: 40 }, { name: "Active", x: 420, y: 40 },
    ], [["Start", "Idle"], ["Idle", "Active", "go"]]);
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    await expect(page.getByLabel("Idle, node", { exact: true })).toBeVisible();

    await test.step("moving a state is an unsaved drawing edit; Undo returns to the saved drawing", async () => {
      await selectNode(page, "Idle");
      await page.keyboard.press("ArrowRight");
      await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeEnabled();
      await page.getByRole("button", { name: "Undo" }).click();
      await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeDisabled();
    });

    await test.step("choosing Inside nests the state; Save stores the nesting and a reload keeps it", async () => {
      await selectNode(page, "Idle");
      await selectionCard(page).getByLabel("Inside").selectOption({ label: await insideLabel(page, "Active") });
      await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeEnabled();
      const saved = page.waitForResponse((r) => r.url().endsWith("/layout") && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save diagram", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeDisabled();
      await page.reload();
      await expect(page.getByLabel("Idle, node", { exact: true })).toBeVisible();
      const model = await (await page.request.get(`${base}/state-machine-diagrams/${diagram.id}/model`, { headers: adminHeaders })).json();
      expect(model.states.find((s: { id: string }) => s.id === ids.Idle).parent_state_id).toBe(ids.Active);
      await page.getByRole("tab", { name: "Outline" }).click();
      const active = page.getByRole("button", { name: /STE-\d+ Active$/ }).locator("xpath=ancestor::li[1]");
      await expect(active.getByRole("button", { name: /STE-\d+ Idle$/ })).toBeVisible();
      await page.getByRole("tab", { name: "Drawing" }).click();
    });

    await test.step("deleting a state names its transitions and needs its code", async () => {
      await selectNode(page, "Active");
      await selectionCard(page).getByRole("button", { name: "Delete state…" }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByText(/with its 1 transition and 0 links/)).toBeVisible();
      // Active holds Idle, so the server refuses until Idle is moved out; the refusal is shown, nothing is deleted.
      const code = (await selectionCard(page).locator(".detail-card__title").textContent())!.match(/STE-\d+/)![0];
      await dialog.getByRole("textbox").fill(code);
      await dialog.getByRole("button", { name: "Delete", exact: true }).click();
      await expect(page.getByRole("alert").filter({ hasText: /contains other states/ })).toBeVisible();
      await expect(page.getByLabel("Active, node", { exact: true })).toBeVisible();
    });
  });

  test("an architect exports the stored diagram as SVG, PNG and Mermaid text, and a rename reaches the next export", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdExport", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Valve ${suffix}`);
    const { diagram, ids } = await createMachine(page.request, base, adminHeaders, elementId, `Valve modes ${suffix}`, [
      { name: "Start", kind: "initial", x: 40, y: 60 }, { name: "Closed", x: 140, y: 40 }, { name: "Open", x: 420, y: 40 },
    ], [["Start", "Closed"], ["Closed", "Open", "open_cmd"]]);
    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    await expect(page.getByLabel("Closed, node", { exact: true })).toBeVisible();

    /** Chooses an Export item and returns the downloaded file's name and text. */
    async function download(item: string): Promise<{ name: string; text: string }> {
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const saved = page.waitForEvent("download");
      await clickMenuRow(page, item);
      const file = await saved;
      const path = await file.path();
      const { readFile } = await import("node:fs/promises");
      return { name: file.suggestedFilename(), text: path ? await readFile(path, "utf8") : "" };
    }

    await test.step("the SVG is the server's drawing of the states and transitions", async () => {
      const svg = await download("SVG image");
      expect(svg.name).toMatch(/^SMD-\d+-valve-modes-.*\.svg$/);
      expect(svg.text).toContain("<svg");
      expect(svg.text).toContain(">Closed<");
      expect(svg.text).toContain(">open_cmd<");
    });

    await test.step("the Mermaid text is a stateDiagram-v2 of the same model", async () => {
      const mermaid = await download("Download Mermaid text");
      expect(mermaid.name).toMatch(/\.mmd$/);
      expect(mermaid.text).toContain("stateDiagram-v2");
      expect(mermaid.text).toMatch(/state "STE-\d+ Closed" as s\d+/);
      expect(mermaid.text).toContain("[*] --> ");
      expect(mermaid.text).toMatch(/s\d+ --> s\d+ : open_cmd/);
    });

    await test.step("a PNG image is downloaded", async () => {
      expect((await download("PNG image")).name).toMatch(/\.png$/);
    });

    await test.step("renaming a state reaches the next export", async () => {
      const renamed = await page.request.put(`${base}/states/${ids.Closed}`, {
        headers: adminHeaders,
        data: { version: (await (await page.request.get(`${base}/state-machine-diagrams/${diagram.id}`, { headers: adminHeaders })).json()).version, name: "Shut" },
      });
      expect(renamed.ok(), await renamed.text()).toBeTruthy();
      await page.reload();
      await expect(page.getByLabel("Shut, node", { exact: true })).toBeVisible();
      const svg = await download("SVG image");
      expect(svg.text).toContain(">Shut<");
      expect(svg.text).not.toContain(">Closed<");
    });
  });

  test("a reviewer comments on a state and a second person sees it on the drawing", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "ArchSmdCmt", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Valve ${suffix}`);
    const { diagram } = await createMachine(page.request, base, adminHeaders, elementId, `Valve modes ${suffix}`, [
      { name: "Start", kind: "initial", x: 40, y: 60 }, { name: "Open", x: 140, y: 40 },
    ], [["Start", "Open"]]);
    const colleagueEmail = `e2e-smd-colleague-${suffix}@example.com`;
    const user = await page.request.post(`${API}/api/v1/orgs/${org.id}/users`, {
      headers: adminHeaders, data: { email: colleagueEmail, display_name: "Casey Colleague", password: PASSWORD, role: "member" },
    });
    expect(user.ok(), await user.text()).toBeTruthy();
    const added = await page.request.post(`${API}/api/v1/projects/${project.id}/roles`, {
      headers: adminHeaders, data: { user_id: (await user.json()).user_id, role: "member" },
    });
    expect(added.status(), await added.text()).toBe(204);

    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}`);
    const open = page.getByLabel("Open, node", { exact: true });
    await expect(open).toBeVisible();

    await test.step("comment mode pins a thread on a state and never makes the drawing unsaved", async () => {
      await page.getByRole("button", { name: "Comment", exact: true }).click();
      const stored = page.waitForResponse((r) => r.url().endsWith("/comments") && r.request().method() === "POST");
      await open.click();
      const composer = page.getByRole("dialog", { name: "New comment" });
      await composer.getByRole("textbox", { name: "New comment" }).fill("What closes the valve?");
      await composer.getByRole("button", { name: "Comment", exact: true }).click();
      expect((await stored).ok()).toBeTruthy();
      await expect(page.getByRole("button", { name: /Comment thread by .*, 1 comment/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "Save diagram", exact: true })).toBeDisabled();
    });

    await test.step("a second person opens the thread from the Comments tab", async () => {
      await logout(page);
      await loginAs(page, colleagueEmail);
      await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}?tab=comments`);
      await expect(page.getByText("What closes the valve?")).toBeVisible();
      await expect(page.getByText(/^On .*STE-\d+ Open$/)).toBeVisible();
    });
  });

  test("the Diagrams tab lists both types, filters by Type, sorts on a header click and lists the states; the element's page lists its diagrams", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchSmdList", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, base, adminHeaders, `Router ${suffix}`);
    const block = await page.request.post(`${base}/diagrams`, { headers: adminHeaders, data: { name: `Overview ${suffix}`, activate: true } });
    expect(block.ok(), await block.text()).toBeTruthy();
    const { diagram } = await createMachine(page.request, base, adminHeaders, elementId, `Router modes ${suffix}`, [
      { name: "Start", kind: "initial", x: 40, y: 60 }, { name: "Routing", x: 140, y: 40 },
    ], [["Start", "Routing"]]);

    await page.goto(`/projects/${project.id}/modules/architecture?tab=diagrams`);
    const table = page.getByRole("table", { name: "Diagrams" });
    await test.step("both types are in one list with a Type column", async () => {
      await expect(table.getByText("State machine diagram", { exact: true })).toBeVisible();
      await expect(table.getByText("Block diagram", { exact: true })).toBeVisible();
      await expect(table.getByText("2 states")).toBeVisible();
    });

    await test.step("the Type filter keeps one type", async () => {
      await page.getByRole("combobox", { name: "Type" }).selectOption("state_machine");
      await expect(table.getByText("Block diagram", { exact: true })).toHaveCount(0);
      await expect(page).toHaveURL(/type=state_machine/);
      await page.getByRole("combobox", { name: "Type" }).selectOption("");
      await expect(table.getByText("Block diagram", { exact: true })).toBeVisible();
    });

    await test.step("a header click sorts the merged list with the sort in the address", async () => {
      await table.getByRole("button", { name: "Type" }).click();
      await expect(page).toHaveURL(/sort=type/);
      await expect(table.getByRole("columnheader", { name: "Type" })).toHaveAttribute("aria-sort", "ascending");
      const types = await table.locator("tbody tr td:nth-child(4)").allTextContents();
      expect(types.map((t) => t.trim())).toEqual([...types.map((t) => t.trim())].sort());
    });

    await test.step("the State list lists every state and opens its diagram with the state selected", async () => {
      await page.getByRole("tab", { name: "State list" }).click();
      const states = page.getByRole("table", { name: "States" });
      await expect(states.getByText("Routing", { exact: true })).toBeVisible();
      await states.getByRole("link", { name: /STE-\d+$/ }).last().click();
      await expect(page).toHaveURL(new RegExp(`/state-machine-diagrams/${diagram.id}\\?state=`));
      await expect(selectionCard(page).locator(".detail-card__title")).toBeVisible();
    });

    await test.step("the element's Diagrams card lists its state machine diagrams", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/elements/${elementId}`);
      const card = page.getByRole("region", { name: "Diagrams" });
      await expect(card.getByRole("link", { name: new RegExp(`Router modes ${suffix}`) })).toBeVisible();
      await expect(card.getByText(/State machine diagram · Describes this element/)).toBeVisible();
    });
  });
});

/** The text of the "Inside" option for the state named `name`. */
async function insideLabel(page: Page, name: string): Promise<string> {
  const labels = await selectionCard(page).getByLabel("Inside").locator("option").allTextContents();
  const found = labels.find((label) => label.endsWith(` ${name}`));
  if (!found) throw new Error(`No "Inside" option for ${name}: ${labels.join(", ")}`);
  return found;
}
