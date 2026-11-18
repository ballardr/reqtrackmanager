import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

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

/** How many drawn lines of the canvas carry an arc in their path. */
async function hoppingLines(page: Page): Promise<number> {
  return page.locator(".react-flow__edge path.react-flow__edge-path").evaluateAll((paths) => paths.filter((p) => (p.getAttribute("d") ?? "").includes(" A ")).length);
}

/** Switches Line hops on or off in the settings button and waits for the diagram to be stored. */
async function setLineHops(page: Page, kind: "diagrams" | "state-machine-diagrams", on: boolean) {
  await page.getByRole("button", { name: /^Diagram settings/ }).click();
  const switchControl = page.getByRole("dialog", { name: "Diagram settings" }).getByRole("switch", { name: "Line hops" });
  await expect(switchControl).toHaveAttribute("aria-checked", on ? "false" : "true");
  const stored = page.waitForResponse((r) => r.url().includes(`/${kind}/`) && r.request().method() === "PUT" && r.ok());
  await switchControl.click();
  await stored;
  await expect(switchControl).toHaveAttribute("aria-checked", on ? "true" : "false");
  await page.keyboard.press("Escape");
}

/**
 * Job to be done: an architect has a drawing where two lines must cross, and switches on Line hops so the crossing is not read
 * as a junction. The arc is a setting of the diagram, so it is still there after a reload (and for everyone who opens it), on a
 * block diagram and on a state machine diagram alike.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements, connections, states and diagrams are
 * created through the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: line hops", () => {
  test("a block diagram draws an arc where two connections cross once Line hops is on, and keeps it after a reload", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchHops", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const ids: string[] = [];
    for (const name of ["Alpha", "Bravo", "Charlie", "Delta"]) ids.push(await createElement(page.request, arch, adminHeaders, `${name} ${suffix}`));
    const types = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
    for (const [source, target] of [[ids[0], ids[1]], [ids[2], ids[3]]]) {
      const connection = await page.request.post(`${arch}/connections`, {
        headers: adminHeaders, data: { connection_type_id: types[0].id, source_element_id: source, target_element_id: target, activate: true },
      });
      expect(connection.ok(), await connection.text()).toBeTruthy();
    }
    const made = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Cross ${suffix}`, activate: true } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const diagram = await made.json();
    const places = [{ x: 0, y: 300 }, { x: 700, y: 300 }, { x: 350, y: 0 }, { x: 350, y: 600 }];
    const laid = await page.request.put(`${arch}/diagrams/${diagram.id}/layout`, {
      headers: adminHeaders, data: { version: diagram.version, placements: ids.map((id, i) => ({ element_id: id, ...places[i] })), notes: [] },
    });
    expect(laid.ok(), await laid.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`Delta ${suffix}, node`, { exact: true })).toBeVisible();
    await expect(page.locator(".react-flow__edge")).toHaveCount(2);

    await test.step("lines cross with no arc while Line hops is off", async () => {
      expect(await hoppingLines(page)).toBe(0);
    });

    await test.step("switching Line hops on draws one arc, on one of the two lines", async () => {
      await setLineHops(page, "diagrams", true);
      await expect.poll(() => hoppingLines(page)).toBe(1);
    });

    await test.step("the setting is stored with the diagram and survives a reload", async () => {
      await page.reload();
      await expect(page.getByLabel(`Delta ${suffix}, node`, { exact: true })).toBeVisible();
      await expect.poll(() => hoppingLines(page)).toBe(1);
      const server = await (await page.request.get(`${arch}/diagrams/${diagram.id}`, { headers: adminHeaders })).json();
      expect(server.line_hops).toBe(true);
      // The server's own drawing carries the same arc.
      const svg = await (await page.request.get(`${arch}/diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
      expect(svg.match(/ A 6 6 0 0 [01] /g)?.length).toBe(1);
    });

    await test.step("switching it off again removes the arc", async () => {
      await setLineHops(page, "diagrams", false);
      await expect.poll(() => hoppingLines(page)).toBe(0);
    });
  });

  test("a state machine diagram draws an arc where two transitions cross and keeps it after a reload", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchHopsSm", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const element = await createElement(page.request, arch, adminHeaders, `Printer ${suffix}`);
    const made = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Modes ${suffix}`, element_id: element } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const machine = await made.json();
    const states: Record<string, string> = {};
    const places: Record<string, { x: number; y: number }> = { A: { x: 0, y: 300 }, B: { x: 700, y: 300 }, C: { x: 350, y: 0 }, D: { x: 350, y: 600 } };
    const version = async () => (await (await page.request.get(`${arch}/state-machine-diagrams/${machine.id}`, { headers: adminHeaders })).json()).version;
    for (const name of Object.keys(places)) {
      const state = await page.request.post(`${arch}/state-machine-diagrams/${machine.id}/states`, {
        headers: adminHeaders, data: { version: await version(), name: `${name} ${suffix}`, kind: "state", ...places[name] },
      });
      expect(state.ok(), await state.text()).toBeTruthy();
      states[name] = (await state.json()).id;
    }
    for (const [source, target] of [["A", "B"], ["C", "D"]]) {
      const transition = await page.request.post(`${arch}/state-machine-diagrams/${machine.id}/transitions`, {
        headers: adminHeaders, data: { version: await version(), source_state_id: states[source], target_state_id: states[target], event: `${source}${target}` },
      });
      expect(transition.ok(), await transition.text()).toBeTruthy();
    }

    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${machine.id}`);
    await expect(page.getByLabel(`D ${suffix}, node`, { exact: true })).toBeVisible();
    await expect(page.locator(".react-flow__edge")).toHaveCount(2);
    expect(await hoppingLines(page)).toBe(0);

    await setLineHops(page, "state-machine-diagrams", true);
    await expect.poll(() => hoppingLines(page)).toBe(1);

    await page.reload();
    await expect(page.getByLabel(`D ${suffix}, node`, { exact: true })).toBeVisible();
    await expect.poll(() => hoppingLines(page)).toBe(1);
    const svg = await (await page.request.get(`${arch}/state-machine-diagrams/${machine.id}/svg`, { headers: adminHeaders })).text();
    expect(svg.match(/ A 6 6 0 0 [01] /g)?.length).toBe(1);
  });
});
