import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { buttonHeightGeometry } from "../../../../../frontend/src/testing/buttonHeights";
import { installCleanupHook, loginAs, logout, PASSWORD } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

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

/** The Findings card of the editor. */
const findingsCard = (page: Page) => page.getByRole("region", { name: "Findings" });

/** Adds a state (or marker) from the Add to diagram menu and fills its form; `name` is left as is for a marker. */
async function addState(page: Page, item: "State" | "Initial state" | "Final state" | "Choice", name?: string) {
  await page.getByRole("button", { name: "Add to diagram" }).click();
  await page.getByRole("menuitem", { name: item, exact: true }).click();
  const dialog = page.getByRole("dialog");
  if (name !== undefined) await dialog.getByLabel("Name", { exact: true }).fill(name);
  const stored = page.waitForResponse((r) => r.url().endsWith("/states") && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  expect((await stored).ok()).toBeTruthy();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

/** Adds a transition from the selected state to another (or itself, named "itself") through the Selection card. */
async function addTransition(page: Page, targetLabel: RegExp, event = "") {
  await selectionCard(page).getByLabel("Add transition to").selectOption({ label: await optionLabel(page, targetLabel) });
  const dialog = page.getByRole("dialog");
  if (event) await dialog.getByLabel("Event", { exact: true }).fill(event);
  const stored = page.waitForResponse((r) => r.url().endsWith("/transitions") && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  expect((await stored).ok()).toBeTruthy();
  await expect(page.getByRole("dialog")).toHaveCount(0);
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
  states: { name: string; kind?: string; x: number; y: number }[], transitions: [string, string, string?][],
) {
  const created = await request.post(`${base}/state-machine-diagrams`, { headers, data: { name, element_id: elementId } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const diagram = await created.json();
  let version = diagram.version;
  const ids: Record<string, string> = {};
  for (const state of states) {
    const added = await request.post(`${base}/state-machine-diagrams/${diagram.id}/states`, {
      headers, data: { version, name: state.name, kind: state.kind ?? "state", x: state.x, y: state.y, width: state.kind && state.kind !== "state" ? 20 : 160, height: state.kind && state.kind !== "state" ? 20 : 64 },
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
      await expect(findingsCard(page).getByText("1 error")).toBeVisible();
      await expect(findingsCard(page).getByText(/no initial state at the top level/)).toBeVisible();
      await page.getByRole("button", { name: "Change status", exact: true }).click();
      await page.getByRole("menuitem", { name: "Move from Draft to Active" }).click();
      await expect(page.getByRole("alert").filter({ hasText: /cannot be activated until its errors are resolved/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "Reload state machine diagram" })).toHaveCount(0);
    });

    await test.step("an initial state clears the error; a state nobody can reach or leave is a warning", async () => {
      await addState(page, "Initial state");
      await expect(findingsCard(page).getByText("0 errors")).toBeVisible();
      await addState(page, "State", "Idle");
      await expect(findingsCard(page).getByText("2 warnings")).toBeVisible();
      await expect(findingsCard(page).getByText(/cannot be reached from the initial state/)).toBeVisible();
    });

    await test.step("a transition from the initial state clears one warning, a loop on Idle clears the other", async () => {
      await selectNode(page, "Initial state");
      await addTransition(page, /Idle/);
      await expect(findingsCard(page).getByText("1 warning")).toBeVisible();
      await selectNode(page, "Idle");
      await addTransition(page, /\(itself\)/, "poll");
      await expect(findingsCard(page).getByText("0 warnings")).toBeVisible();
      await expect(page.getByLabel(/poll, connection from Idle to Idle/)).toBeVisible();
    });

    await test.step("the Selection card's actions are icon buttons: named, one height, and reached by keyboard", async () => {
      await selectNode(page, "Idle");
      const actions = selectionCard(page).getByRole("group", { name: "Actions" });
      for (const name of ["Edit state", "Delete state…"]) {
        const button = actions.getByRole("button", { name });
        await expect(button).toBeVisible();
        expect((await button.textContent())?.trim()).toBe("");
      }
      expect((await page.evaluate(buttonHeightGeometry, undefined)).violations).toEqual([]);
      await actions.getByRole("button", { name: "Edit state" }).focus();
      await expect(page.getByRole("tooltip")).toContainText("Edit state");
    });

    await test.step("a sound diagram is activated", async () => {
      await page.getByRole("button", { name: "Change status", exact: true }).click();
      await page.getByRole("menuitem", { name: "Move from Draft to Active" }).click();
      await expect(page.getByText("Active", { exact: true }).first()).toBeVisible();
      await expect(page.getByText(/moved to Active/).first()).toBeVisible();
    });
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
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
      await page.getByRole("button", { name: "Undo" }).click();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    });

    await test.step("choosing Inside nests the state; Save stores the nesting and a reload keeps it", async () => {
      await selectNode(page, "Idle");
      await selectionCard(page).getByLabel("Inside").selectOption({ label: await insideLabel(page, "Active") });
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
      const saved = page.waitForResponse((r) => r.url().endsWith("/layout") && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
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
      const code = (await selectionCard(page).locator("strong").first().textContent())!.match(/STE-\d+/)![0];
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
      await page.getByRole("menuitem", { name: item, exact: true }).click();
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
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
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
      await expect(selectionCard(page).locator("strong").first()).toBeVisible();
    });

    await test.step("the element's page lists its state machine diagrams", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/elements/${elementId}`);
      const card = page.getByRole("region", { name: "State machine diagrams" });
      await expect(card.getByRole("link", { name: new RegExp(`Router modes ${suffix}`) })).toBeVisible();
      await expect(card.getByText("2 states")).toBeVisible();
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
