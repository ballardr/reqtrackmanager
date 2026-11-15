import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000";

/**
 * Job to be done: a person looking at a block diagram sees which blocks have behaviour drawn as a state machine diagram, opens
 * it in one click, and gets back to the block diagram, with the block selected, without relying on browser history.
 *
 * Disposable org, admin and project via `setUpOrg` with System Architecture on; two elements (one described by a state machine
 * diagram), the block diagram placing both, and the state machine diagram are created through the API as setup.
 */
async function setUp(page: Page, label: string) {
  const { suffix, project, adminHeaders } = await setUpOrg(page, label, true, "System Architecture");
  const arch = `${API}/api/v1/projects/${project.id}/modules/architecture`;
  const types = await (await page.request.get(`${arch}/element-types`, { headers: adminHeaders })).json();
  const make = async (name: string) => {
    const res = await page.request.post(`${arch}/elements`, { headers: adminHeaders, data: { name, element_type_id: types[0].id, activate: true } });
    expect(res.ok(), await res.text()).toBeTruthy();
    return res.json();
  };
  const valve = await make(`Valve ${suffix}`);
  await make(`Pump ${suffix}`);
  const machineRes = await page.request.post(`${arch}/state-machine-diagrams`, { headers: adminHeaders, data: { name: `Valve modes ${suffix}`, element_id: valve.id } });
  expect(machineRes.ok(), await machineRes.text()).toBeTruthy();
  const machine = await machineRes.json();
  const diagramRes = await page.request.post(`${arch}/diagrams`, { headers: adminHeaders, data: { name: `Plant ${suffix}`, activate: true, populate: true } });
  expect(diagramRes.ok(), await diagramRes.text()).toBeTruthy();
  const diagram = await diagramRes.json();
  const root = `/projects/${project.id}/modules/architecture`;
  return {
    suffix, valve, machine, diagram, root,
    blockPath: `${root}/diagrams/${diagram.id}`, machinePath: `${root}/state-machine-diagrams/${machine.id}`,
  };
}


test.describe("System Architecture: from a block to its state machine diagram and back", () => {
  test("only a described block has a badge; it opens the diagram and Return selects the block again", async ({ page }) => {
    const s = await setUp(page, "SmLink");
    await page.goto(s.blockPath);
    await expect(page.getByLabel(`Valve ${s.suffix}, node`, { exact: true })).toBeVisible();
    await expect(page.getByLabel(`Pump ${s.suffix}, node`, { exact: true })).toBeVisible();

    await test.step("one badge, on the described block only", async () => {
      await expect(page.getByRole("button", { name: "Open state machine diagram" })).toHaveCount(1);
    });

    await test.step("pressing it opens the state machine diagram without selecting the block", async () => {
      await page.getByRole("button", { name: "Open state machine diagram" }).click();
      await expect(page).toHaveURL(new RegExp(`${s.machinePath}\\?from=${s.diagram.id}`));
      await expect(page.getByRole("heading", { name: new RegExp(`Valve modes ${s.suffix}`) })).toBeVisible();
    });

    await test.step("Return goes back to the block diagram with the block selected and the address cleaned once something else is chosen", async () => {
      await page.getByRole("link", { name: /^Return to .*Plant/ }).click();
      await expect(page).toHaveURL(new RegExp(`${s.blockPath}\\?select=${s.valve.id}`));
      await expect(page.locator(".react-flow__node.selected")).toHaveCount(1);
      await expect(page.locator(".react-flow__node.selected").getByText(`Valve ${s.suffix}`)).toBeVisible();
      await page.getByLabel(`Pump ${s.suffix}, node`, { exact: true }).click();
      await expect(page).not.toHaveURL(/select=/);
      await expect(page.locator(".react-flow__node.selected").getByText(`Pump ${s.suffix}`)).toBeVisible();
    });
  });

  test("without a from, an Open in diagram menu leads back, and an unreadable from is ignored", async ({ page }) => {
    const s = await setUp(page, "SmMenu");

    await test.step("opened directly, the header offers the block diagrams that draw the element", async () => {
      await page.goto(s.machinePath);
      await expect(page.getByRole("link", { name: /^Return to/ })).toHaveCount(0);
      await page.getByRole("button", { name: "Open in diagram" }).click();
      await page.getByRole("menuitem", { name: new RegExp(`Plant ${s.suffix}`) }).click();
      await expect(page).toHaveURL(new RegExp(`${s.blockPath}\\?select=${s.valve.id}`));
      await expect(page.locator(".react-flow__node.selected").getByText(`Valve ${s.suffix}`)).toBeVisible();
    });

    await test.step("a from naming nothing readable is ignored and the menu is offered instead", async () => {
      await page.goto(`${s.machinePath}?from=00000000-0000-4000-8000-000000000000`);
      await expect(page.getByRole("button", { name: "Open in diagram" })).toBeVisible();
      await expect(page.getByRole("link", { name: /^Return to/ })).toHaveCount(0);
    });

    await test.step("a reload keeps the Return link while the address names the diagram", async () => {
      await page.goto(`${s.machinePath}?from=${s.diagram.id}`);
      await expect(page.getByRole("link", { name: /^Return to .*Plant/ })).toBeVisible();
      await page.reload();
      await expect(page.getByRole("link", { name: /^Return to .*Plant/ })).toBeVisible();
    });
  });

  test("the keyboard reaches the state machine diagram from the badge and from the Selection card, and the Outline lists it", async ({ page }) => {
    const s = await setUp(page, "SmKey");
    await page.goto(s.blockPath);
    const valveBox = page.getByLabel(`Valve ${s.suffix}, node`, { exact: true });
    await expect(valveBox).toBeVisible();

    await test.step("Tab from the box reaches the badge and Enter opens the diagram", async () => {
      await valveBox.focus();
      await page.keyboard.press("Tab");
      await expect(page.getByRole("button", { name: "Open state machine diagram" })).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(new RegExp(`${s.machinePath}\\?from=`));
    });

    await test.step("the Selection card has the same action", async () => {
      await page.goto(s.blockPath);
      await valveBox.focus();
      await page.keyboard.press("Enter");
      await page.getByRole("group", { name: "Actions" }).getByRole("button", { name: "Open state machine diagram" }).click();
      await expect(page).toHaveURL(new RegExp(`${s.machinePath}\\?from=`));
    });

    await test.step("the Outline lists it beside the element", async () => {
      await page.goto(`${s.blockPath}?tab=outline`);
      await page.getByRole("button", { name: new RegExp(`Valve modes ${s.suffix}`) }).click();
      await expect(page).toHaveURL(new RegExp(`${s.machinePath}\\?from=`));
    });
  });
});
