import { expect, type APIRequestContext, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

type Headers = { Authorization: string };

/**
 * Job to be done: a Pain Point manager scoring a backlog should not open each Pain Point to set its severity,
 * frequency and confidence. The list has a Grid view of the same rows, with those levels (and Type, Priority and
 * the Intentional flag) as cells, saved row by row.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded state and can be
 * repeated against the same database. The org admin who creates it is a Pain Point manager.
 */
async function setUpPainPoints(page: Parameters<typeof setUpOrg>[0], request: APIRequestContext, label: string, count: number) {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, label);
  const enable = await request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy`;
  const types = await (await request.get(`${base}/pain-point-types`, { headers: adminHeaders })).json();
  const painPoints: { id: string; unique_code: string; title: string }[] = [];
  for (let n = 1; n <= count; n += 1) {
    const created = await request.post(`${base}/pain-points`, {
      headers: adminHeaders, data: { pain_point_type_id: types[0].id, title: `Grid problem ${n} ${suffix}`, description: "x" },
    });
    expect(created.ok()).toBeTruthy();
    painPoints.push(await created.json());
  }
  return { suffix, project, adminHeaders, base, painPoints };
}

/** The all-personas level names a Pain Point is scored with, read through the scores endpoint. */
async function scoreNames(request: APIRequestContext, base: string, headers: Headers, projectId: string, painPointId: string) {
  const scheme = await (await request.get(`${API_BASE_URL}/api/v1/projects/${projectId}/scoring-schemes/pain_point`, { headers })).json();
  const names = new Map<string, string>(scheme.axes.flatMap((a: { levels: { id: string; name: string }[] }) => a.levels.map((l) => [l.id, l.name])));
  const scores = await (await request.get(`${base}/pain-points/${painPointId}/scores`, { headers })).json();
  const entry = scores.entries[0];
  return entry
    ? { severity: names.get(entry.severity_level_id) ?? "", frequency: names.get(entry.frequency_level_id) ?? "", confidence: names.get(entry.confidence_level_id) ?? "" }
    : { severity: "", frequency: "", confidence: "" };
}

test("a manager scores several pain points from the grid and the saved levels show on the next load", async ({ page, request }) => {
  const { project, adminHeaders, base, painPoints } = await setUpPainPoints(page, request, "Grid", 3);
  const [a, b, c] = painPoints;

  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  await page.getByRole("button", { name: "Grid view" }).click();
  const grid = page.getByRole("table", { name: "Pain points grid" });
  await expect(grid).toBeVisible();

  await test.step("changed cells are marked and counted on the Save button", async () => {
    await grid.getByRole("combobox", { name: `Severity for ${a.unique_code}` }).selectOption({ label: "Blocker" });
    await grid.getByRole("combobox", { name: `Frequency for ${a.unique_code}` }).selectOption({ label: "Rare" });
    await grid.getByRole("combobox", { name: `Severity for ${b.unique_code}` }).selectOption({ label: "Minor" });
    await grid.getByRole("checkbox", { name: `Intentional for ${c.unique_code}` }).check();
    await expect(grid.getByRole("combobox", { name: `Severity for ${a.unique_code}` }).locator("xpath=ancestor::td")).toHaveClass(/record-grid__cell--changed/);
    await expect(page.getByRole("button", { name: "Save 3 changes" })).toBeEnabled();
  });

  await test.step("Save writes each row and reports the count", async () => {
    await page.getByRole("button", { name: "Save 3 changes" }).click();
    await expect(page.getByText("3 saved.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  await test.step("the levels are the Pain Points' scores, not grid-only values", async () => {
    expect(await scoreNames(request, base, adminHeaders, project.id, a.id)).toEqual({ severity: "Blocker", frequency: "Rare", confidence: "" });
    expect((await scoreNames(request, base, adminHeaders, project.id, b.id)).severity).toBe("Minor");
    const detail = await (await request.get(`${base}/pain-points/${c.id}`, { headers: adminHeaders })).json();
    expect(detail.is_intentional).toBe(true);
  });

  await test.step("the grid opens again with the saved values, and Enter moves down a column", async () => {
    await page.reload();
    const reloaded = page.getByRole("table", { name: "Pain points grid" });
    await expect(reloaded.getByRole("combobox", { name: `Severity for ${a.unique_code}` })).toHaveValue(/.+/);
    await expect(reloaded.getByRole("combobox", { name: `Severity for ${a.unique_code}` }).locator("option:checked")).toHaveText("Blocker");
    await reloaded.getByRole("combobox", { name: `Priority for ${a.unique_code}` }).focus();
    await page.keyboard.press("Enter");
    await expect(reloaded.getByRole("combobox", { name: `Priority for ${b.unique_code}` })).toBeFocused();
  });

  await test.step("the list view shows the same scores", async () => {
    await page.getByRole("button", { name: "List view" }).click();
    await expect(page.getByRole("table", { name: "Pain Points" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Pain Points" }).locator("tr", { hasText: a.title })).toContainText("Blocker");
  });
});

test("a row whose cell changed elsewhere stays changed with its message while the others save", async ({ page, request }) => {
  const { project, adminHeaders, base, painPoints } = await setUpPainPoints(page, request, "GridStale", 2);
  const [a, b] = painPoints;

  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  await page.getByRole("button", { name: "Grid view" }).click();
  const grid = page.getByRole("table", { name: "Pain points grid" });
  await expect(grid).toBeVisible();

  await grid.getByRole("combobox", { name: `Severity for ${a.unique_code}` }).selectOption({ label: "Blocker" });
  await grid.getByRole("combobox", { name: `Severity for ${b.unique_code}` }).selectOption({ label: "Minor" });

  // Someone else scores the first Pain Point after the grid loaded.
  const scheme = await (await request.get(`${API_BASE_URL}/api/v1/projects/${project.id}/scoring-schemes/pain_point`, { headers: adminHeaders })).json();
  const moderate = scheme.axes.find((x: { key: string }) => x.key === "severity").levels.find((l: { name: string }) => l.name === "Moderate");
  const elsewhere = await request.put(`${base}/pain-points/${a.id}/scores`, {
    headers: adminHeaders, data: { scores: [{ target_id: null, severity_level_id: moderate.id, frequency_level_id: null, confidence_level_id: null }] },
  });
  expect(elsewhere.ok()).toBeTruthy();

  await page.getByRole("button", { name: "Save 2 changes" }).click();
  await expect(page.getByText("1 saved, 1 failed.")).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: `${a.unique_code}: Severity was changed by someone else` })).toBeVisible();
  expect((await scoreNames(request, base, adminHeaders, project.id, a.id)).severity).toBe("Moderate");
  expect((await scoreNames(request, base, adminHeaders, project.id, b.id)).severity).toBe("Minor");
  await expect(page.getByRole("button", { name: "Save 1 change" })).toBeEnabled();
});

test("a pain point at a terminal outcome is read-only in the grid and says why", async ({ page, request }) => {
  const { project, adminHeaders, base, painPoints } = await setUpPainPoints(page, request, "GridLocked", 2);
  const [open, closed] = painPoints;
  expect((await request.post(`${base}/pain-points/${closed.id}/triage`, { headers: adminHeaders, data: {} })).ok()).toBeTruthy();
  expect((await request.post(`${base}/pain-points/${closed.id}/reject`, { headers: adminHeaders, data: { comment: "Not a defect" } })).ok()).toBeTruthy();

  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points?open=0`);
  await page.getByRole("button", { name: "Grid view" }).click();
  const grid = page.getByRole("table", { name: "Pain points grid" });
  await expect(grid.getByRole("combobox", { name: `Severity for ${open.unique_code}` })).toBeEnabled();
  await expect(grid.getByRole("combobox", { name: `Severity for ${closed.unique_code}` })).toHaveCount(0);
  await expect(grid.locator("tr", { hasText: closed.unique_code })).toContainText("terminal outcome");
  // The Editing column states every row's state, beside the status.
  await expect(grid.locator("tr", { hasText: closed.unique_code }).getByText("Read-only")).toBeVisible();
  await expect(grid.locator("tr", { hasText: closed.unique_code })).toContainText("Rejected");
  await expect(grid.locator("tr", { hasText: open.unique_code }).getByText("Editable")).toBeVisible();
});

