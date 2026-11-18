import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/** Creates an active element through the API (setup) and returns its id. */
async function createElement(request: APIRequestContext, base: string, headers: Record<string, string>, name: string): Promise<string> {
  const types = await (await request.get(`${base}/element-types`, { headers })).json();
  const created = await request.post(`${base}/elements`, { headers, data: { name, element_type_id: types[0].id, activate: true } });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id;
}

/** Shows a help button's text by hovering it and returns the tooltip's text. */
async function helpText(page: Page, scope: ReturnType<Page["locator"]>, name: string): Promise<string> {
  const button = scope.getByRole("button", { name: `Help: ${name}`, exact: true });
  await button.hover();
  const tip = page.getByRole("tooltip");
  await expect(tip).toBeVisible();
  const text = (await tip.textContent()) ?? "";
  await page.mouse.move(0, 0);
  await expect(tip).toHaveCount(0);
  return text;
}

/**
 * Job to be done: a reader who does not know UML or the module's own terms learns what each one means from the screen, in plain
 * words, on the heading, column header or label that names it, by pointer or by keyboard.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; records are created through the API as setup,
 * the behaviour under test through the UI.
 */
test.describe("System Architecture: help for notation and domain terms", () => {
  test("a state machine diagram explains event, condition, action and the state kinds", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchTermsA", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, arch, adminHeaders, `Pump ${suffix}`);
    const created = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Modes ${suffix}`, element_id: elementId } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    let version = diagram.version;
    const ids: string[] = [];
    for (const [name, x] of [["Idle", 40], ["Running", 300]] as const) {
      const added = await page.request.post(`${arch}/state-machine-diagrams/${diagram.id}/states`, {
        headers: adminHeaders, data: { version, name, kind: "state", x, y: 40, width: 160, height: 64, entry_action: "start motor" },
      });
      expect(added.ok(), await added.text()).toBeTruthy();
      const body = await added.json();
      ids.push(body.id);
      version = body.state_machine_diagram_version;
    }
    const transition = await page.request.post(`${arch}/state-machine-diagrams/${diagram.id}/transitions`, {
      headers: adminHeaders, data: { version, source_state_id: ids[0], target_state_id: ids[1], event: "start", guard: "battery ok", action: "log" },
    });
    expect(transition.ok(), await transition.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${diagram.id}?tab=outline`);
    const transitions = page.getByRole("table", { name: "Transitions" });
    await expect(transitions).toBeVisible();

    await test.step("the transition table's headers explain event, condition (guard) and action on hover", async () => {
      expect(await helpText(page, transitions, "Event")).toContain("triggers the transition");
      expect(await helpText(page, transitions, "Condition (guard)")).toContain("guard");
      expect(await helpText(page, transitions, "Action")).toContain("transition is taken");
    });

    await test.step("a header's help is reached and shown by keyboard", async () => {
      const button = transitions.getByRole("button", { name: "Help: Condition (guard)", exact: true });
      await button.focus();
      await expect(page.getByRole("tooltip")).toContainText("battery low");
      await button.blur(); // a keyboard-focus tooltip stays open until the focus leaves
    });

    await test.step("the States section lists the kinds, one line each", async () => {
      const text = await helpText(page, page.locator("body"), "States");
      for (const kind of ["Initial state:", "Final state:", "Choice:"]) expect(text).toContain(kind);
    });
  });

  test("a block diagram, an element and a connection explain ports, direction and routes", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchTermsB", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const elementId = await createElement(page.request, arch, adminHeaders, `Hub ${suffix}`);
    const otherId = await createElement(page.request, arch, adminHeaders, `Spoke ${suffix}`);
    const connectionTypes = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
    const connection = await page.request.post(`${arch}/connections`, {
      headers: adminHeaders,
      data: { connection_type_id: connectionTypes[0].id, source_element_id: elementId, target_element_id: otherId, activate: true },
    });
    expect(connection.ok(), await connection.text()).toBeTruthy();
    const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Main ${suffix}`, activate: true, populate: true } });
    expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
    const diagram = await diagramRes.json();

    await test.step("the element page's Ports heading says what a port is", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/elements/${elementId}`);
      const ports = page.getByRole("region", { name: "Ports" });
      await expect(ports).toBeVisible();
      expect(await helpText(page, ports, "Ports")).toContain("named point where a connection meets the element");
    });

    await test.step("the Outline's Lines table explains direction and route", async () => {
      await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}?tab=outline`);
      const outline = page.getByRole("region", { name: "Outline" });
      await expect(outline).toBeVisible();
      const lines = outline.getByRole("button", { name: "Help: Route", exact: true });
      await lines.hover();
      const tip = page.getByRole("tooltip");
      await expect(tip).toContainText("Rolled up:");
      await expect(tip).toContainText("Bridged:");
    });
  });
});
