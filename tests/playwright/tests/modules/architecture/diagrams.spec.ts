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
  test("an architect places elements, sees their connection, adds one from the palette and removes a box without deleting it", async ({ page }) => {
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
      await page.getByRole("link", { name: "Diagrams", exact: true }).click();
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
      await page.getByRole("button", { name: "Add existing elements" }).click();
      const dialog = page.getByRole("dialog", { name: "Add existing elements" });
      await dialog.getByRole("checkbox", { name: `Add ${gateway}` }).check();
      await dialog.getByRole("checkbox", { name: `Add ${orders}` }).check();
      await dialog.getByRole("button", { name: "Add selected (2)" }).click();
      await expect(page.getByLabel(`${gateway}, node`, { exact: true })).toBeVisible();
      await expect(page.getByText(/Unsaved changes/)).toBeVisible();
      // The line is drawn from the model data in the browser, so it is there before anything is stored.
      await expect(page.getByLabel(`Connection from ${gateway} to ${orders}`, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.")).toBeVisible();
      await expect(page.getByLabel(`Connection from ${gateway} to ${orders}`, { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    });

    await test.step("create an element from the palette and place it", async () => {
      await page.getByRole("button", { name: "New Service" }).click();
      const dialog = page.getByRole("dialog", { name: "New Service" });
      await dialog.getByLabel("Name", { exact: true }).fill(queue);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByLabel(`${queue}, node`, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Diagram saved.")).toBeVisible();
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
      await expect(page.getByText("Diagram saved.")).toBeVisible();

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
});
