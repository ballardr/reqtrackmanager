import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { buttonHeightGeometry } from "../../../../../frontend/src/testing/buttonHeights";
import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** Creates an active element through the API and returns its id; the diagram is the subject here, not the element form. */
async function createElement(
  request: APIRequestContext, headers: Record<string, string>, projectId: string, name: string, parentId?: string,
): Promise<string> {
  const base = `${API}/api/v1/projects/${projectId}/modules/architecture`;
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true, parent_id: parentId } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/** Selects a node by keyboard (focus, Enter), the way the canvas documents. */
async function selectNode(page: Page, name: string) {
  const node = page.getByLabel(`${name}, node`, { exact: true });
  await node.focus();
  await page.keyboard.press("Enter");
  return node;
}

/**
 * Job to be done: an architect draws how a product's parts connect. A diagram is a view over the model: placing an element
 * shows its real name and connections, removing a box never deletes the element, edits are stored together by Save, and a
 * save made from a stale copy is refused with an offer to reload.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture switched on; elements and the connection are
 * created through the API as setup, everything about the diagram through the UI.
 */
test.describe("System Architecture: diagram editor", () => {
  test("an architect places elements, sees their connection, adds one from the Add menu and removes a box without deleting it", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchDiagram", true, "System Architecture");
    const gateway = `Gateway ${suffix}`;
    const orders = `Orders ${suffix}`;
    const queue = `Queue ${suffix}`;
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gatewayId = await createElement(page.request, adminHeaders, project.id, gateway);
    const ordersId = await createElement(page.request, adminHeaders, project.id, orders);
    const connectionTypes = await (await page.request.get(`${base}/connection-types`, { headers: adminHeaders })).json();
    const connection = await page.request.post(`${base}/connections`, {
      headers: adminHeaders,
      data: { connection_type_id: connectionTypes[0].id, source_element_id: gatewayId, target_element_id: ordersId, activate: true },
    });
    expect(connection.ok(), await connection.text()).toBeTruthy();

    await test.step("create an active diagram from the Diagrams list and land in the editor", async () => {
      await page.goto(`/projects/${project.id}`);
      await page.getByRole("link", { name: "System Architecture", exact: true }).click();
      await page.getByRole("tab", { name: "Diagrams" }).click();
      await expect(page.getByText("No diagrams drawn for this project yet.")).toBeVisible();
      await page.getByRole("button", { name: "New diagram" }).click();
      const dialog = page.getByRole("dialog", { name: "New diagram" });
      await dialog.getByLabel("Name", { exact: true }).fill(`Overview ${suffix}`);
      await dialog.getByRole("button", { name: "Save and activate" }).click();
      await expect(page).toHaveURL(new RegExp(`/modules/architecture/diagrams/[0-9a-f-]+$`));
      await expect(page.getByRole("heading", { name: new RegExp(`Overview ${suffix}`) })).toBeVisible();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    });

    await test.step("add existing elements, see their connection before saving, then save", async () => {
      await page.getByRole("button", { name: "Add to diagram" }).click();
      await page.getByRole("menuitem", { name: "Add existing elements" }).click();
      const dialog = page.getByRole("dialog", { name: "Add existing elements" });
      await dialog.getByRole("checkbox", { name: `Add ${gateway}` }).check();
      await dialog.getByRole("checkbox", { name: `Add ${orders}` }).check();
      await dialog.getByRole("button", { name: "Add selected (2)" }).click();
      await expect(page.getByLabel(`${gateway}, node`, { exact: true })).toBeVisible();
      await expect(page.getByText(/Unsaved changes/)).toBeVisible();
      // The line is drawn from the model data in the browser, so it is there before anything is stored. (A straight line has
      // no area, so it is attached rather than "visible".)
      await expect(page.getByLabel(`Connection from ${gateway} to ${orders}`, { exact: true })).toBeAttached();
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.").last()).toBeVisible();
      await expect(page.getByLabel(`Connection from ${gateway} to ${orders}`, { exact: true })).toBeAttached();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    });

    await test.step("create an element from the Add menu and place it", async () => {
      await page.getByRole("button", { name: "Add to diagram" }).click();
      await page.getByRole("menuitem", { name: "Component", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "New Component" });
      await dialog.getByLabel("Name", { exact: true }).fill(queue);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByLabel(`${queue}, node`, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.").last()).toBeVisible();
    });

    await test.step("the Configuration tab and the settings gear keep unsaved edits; the gear's setting is stored at once", async () => {
      await selectNode(page, queue);
      await page.keyboard.press("ArrowRight");
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
      await page.getByRole("tab", { name: "Configuration" }).click();
      await expect(page).toHaveURL(/tab=configuration/);
      await expect(page.getByRole("toolbar", { name: "Diagram editing" })).toHaveCount(0);
      await page.getByRole("tab", { name: "Drawing" }).click();
      await expect(page).not.toHaveURL(/tab=/);
      await page.getByRole("button", { name: /^Diagram settings/ }).click();
      const detail = page.getByRole("switch", { name: "Connection detail" });
      await detail.click();
      await expect(detail).toBeChecked();
      await page.keyboard.press("Escape");
      // The move made before the tab change and the setting is still pending.
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
      await page.getByRole("button", { name: "Undo" }).click();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    });

    await test.step("undo a move, then remove a box: the element stays in the model", async () => {
      await selectNode(page, queue);
      await page.keyboard.press("ArrowRight");
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
      await page.getByRole("button", { name: "Undo" }).click();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

      await selectNode(page, queue);
      await page.getByRole("button", { name: "Remove from diagram" }).click();
      await expect(page.getByLabel(`${queue}, node`, { exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.").last()).toBeVisible();

      await page.reload();
      await expect(page.getByLabel(`${gateway}, node`, { exact: true })).toBeVisible();
      await expect(page.getByLabel(`${queue}, node`, { exact: true })).toHaveCount(0);

      await page.goto(`/projects/${project.id}/modules/architecture/elements`);
      await expect(page.locator("tr", { hasText: queue })).toBeVisible();
    });
  });

  test("the drawing fits the screen without scrolling, and tags and components are set from one button beside the version", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchFit", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    await createElement(page.request, adminHeaders, project.id, `Gateway ${suffix}`);
    const component = await page.request.post(`${API}/api/v1/projects/${project.id}/components`, {
      headers: adminHeaders, data: { name: "Hardware", prefix: "HW" },
    });
    expect(component.ok(), await component.text()).toBeTruthy();
    const created = await page.request.post(`${base}/diagrams`, {
      headers: adminHeaders, data: { name: `Fit ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();

    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    const canvas = page.getByLabel(`Diagram Fit ${suffix}`, { exact: true });
    await expect(canvas).toBeVisible();

    await test.step("the whole canvas is inside the window without scrolling", async () => {
      await expect(page.getByLabel(`Gateway ${suffix}, node`, { exact: true })).toBeVisible();
      const box = await canvas.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(720);
    });

    await test.step("the toolbar's buttons and menu triggers are one height", async () => {
      await expect(page.getByRole("toolbar", { name: "Diagram editing" })).toBeVisible();
      expect((await page.evaluate(buttonHeightGeometry, undefined)).violations).toEqual([]);
    });

    await test.step("a record with no tags or components shows no empty line, only the button", async () => {
      await expect(page.getByText("Not placed in a component")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Tags and components" })).toBeVisible();
    });

    await test.step("a tag and a component are added from the dialog and appear beside the version", async () => {
      await page.getByRole("button", { name: "Tags and components" }).click();
      const dialog = page.getByRole("dialog", { name: "Tags and components" });
      await dialog.getByRole("button", { name: "Add tag" }).click();
      await page.getByRole("combobox", { name: "Tags" }).fill("Core");
      await page.keyboard.press("Enter");
      await expect(dialog.getByRole("button", { name: "Remove tag Core" })).toBeVisible();
      await page.getByRole("combobox", { name: "Tags" }).press("Escape");
      await dialog.getByRole("button", { name: "Components and categories" }).click();
      await page.getByRole("checkbox", { name: "Hardware", exact: true }).click();
      await page.keyboard.press("Escape");
      await expect(dialog.getByRole("button", { name: "Remove Hardware" })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      const header = page.locator("header.record-header");
      await expect(header.getByText("Core", { exact: true })).toBeVisible();
      await expect(header.getByText("Hardware", { exact: true })).toBeVisible();
    });
  });

  test("an architect assigns a component to a box from the Selection card and narrows the Add menu by a component", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchComp", true, "System Architecture");
    const projectBase = `${API}/api/v1/projects/${project.id}`;
    const gateway = `Gateway ${suffix}`;
    const relay = `Relay ${suffix}`;
    const cache = `Cache ${suffix}`;
    await createElement(page.request, adminHeaders, project.id, gateway);
    const hardware = await (await page.request.post(`${projectBase}/components`, { headers: adminHeaders, data: { name: "Hardware", prefix: "HW" } })).json();
    const category = await page.request.post(`${projectBase}/categories`, { headers: adminHeaders, data: { name: "Power", prefix: "PWR", component_id: hardware.id } });
    expect(category.ok(), await category.text()).toBeTruthy();
    const created = await page.request.post(`${projectBase}/modules/architecture/diagrams`, {
      headers: adminHeaders, data: { name: `Comp ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    // Created after the diagram, so both are offered by "Add existing elements"; only Relay sits in a component.
    const relayId = await createElement(page.request, adminHeaders, project.id, relay);
    await createElement(page.request, adminHeaders, project.id, cache);
    const placed = await page.request.put(`${projectBase}/artefacts/architecture_element/${relayId}/placements`, {
      headers: adminHeaders, data: { placements: [{ component_id: hardware.id, category_id: null }] },
    });
    expect(placed.ok(), await placed.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`${gateway}, node`, { exact: true })).toBeVisible();

    await test.step("the Components control of the Selection card stores the choice at once", async () => {
      await selectNode(page, gateway);
      const panel = page.getByRole("region", { name: "Selection" });
      await panel.getByRole("button", { name: "Components and categories" }).click();
      const saved = page.waitForResponse((r) => r.url().includes("/placements") && r.request().method() === "PUT");
      await page.getByRole("checkbox", { name: "Hardware", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      await page.keyboard.press("Escape");
      await expect(panel.getByRole("button", { name: "Remove Hardware" })).toBeVisible();
      await page.reload();
      await selectNode(page, gateway);
      await expect(page.getByRole("region", { name: "Selection" }).getByRole("button", { name: "Remove Hardware" })).toBeVisible();
    });

    await test.step("the component tree collapses, and the Add menu list narrows to the ticked component", async () => {
      await page.getByRole("button", { name: "Add to diagram" }).click();
      await page.getByRole("menuitem", { name: "Add existing elements" }).click();
      const dialog = page.getByRole("dialog", { name: "Add existing elements" });
      await expect(dialog.getByRole("checkbox", { name: `Add ${cache}` })).toBeVisible();
      await dialog.getByRole("button", { name: "Component and category", exact: true }).click();
      await expect(page.getByRole("checkbox", { name: "Hardware / Power" })).toBeVisible();
      await page.getByRole("button", { name: "Collapse Hardware" }).click();
      await expect(page.getByRole("checkbox", { name: "Hardware / Power" })).toHaveCount(0);
      await page.getByRole("checkbox", { name: "Hardware", exact: true }).click();
      await page.keyboard.press("Escape");
      await expect(dialog.getByRole("checkbox", { name: `Add ${relay}` })).toBeVisible();
      await expect(dialog.getByRole("checkbox", { name: `Add ${cache}` })).toHaveCount(0);
    });
  });

  test("a save from a stale copy is refused and the architect is offered a reload", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchConflict", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gateway = `Gateway ${suffix}`;
    await createElement(page.request, adminHeaders, project.id, gateway);

    const created = await page.request.post(`${base}/diagrams`, {
      headers: adminHeaders, data: { name: `Shared ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`${gateway}, node`, { exact: true })).toBeVisible();

    // Another person saves first, which advances the diagram's version.
    const other = await page.request.put(`${base}/diagrams/${diagram.id}`, {
      headers: adminHeaders, data: { version: diagram.version, purpose: "Changed elsewhere" },
    });
    expect(other.ok(), await other.text()).toBeTruthy();

    await selectNode(page, gateway);
    await page.keyboard.press("ArrowRight");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const alert = page.getByRole("alert").filter({ hasText: "Someone else saved this diagram" });
    await expect(alert).toBeVisible();
    await alert.getByRole("button", { name: "Reload diagram" }).click();
    await expect(alert).toHaveCount(0);
    await expect(page.getByText(/Changed elsewhere/)).toBeVisible();
  });

  test("an architect works the whole diagram from the keyboard and the outline, and exports it", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchKeys", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gateway = `Gateway ${suffix}`;
    const orders = `Orders ${suffix}`;
    await createElement(page.request, adminHeaders, project.id, gateway);
    await createElement(page.request, adminHeaders, project.id, orders);
    const created = await page.request.post(`${base}/diagrams`, {
      headers: adminHeaders, data: { name: `Keys ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`${gateway}, node`, { exact: true })).toBeVisible();

    await test.step("the Outline tab lists the same elements and selecting there fills the Selection card", async () => {
      await page.getByRole("tab", { name: "Outline" }).click();
      const outline = page.getByRole("region", { name: "Outline" });
      await expect(outline.getByRole("button", { name: new RegExp(`^ELM-\\d+ ${orders}`) })).toBeVisible();
      await outline.getByRole("button", { name: new RegExp(`^ELM-\\d+ ${orders}`) }).click();
      await expect(page.getByRole("region", { name: "Selection" }).getByText(new RegExp(orders))).toBeVisible();
    });

    await test.step("the elements read as a table, and the sections collapse", async () => {
      const outline = page.getByRole("region", { name: "Outline" });
      await outline.getByRole("button", { name: "List view" }).click();
      const table = outline.getByRole("table", { name: "Elements" });
      await expect(table.getByRole("button", { name: new RegExp(`^ELM-\\d+ ${gateway}`) })).toBeVisible();
      await outline.getByRole("button", { name: "Elements section" }).click();
      await expect(table).toHaveCount(0);
      await outline.getByRole("button", { name: "Elements section" }).click();
      await outline.getByRole("button", { name: "Tree view" }).click();
      await expect(outline.getByRole("button", { name: new RegExp(`^ELM-\\d+ ${gateway}`) })).toBeVisible();
    });

    await test.step("Connect to starts a connection without dragging", async () => {
      await page.getByRole("tab", { name: "Drawing" }).click();
      await selectNode(page, gateway);
      const choose = page.getByRole("region", { name: "Selection" }).getByRole("combobox", { name: /Connect to/ });
      await choose.selectOption(await choose.locator("option", { hasText: orders }).getAttribute("value") ?? "");
      const dialog = page.getByRole("dialog", { name: "New connection" });
      await expect(dialog).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
    });

    await test.step("Alt+arrow resizes, Delete takes the box off the diagram and Undo brings it back", async () => {
      await selectNode(page, orders);
      await page.keyboard.press("Alt+ArrowRight");
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
      await page.keyboard.press("Delete");
      await expect(page.getByLabel(`${orders}, node`, { exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "Undo" }).click();
      await page.getByRole("button", { name: "Undo" }).click();
      await expect(page.getByLabel(`${orders}, node`, { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    });

    await test.step("export downloads an SVG and the Mermaid text named after the diagram", async () => {
      await page.getByRole("button", { name: "Export" }).click();
      const svg = page.waitForEvent("download");
      await page.getByRole("menuitem", { name: "SVG image" }).click();
      expect((await svg).suggestedFilename()).toMatch(/^DGM-\d+-keys-.*\.svg$/);
      await page.getByRole("button", { name: "Export" }).click();
      const mermaid = page.waitForEvent("download");
      await page.getByRole("menuitem", { name: "Download Mermaid text" }).click();
      expect((await mermaid).suggestedFilename()).toMatch(/\.mmd$/);
    });
  });

  test("an architect chooses where a line meets its boxes from the Selection card and by dragging its end, and the choice is kept", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchAnchors", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gateway = `Gateway ${suffix}`;
    const orders = `Orders ${suffix}`;
    const gatewayId = await createElement(page.request, adminHeaders, project.id, gateway);
    const ordersId = await createElement(page.request, adminHeaders, project.id, orders);
    const connectionTypes = await (await page.request.get(`${base}/connection-types`, { headers: adminHeaders })).json();
    const connection = await page.request.post(`${base}/connections`, {
      headers: adminHeaders,
      data: { connection_type_id: connectionTypes[0].id, source_element_id: gatewayId, target_element_id: ordersId, activate: true },
    });
    expect(connection.ok(), await connection.text()).toBeTruthy();
    const created = await page.request.post(`${base}/diagrams`, { headers: adminHeaders, data: { name: `Anchors ${suffix}`, activate: true } });
    const diagram = await created.json();
    const layout = await page.request.put(`${base}/diagrams/${diagram.id}/layout`, {
      headers: adminHeaders,
      data: {
        version: diagram.version,
        placements: [{ element_id: gatewayId, x: 0, y: 0 }, { element_id: ordersId, x: 400, y: 0 }],
        notes: [],
      },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    const line = page.getByLabel(`Connection from ${gateway} to ${orders}`, { exact: true });
    await expect(line).toBeAttached();
    await line.focus();
    await page.keyboard.press("Enter");
    const selection = page.getByRole("region", { name: "Selection" });
    const starts = selection.getByRole("combobox", { name: "Line starts at" });
    const ends = selection.getByRole("combobox", { name: "Line ends at" });

    await test.step("automatic ends are the facing sides of boxes side by side", async () => {
      await expect(starts).toHaveValue("");
      await expect(starts.locator("option:checked")).toHaveText("Automatic (Right)");
      await expect(ends.locator("option:checked")).toHaveText("Automatic (Left)");
    });

    await test.step("choosing the start from the list is an unsaved edit that Save stores", async () => {
      await starts.selectOption("bottom");
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.").last()).toBeVisible();
    });

    await test.step("dragging the end of the line to another point of the same box chooses that point", async () => {
      await line.focus();
      await page.keyboard.press("Enter");
      const handle = page.locator(`.react-flow__node[data-id="${ordersId}"] .react-flow__handle[data-handleid="top"]`);
      const updater = page.locator(".react-flow__edgeupdater-target").first();
      await expect(updater).toBeAttached();
      const from = (await updater.boundingBox())!;
      const to = (await handle.boundingBox())!;
      await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
      await page.mouse.down();
      await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 8 });
      await page.mouse.up();
      await expect(ends).toHaveValue("top");
      await expect(page.getByText(/Unsaved changes/)).toBeVisible();
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.").last()).toBeVisible();
    });

    await test.step("the choice is stored, shown after a reload and drawn by the server", async () => {
      await page.reload();
      await line.focus();
      await page.keyboard.press("Enter");
      await expect(starts).toHaveValue("bottom");
      await expect(ends).toHaveValue("top");
      const view = await (await page.request.get(`${base}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json();
      expect(view.anchors).toEqual([
        { source_element_id: gatewayId, target_element_id: ordersId, source_point: "bottom", target_point: "top" },
      ]);
      const svg = await (await page.request.get(`${base}/diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
      // Gateway is 160 x 80 at the origin and Orders the same at x = 400: bottom middle (80, 80) to top middle (480, 0).
      expect(svg).toContain('x1="80.0" y1="80.0" x2="480.0" y2="0.0"');
    });

    await test.step("choosing Automatic again removes the choice", async () => {
      await starts.selectOption("");
      await ends.selectOption("");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.").last()).toBeVisible();
      const view = await (await page.request.get(`${base}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json();
      expect(view.anchors).toEqual([]);
    });
  });
  test("an architect edits a box and adds a port from the diagram, and the Add menu leads to the type settings", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchEdit", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gateway = `Gateway ${suffix}`;
    await createElement(page.request, adminHeaders, project.id, gateway);
    const created = await page.request.post(`${base}/diagrams`, {
      headers: adminHeaders, data: { name: `Edit ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);

    await test.step("Edit element opens the element form over the diagram and the box is renamed", async () => {
      await selectNode(page, gateway);
      await page.getByRole("button", { name: "Edit element" }).click();
      const dialog = page.getByRole("dialog", { name: `Edit ${gateway}` });
      const renamed = `Edge ${suffix}`;
      await dialog.getByLabel("Name", { exact: true }).fill(renamed);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Element updated.")).toBeVisible();
      await expect(page.getByLabel(`${renamed}, node`, { exact: true })).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`/diagrams/${diagram.id}`));
    });

    await test.step("a port is added from the Selection card and stored at once", async () => {
      await selectNode(page, `Edge ${suffix}`);
      const card = page.getByRole("region", { name: "Selection" });
      const stored = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/ports") && r.ok());
      await card.getByPlaceholder("Port name").fill("Telemetry");
      await card.getByRole("button", { name: "Add port" }).click();
      await stored;
      await page.reload();
      await selectNode(page, `Edge ${suffix}`);
      await expect(page.getByRole("region", { name: "Selection" }).locator('input[value="Telemetry"]')).toBeVisible();
    });

    await test.step("the Add menu ends with the setup entry, which opens the Element Types settings", async () => {
      await page.getByRole("button", { name: "Add to diagram" }).click();
      await page.getByRole("menuitem", { name: "Set up element types" }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/admin/architecture/architecture-element-types`));
    });
  });

  test("an architect sets a display note on a box, sees it inside the box and hides it for the viewer with Show notes", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchNote", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gateway = `Gateway ${suffix}`;
    await createElement(page.request, adminHeaders, project.id, gateway);
    const created = await page.request.post(`${base}/diagrams`, {
      headers: adminHeaders, data: { name: `Note ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    const note = `Entry point ${suffix}`;

    await test.step("the note is typed in the element form, apart from the description, and drawn in the box", async () => {
      await selectNode(page, gateway);
      await page.getByRole("button", { name: "Edit element" }).click();
      const dialog = page.getByRole("dialog", { name: `Edit ${gateway}` });
      await dialog.getByLabel("Description", { exact: true }).fill("Long text that a diagram never draws.");
      await dialog.getByLabel("Display note", { exact: true }).fill(note);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Element updated.")).toBeVisible();
      const box = page.getByLabel(`${gateway}, node`, { exact: true });
      await expect(box.getByText(note)).toBeVisible();
      await expect(box.getByText("Long text that a diagram never draws.")).toHaveCount(0);
    });

    await test.step("the Selection card shows the note and the description in full", async () => {
      await selectNode(page, gateway);
      const card = page.getByRole("region", { name: "Selection" });
      await expect(card.getByText(note)).toBeVisible();
      await expect(card.getByText("Long text that a diagram never draws.")).toBeVisible();
    });

    await test.step("Show notes in the gear hides the note on this screen only, and the choice is in the address", async () => {
      await page.getByRole("button", { name: /^Diagram settings/ }).click();
      await page.getByRole("switch", { name: "Show notes" }).click();
      await expect(page).toHaveURL(/notes=0/);
      await expect(page.getByLabel(`${gateway}, node`, { exact: true }).getByText(note)).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
      await page.reload();
      await expect(page.getByLabel(`${gateway}, node`, { exact: true })).toBeVisible();
      await expect(page.getByLabel(`${gateway}, node`, { exact: true }).getByText(note)).toHaveCount(0);
    });
  });

  test("an architect annotates a diagram with a toned note, points it at a box and then at a spot, and the leader is kept", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchLead", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gateway = `Gateway ${suffix}`;
    const gatewayId = await createElement(page.request, adminHeaders, project.id, gateway);
    const created = await page.request.post(`${base}/diagrams`, {
      headers: adminHeaders, data: { name: `Leader ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    const leaders = page.locator(".react-flow__edge.graph-leader");
    /** Presses Save and waits for the layout write and the read-back that follows it, so a later read sees what was stored. */
    const saveLayout = async () => {
      const saved = page.waitForResponse((r) => r.url().endsWith(`/diagrams/${diagram.id}/layout`) && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    };
    const stored = async () => (await (await page.request.get(`${base}/diagrams/${diagram.id}/view`, { headers: adminHeaders })).json()).notes;

    await test.step("a note gets text, a tone and a leader to the box", async () => {
      await page.getByRole("button", { name: "Add to diagram" }).click();
      await page.getByRole("menuitem", { name: "Add note" }).click();
      await page.getByRole("textbox", { name: "Note text" }).fill("Single point of failure");
      await page.getByRole("combobox", { name: "Tone", exact: true }).selectOption("danger");
      await page.getByRole("combobox", { name: "Points at", exact: true }).selectOption(`element:${gatewayId}`);
      await expect(leaders).toHaveCount(1);
      await saveLayout();
      expect(await stored()).toMatchObject([{ text: "Single point of failure", tone: "danger", leader_kind: "element", leader_element_id: gatewayId }]);
    });

    await test.step("the leader and the tone are still there after a reload", async () => {
      await page.reload();
      await expect(leaders).toHaveCount(1);
      await expect(page.locator(".graph-node-tone-danger")).toHaveCount(1);
    });

    await test.step("Point at a spot waits for a click on the canvas, and undo returns to the box", async () => {
      await page.getByLabel("Single point of failure, node").focus();
      await page.keyboard.press("Enter");
      await page.getByRole("button", { name: "Point at a spot" }).click();
      await expect(page.getByText("Click the canvas to place the end of the line.")).toBeVisible();
      const pane = page.locator(".react-flow__pane");
      const box = await pane.boundingBox();
      await page.mouse.click(box!.x + box!.width - 40, box!.y + box!.height - 40);
      await expect(page.getByRole("combobox", { name: "Points at", exact: true })).toHaveValue("spot");
      await expect(leaders).toHaveCount(1);
      await page.getByRole("button", { name: "Undo" }).click();
      await expect(page.getByRole("combobox", { name: "Points at", exact: true })).toHaveValue(`element:${gatewayId}`);
      await page.getByRole("button", { name: "Redo" }).click();
      await saveLayout();
      expect(await stored()).toMatchObject([{ leader_kind: "point", leader_element_id: null }]);
    });

    await test.step("removing the leader keeps the note", async () => {
      await page.getByRole("combobox", { name: "Points at", exact: true }).selectOption("");
      await expect(leaders).toHaveCount(0);
      await saveLayout();
      expect(await stored()).toMatchObject([{ text: "Single point of failure", leader_kind: "none" }]);
    });
  });

  test("an architect edits a connection from the diagram and the line is redrawn", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchConEdit", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const gateway = `Gateway ${suffix}`;
    const orders = `Orders ${suffix}`;
    const gatewayId = await createElement(page.request, adminHeaders, project.id, gateway);
    const ordersId = await createElement(page.request, adminHeaders, project.id, orders);
    const connectionTypes = await (await page.request.get(`${base}/connection-types`, { headers: adminHeaders })).json();
    const made = await page.request.post(`${base}/connections`, {
      headers: adminHeaders,
      data: { connection_type_id: connectionTypes[0].id, source_element_id: gatewayId, target_element_id: ordersId, activate: true },
    });
    expect(made.ok(), await made.text()).toBeTruthy();
    const connection = await made.json();
    const created = await page.request.post(`${base}/diagrams`, {
      headers: adminHeaders, data: { name: `Connections ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);

    const line = page.getByLabel(`Connection from ${gateway} to ${orders}`, { exact: true });
    await expect(line).toBeAttached();
    await line.focus();
    await page.keyboard.press("Enter");
    const card = page.getByRole("region", { name: "Selection" });

    await test.step("Edit opens the connection form over the diagram and the protocol is stored", async () => {
      await card.getByRole("button", { name: `Edit ${connection.unique_code}` }).click();
      const dialog = page.getByRole("dialog", { name: /^Edit / });
      await dialog.getByLabel("Protocol", { exact: true }).fill("MQTT");
      const stored = page.waitForResponse((r) => r.request().method() === "PUT" && r.url().includes(`/connections/${connection.id}`) && r.ok());
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await stored;
      await expect(page.getByText("Connection updated.")).toBeVisible();
      await expect(dialog).toBeHidden();
      await expect(page).toHaveURL(new RegExp(`/diagrams/${diagram.id}`));
    });

    await test.step("the Selection card shows the new protocol", async () => {
      await expect(line).toBeAttached();
      await line.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("region", { name: "Selection" }).getByText(/MQTT/)).toBeVisible();
    });
  });

  test("an architect double-clicks a box to work inside it and adds a sub-component there", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchInside", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const head = `Sensor head ${suffix}`;
    const filter = `High pass filter ${suffix}`;
    await createElement(page.request, adminHeaders, project.id, head);
    const created = await page.request.post(`${base}/diagrams`, {
      headers: adminHeaders, data: { name: `Overview ${suffix}`, activate: true, populate: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);

    await test.step("the system context explains itself", async () => {
      await expect(page.getByRole("button", { name: "Help: System context" })).toBeVisible();
    });

    await test.step("a double-click opens the inside of the box as a diagram of its own", async () => {
      await page.getByLabel(`${head}, node`, { exact: true }).dblclick();
      await expect(page.getByText(`Inside ELM-`)).toBeVisible();
      await expect(page.getByText(/Nothing is inside this element yet/)).toBeVisible();
    });

    await test.step("a new element created there is a child of the box", async () => {
      await page.getByRole("button", { name: "Add to diagram" }).click();
      await page.getByRole("menuitem", { name: "Component", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "New Component" });
      await dialog.getByLabel("Name", { exact: true }).fill(filter);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByLabel(`${filter}, node`, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.").last()).toBeVisible();
      const elements = await (await page.request.get(`${base}/elements`, { headers: adminHeaders })).json();
      const child = elements.find((e: { name: string }) => e.name === filter);
      const parent = elements.find((e: { name: string }) => e.name === head);
      expect(child.parent_id).toBe(parent.id);
    });
  });

  test("an architect draws the connections that cross an element's boundary, marks one as realised and sees it covered", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchBoundary", true, "System Architecture");
    const base = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const scope = await createElement(page.request, adminHeaders, project.id, `Telemetry ${suffix}`);
    const encoder = `Encoder ${suffix}`;
    const framer = `Framer ${suffix}`;
    const encoderId = await createElement(page.request, adminHeaders, project.id, encoder, scope);
    const framerId = await createElement(page.request, adminHeaders, project.id, framer, scope);
    const cloud = `Cloud ${suffix}`;
    const cloudId = await createElement(page.request, adminHeaders, project.id, cloud);
    const connectionTypes = await (await page.request.get(`${base}/connection-types`, { headers: adminHeaders })).json();
    // A one-way type, so the box's direction (an output: the scope sends) is known.
    const restApi = connectionTypes.find((t: { name: string }) => t.name === "REST API");
    const connect = async (source: string, target: string, name: string) => {
      const made = await page.request.post(`${base}/connections`, {
        headers: adminHeaders,
        data: { connection_type_id: restApi.id, source_element_id: source, target_element_id: target, name, activate: true },
      });
      expect(made.ok(), await made.text()).toBeTruthy();
      return made.json();
    };
    const outer = await connect(scope, cloudId, `Uplink ${suffix}`);
    const inner = await connect(encoderId, framerId, `Frames ${suffix}`);
    const created = await page.request.post(`${base}/diagrams`, {
      headers: adminHeaders, data: { name: `Inside ${suffix}`, activate: true, populate: true, scope_element_id: scope },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    const box = page.getByLabel(`${outer.unique_code}, node`, { exact: true });

    await test.step("the Add menu lists the connection crossing the boundary and draws it as a box that is not covered yet", async () => {
      await expect(box).toHaveCount(0);
      await page.getByRole("button", { name: "Add to diagram" }).click();
      await page.getByRole("menuitem", { name: new RegExp(`^${outer.unique_code} · ELM-\\d+ ${cloud}$`) }).click();
      await expect(box).toBeVisible();
      await expect(box).toContainText("Not covered");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.").last()).toBeVisible();
    });

    await test.step("the box is kept on reload and the Outline lists it with its direction", async () => {
      await page.reload();
      await expect(box).toContainText("Not covered");
      await page.getByRole("tab", { name: "Outline" }).click();
      const row = page.getByRole("table", { name: "Outer connections" }).getByRole("row", { name: new RegExp(outer.unique_code) });
      await expect(row).toContainText("Output");
      await expect(row).toContainText("Not covered");
      await page.getByRole("tab", { name: "Drawing" }).click();
    });

    await test.step("choosing the box lists what realises it and offers a connection to an inner element", async () => {
      await selectNode(page, outer.unique_code);
      const panel = page.getByRole("region", { name: "Selection" });
      await expect(panel.getByText("Not covered.")).toBeVisible();
      const choose = panel.getByRole("combobox", { name: /Connect to/ });
      await choose.selectOption(await choose.locator("option", { hasText: encoder }).getAttribute("value") ?? "");
      const dialog = page.getByRole("dialog", { name: "New connection" });
      await expect(dialog).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
    });

    await test.step("a line between inner elements is marked as realising the outer connection and the box reads covered", async () => {
      const line = page.getByLabel(`Connection from ${encoder} to ${framer}`, { exact: true });
      await expect(line).toBeAttached();
      await line.focus();
      await expect(line).toBeFocused();
      await page.keyboard.press("Enter");
      const panel = page.getByRole("region", { name: "Selection" });
      await expect(panel.getByText("No outer connection.")).toBeVisible();
      const choose = panel.getByRole("combobox", { name: "Add outer connection" });
      await choose.selectOption(await choose.locator("option", { hasText: outer.unique_code }).getAttribute("value") ?? "");
      await expect(box).toContainText("Covered");
      await expect(box).not.toContainText("Not covered");
    });

    await test.step("the connection page lists both sides of the realisation", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/connections/${inner.id}`);
      await expect(page.getByText("Realises", { exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: outer.unique_code })).toBeVisible();
      await page.goto(`/projects/${project.id}/modules/architecture/connections/${outer.id}`);
      await expect(page.getByText("Realised by", { exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: inner.unique_code })).toBeVisible();
    });
  });
});
