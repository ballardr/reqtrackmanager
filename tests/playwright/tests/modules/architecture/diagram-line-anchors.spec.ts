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

/** The path of every line drawn on the canvas, by its text. */
async function drawnPaths(page: Page): Promise<string[]> {
  return page.locator(".react-flow__edge path.react-flow__edge-path").evaluateAll((paths) => paths.map((p) => p.getAttribute("d") ?? ""));
}

/** The straight connection or transition lines of the server's drawing as `x1,y1-x2,y2` with the two ends in a fixed order, so a line drawn the other way round reads the same. */
function serverLines(svg: string): string[] {
  return [...svg.matchAll(/<line x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" y2="([\d.-]+)"[^>]*stroke-width="2"/g)].map(([, a, b, c, d]) => {
    const ends = [`${a},${b}`, `${c},${d}`].sort();
    return ends.join("-");
  });
}

/**
 * Job to be done: a person draws a line each way between two boxes (or a loop back to a box they came from) and each line
 * must be seen, never drawn over another. Lines take different attach points, and the server's drawing (the SVG and PNG
 * exports) places them the same way.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; elements, states, transitions and diagrams are
 * created through the API as setup, the behaviour under test through the UI.
 */
test.describe("System Architecture: lines never overlap", () => {
  test("a block diagram draws a connection each way on two paths, and the server drawing agrees", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchAnchors", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const a = await createElement(page.request, arch, adminHeaders, `Alpha ${suffix}`);
    const b = await createElement(page.request, arch, adminHeaders, `Bravo ${suffix}`);
    const types = await (await page.request.get(`${arch}/connection-types`, { headers: adminHeaders })).json();
    for (const [source, target] of [[a, b], [b, a]]) {
      const made = await page.request.post(`${arch}/connections`, {
        headers: adminHeaders, data: { connection_type_id: types[0].id, source_element_id: source, target_element_id: target, activate: true },
      });
      expect(made.ok(), await made.text()).toBeTruthy();
    }
    const created = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Both ways ${suffix}`, activate: true, connection_detail: true } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const diagram = await created.json();
    const laid = await page.request.put(`${arch}/diagrams/${diagram.id}/layout`, {
      headers: adminHeaders,
      data: { version: diagram.version, placements: [{ element_id: a, x: 0, y: 0 }, { element_id: b, x: 400, y: 0 }], notes: [] },
    });
    expect(laid.ok(), await laid.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/architecture/diagrams/${diagram.id}`);
    await expect(page.getByLabel(`Bravo ${suffix}, node`, { exact: true })).toBeVisible();
    await expect(page.locator(".react-flow__edge")).toHaveCount(2);

    await test.step("the two connections are drawn on different paths", async () => {
      const paths = await drawnPaths(page);
      expect(new Set(paths).size).toBe(2);
    });

    await test.step("the server's drawing places them the same way, on two different lines", async () => {
      const svg = await (await page.request.get(`${arch}/diagrams/${diagram.id}/svg`, { headers: adminHeaders })).text();
      const lines = serverLines(svg);
      expect(lines.length).toBe(2);
      expect(new Set(lines).size).toBe(2);
    });

    await test.step("a reload draws the same lines", async () => {
      const before = await drawnPaths(page);
      await page.reload();
      await expect(page.getByLabel(`Bravo ${suffix}, node`, { exact: true })).toBeVisible();
      await expect.poll(() => drawnPaths(page)).toEqual(before);
    });
  });

  test("a state machine diagram draws a transition each way, a loop back and two loops on one state without overlap", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchAnchorsSm", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const element = await createElement(page.request, arch, adminHeaders, `Printer ${suffix}`);
    const made = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Modes ${suffix}`, element_id: element } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const machine = await made.json();
    const version = async () => (await (await page.request.get(`${arch}/state-machine-diagrams/${machine.id}`, { headers: adminHeaders })).json()).version;
    const states: Record<string, string> = {};
    const places: Record<string, { kind: string; x: number; y: number }> = {
      Idle: { kind: "state", x: 0, y: 0 }, Check: { kind: "choice", x: 340, y: 20 }, Busy: { kind: "state", x: 520, y: 0 },
    };
    for (const [name, place] of Object.entries(places)) {
      const state = await page.request.post(`${arch}/state-machine-diagrams/${machine.id}/states`, {
        headers: adminHeaders, data: { version: await version(), name: `${name} ${suffix}`, ...place },
      });
      expect(state.ok(), await state.text()).toBeTruthy();
      states[name] = (await state.json()).id;
    }
    // Into the choice, on to Busy, back to Idle from the choice (the loop back), and two loops on Busy.
    for (const [source, target, event] of [["Idle", "Check", "go"], ["Check", "Busy", "yes"], ["Check", "Idle", "no"], ["Busy", "Busy", "retry"], ["Busy", "Busy", "again"]]) {
      const transition = await page.request.post(`${arch}/state-machine-diagrams/${machine.id}/transitions`, {
        headers: adminHeaders, data: { version: await version(), source_state_id: states[source], target_state_id: states[target], event },
      });
      expect(transition.ok(), await transition.text()).toBeTruthy();
    }

    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${machine.id}`);
    await expect(page.getByLabel(`Busy ${suffix}, node`, { exact: true })).toBeVisible();
    await expect(page.locator(".react-flow__edge")).toHaveCount(5);

    await test.step("every transition is drawn on its own path, the two loops included", async () => {
      const paths = await drawnPaths(page);
      expect(paths.length).toBe(5);
      expect(new Set(paths).size).toBe(5);
    });

    await test.step("the server's drawing has distinct straight lines and distinct loops", async () => {
      const svg = await (await page.request.get(`${arch}/state-machine-diagrams/${machine.id}/svg`, { headers: adminHeaders })).text();
      const lines = serverLines(svg);
      expect(lines.length).toBe(3);
      expect(new Set(lines).size).toBe(3);
      const loops = [...svg.matchAll(/<path d="(M [^"]+ C [^"]+)"/g)].map((m) => m[1]);
      expect(loops.length).toBe(2);
      expect(new Set(loops).size).toBe(2);
    });
  });

  test("an attach point a person chooses is kept, shown as chosen, and the other line gives way", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ArchAnchorsPin", true, "System Architecture");
    const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
    const element = await createElement(page.request, arch, adminHeaders, `Printer ${suffix}`);
    const made = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Pin ${suffix}`, element_id: element } });
    expect(made.ok(), await made.text()).toBeTruthy();
    const machine = await made.json();
    let version = machine.version;
    const ids: string[] = [];
    for (const [index, name] of ["Idle", "Running"].entries()) {
      const added = await page.request.post(`${arch}/state-machine-diagrams/${machine.id}/states`, {
        headers: adminHeaders, data: { version, name, kind: "state", x: 40 + index * 400, y: 40, width: 160, height: 64 },
      });
      expect(added.ok(), await added.text()).toBeTruthy();
      const body = await added.json();
      ids.push(body.id);
      version = body.state_machine_diagram_version;
    }
    const transitions: string[] = [];
    for (const [source, target, event] of [[ids[0], ids[1], "start"], [ids[1], ids[0], "stop"]]) {
      const added = await page.request.post(`${arch}/state-machine-diagrams/${machine.id}/transitions`, {
        headers: adminHeaders, data: { version, source_state_id: source, target_state_id: target, event },
      });
      expect(added.ok(), await added.text()).toBeTruthy();
      const body = await added.json();
      transitions.push(body.id);
      version = body.state_machine_diagram_version ?? (await (await page.request.get(`${arch}/state-machine-diagrams/${machine.id}`, { headers: adminHeaders })).json()).version;
    }
    const [start, stop] = transitions;
    const pathOf = async (id: string) => (await page.locator(`.react-flow__edge[data-id="${id}"] path.react-flow__edge-path`).getAttribute("d")) ?? "";

    await page.goto(`/projects/${project.id}/modules/architecture/state-machine-diagrams/${machine.id}`);
    await expect(page.getByLabel("Running, node", { exact: false })).toBeVisible();
    await expect(page.locator(".react-flow__edge")).toHaveCount(2);
    const startBefore = await pathOf(start);

    await test.step("the Selection card says which point Automatic would take for the line that gave way", async () => {
      await page.locator(`.react-flow__edge[data-id="${stop}"]`).focus();
      await page.keyboard.press("Enter");
      const first = page.getByLabel("Line starts at").locator("option").first();
      await expect(first).toHaveText(/^Automatic \(/);
      // The facing side of Running is held by the other line, so Automatic is not its Left.
      await expect(first).not.toHaveText("Automatic (Left)");
    });

    await test.step("choosing Left on the second line keeps it there and moves the first line off the facing sides", async () => {
      await page.getByLabel("Line starts at").selectOption("left");
      await page.getByLabel("Line ends at").selectOption("right");
      const saved = page.waitForResponse((r) => r.url().includes(`/state-machine-diagrams/${machine.id}/layout`) && r.request().method() === "PUT");
      await page.getByRole("button", { name: "Save diagram", exact: true }).click();
      expect((await saved).ok()).toBeTruthy();
      await expect.poll(() => pathOf(start)).not.toEqual(startBefore);
    });

    await test.step("a reload keeps the choice", async () => {
      await page.reload();
      await expect(page.getByLabel("Running, node", { exact: false })).toBeVisible();
      await page.locator(`.react-flow__edge[data-id="${stop}"]`).focus();
      await page.keyboard.press("Enter");
      await expect(page.getByLabel("Line starts at")).toHaveValue("left");
      await expect(page.getByLabel("Line ends at")).toHaveValue("right");
    });
  });
});