test("the filter panel keeps its state when switching to the grid, and the grid's columns can be chosen", async ({ page, request }) => {
  const { project, painPoints } = await setUpPainPoints(page, request, "GridColumns", 2);
  const [a] = painPoints;

  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  await expect(page.getByLabel("Search Pain Points")).toBeVisible();
  await page.getByRole("button", { name: "Collapse filters" }).click();
  await expect(page.getByLabel("Search Pain Points")).toBeHidden();
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await expect(page.getByLabel("Search Pain Points")).toBeVisible();

  // The panel is left as it was when the view changes, in both states.
  await page.getByRole("button", { name: "Grid view" }).click();
  const grid = page.getByRole("table", { name: "Pain points grid" });
  await expect(grid).toBeVisible();
  await expect(page.getByLabel("Search Pain Points")).toBeVisible();
  await page.getByRole("button", { name: "Collapse filters" }).click();
  await page.getByRole("button", { name: "List view" }).click();
  await expect(page.getByLabel("Search Pain Points")).toBeHidden();
  await page.getByRole("button", { name: "Grid view" }).click();
  await expect(page.getByLabel("Search Pain Points")).toBeHidden();
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await expect(page.getByLabel("Search Pain Points")).toBeVisible();

  // Columns, Discard and Save share the view toggle's row, before it.
  const box = async (name: string) => (await page.getByRole("button", { name, exact: true }).boundingBox())!;
  const [columnsBox, discardBox, saveBox, listBox, gridBox] = [await box("Columns"), await box("Discard changes"), await box("Save changes"), await box("List view"), await box("Grid view")];
  expect(columnsBox.x).toBeLessThan(discardBox.x);
  expect(discardBox.x).toBeLessThan(saveBox.x);
  expect(saveBox.x).toBeLessThan(listBox.x);
  expect(listBox.x).toBeLessThan(gridBox.x);
  expect(Math.abs(columnsBox.y - listBox.y)).toBeLessThanOrEqual(8);

  await page.getByRole("button", { name: "Columns" }).click();
  await page.getByRole("checkbox", { name: "Show Frequency" }).uncheck();
  await page.getByRole("checkbox", { name: "Show Source" }).check();
  await page.keyboard.press("Escape");
  await expect(grid.getByRole("columnheader", { name: "Frequency" })).toHaveCount(0);
  await expect(grid.getByRole("columnheader", { name: "Source" })).toBeVisible();
  await expect(grid.getByRole("combobox", { name: `Severity for ${a.unique_code}` })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("table", { name: "Pain points grid" }).getByRole("columnheader", { name: "Frequency" })).toHaveCount(0);
});
