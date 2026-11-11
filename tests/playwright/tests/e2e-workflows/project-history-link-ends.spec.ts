import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

// Archives this file's disposable projects after each test (see createDisposableProject).
installCleanupHook();

/**
 * Job to be done: read the project History page and see which two records a link event joined (in the Record column) and by which
 * relationship (in the Event column), instead of a Link row with an empty Record column; each record opens from the row.
 *
 * Each test builds its own project, so none depends on state left by another test or an earlier run.
 */

const api = "http://localhost:8000/api/v1";

test("a created and a removed link each name both records and the relationship", async ({ page }) => {
  const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E link history");
  const suffix = Date.now();
  const names = [`Link source ${suffix}`, `Link target ${suffix}`];
  const ids: string[] = [];
  for (const name of names) {
    const created = await page.request.post(`${api}/projects/${project.projectId}/requirements`, {
      headers: project.headers,
      data: { name, component_id: project.components[0].id, category_id: project.categories[0].id },
    });
    expect(created.ok()).toBeTruthy();
    ids.push((await created.json()).id);
  }
  const linkTypes: { id: string; forward_name: string }[] = await (
    await page.request.get(`${api}/orgs/${project.organizationId}/link-types`, { headers: project.headers })
  ).json();
  const related = linkTypes.find((type) => type.forward_name === "Related to")!;
  const link = await page.request.post(`${api}/projects/${project.projectId}/artefacts/requirement/${ids[0]}/links`, {
    headers: project.headers,
    data: { link_type_id: related.id, direction: "outgoing", other_type: "requirement", other_id: ids[1] },
  });
  expect(link.ok()).toBeTruthy();
  const removed = await page.request.delete(
    `${api}/projects/${project.projectId}/artefacts/requirement/${ids[0]}/links/${(await link.json()).id}`, { headers: project.headers },
  );
  expect(removed.ok()).toBeTruthy();

  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
  await page.goto(`/projects/${project.projectId}/history?type=artefact_link`);
  const table = page.getByRole("table", { name: "Project history" });
  const created = table.getByRole("row").filter({ hasText: "created a link" });
  const deleted = table.getByRole("row").filter({ hasText: "removed a link" });

  await test.step("each link event names the relationship in Event and both records in Record, source first", async () => {
    for (const row of [created, deleted]) {
      await expect(row.getByRole("cell").nth(2)).toContainText("(Related to)");
      const records = row.getByRole("cell").nth(3);
      await expect(records).toContainText(names[0]);
      await expect(records).toContainText(names[1]);
      expect((await records.innerText()).indexOf(names[0])).toBeLessThan((await records.innerText()).indexOf(names[1]));
    }
  });

  await test.step("each record opens from the row", async () => {
    await expect(created.getByRole("link", { name: new RegExp(names[0]) })).toHaveAttribute("href", `/projects/${project.projectId}/requirements/${ids[0]}`);
    await expect(created.getByRole("link", { name: new RegExp(names[1]) })).toHaveAttribute("href", `/projects/${project.projectId}/requirements/${ids[1]}`);
  });
});
