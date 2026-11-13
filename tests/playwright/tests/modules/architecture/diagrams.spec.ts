import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** Creates an active element through the API and returns its id; the diagram is the subject here, not the element form. */
async function createElement(request: APIRequestContext, headers: Record<string, string>, projectId: string, name: string): Promise<string> {
  const base = `${API}/api/v1/projects/${projectId}/modules/architecture`;
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
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
});
