import { expect, test, type APIRequestContext } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

type Headers = Record<string, string>;

/** Creates an active element through the API (setup) and returns its id. */
async function createElement(request: APIRequestContext, base: string, headers: Headers, name: string): Promise<string> {
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/**
 * Job to be done: an architect has a diagram of links with names (a connection called "Telemetry feed"), and switches on Show
 * connection names so each line says what it carries. The names are a setting of the diagram, so they are still there after a
 * reload and in the SVG download everyone gets.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements, the named connection and the diagram
 * are created through the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: connection names on a diagram", () => {
  test("a line carries the name of its connection once Show connection names is on, and keeps it after a reload", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchNames", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const source = await createElement(page.request, arch, adminHeaders, `Sensor ${suffix}`);
    const target = await createElement(page.request, arch, adminHeaders, `Gateway ${suffix}`);
    const types = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
    const connection = await page.request.post(`${arch}/connections`, {
      headers: adminHeaders,
      data: { connection_type_id: types[0].id, source_element_id: source, target_element_id: target, name: `Telemetry feed ${suffix}`, activate: true },
    });
    expect(connection.ok(), await connection.text()).toBeTruthy();
    const made = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Links ${suffix}`, activate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const diagram = await made.json();
    const laid = await page.request.put(`${arch}/diagrams/${diagram.id}/layout`, {
      headers: adminHeaders,
      data: {
        version: diagram.version, notes: [],
        placements: [{ element_id: source, x: 0, y: 0 }, { element_id: target, x: 500, y: 0 }],
      },
    });
    expect(laid.ok(), await laid.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`Gateway ${suffix}, node`, { exact: true })).toBeVisible();
    const name = page.getByText(`Telemetry feed ${suffix}`, { exact: true });

    await test.step("no line is named while the setting is off", async () => {
      await expect(page.locator(".react-flow__edge")).toHaveCount(1);
      await expect(name).toHaveCount(0);
    });

    await test.step("switching it on writes the connection's name beside the line", async () => {
      await page.getByRole("button", { name: /^Diagram settings/ }).click();
      const switchControl = page.getByRole("dialog", { name: "Diagram settings" }).getByRole("switch", { name: "Show connection names" });
      await expect(switchControl).toHaveAttribute("aria-checked", "false");
      const stored = page.waitForResponse((r) => r.url().includes("/diagrams/") && r.request().method() === "PUT" && r.ok());
      await switchControl.click();
      await stored;
      await expect(switchControl).toHaveAttribute("aria-checked", "true");
      await page.keyboard.press("Escape");
      await expect(name).toBeVisible();
    });

    await test.step("the setting is stored with the diagram and survives a reload", async () => {
      await page.reload();
      await expect(page.getByLabel(`Gateway ${suffix}, node`, { exact: true })).toBeVisible();
      await expect(name).toBeVisible();
      const server = await (await page.request.get(`${arch}/diagrams/${diagram.id}`, { headers: adminHeaders })).json();
      expect(server.show_connection_names).toBe(true);
    });

    await test.step("the SVG and Mermaid downloads carry the name", async () => {
      const svg = await (await page.request.get(`${arch}/diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
      expect(svg).toContain(`Telemetry feed ${suffix}`);
      const mermaid = await (await page.request.get(`${arch}/diagrams/${diagram.id}/mermaid`, { headers: adminHeaders })).text();
      expect(mermaid).toContain(`Telemetry feed ${suffix}`);
    });

    await test.step("switching it off again removes the name", async () => {
      await page.getByRole("button", { name: /^Diagram settings/ }).click();
      const switchControl = page.getByRole("dialog", { name: "Diagram settings" }).getByRole("switch", { name: "Show connection names" });
      const stored = page.waitForResponse((r) => r.url().includes("/diagrams/") && r.request().method() === "PUT" && r.ok());
      await switchControl.click();
      await stored;
      await page.keyboard.press("Escape");
      await expect(name).toHaveCount(0);
    });
  });
});
