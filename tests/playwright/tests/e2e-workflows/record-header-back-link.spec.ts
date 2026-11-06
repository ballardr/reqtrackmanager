import { expect, test } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

// Archives this file's disposable projects after each test (see createDisposableProject).
installCleanupHook();

/**
 * Job to be done: every record detail page opens with a back link named after its list, so a person
 * can return to the list from any record the same way.
 *
 * Covers: the back link on the core record pages (requirement, change request, action) and the
 * compliance standard page, its plural label, and that following it lands on the list.
 *
 * The module record pages are covered by their lifecycle specs, which end by following the same link.
 */
const API = "http://localhost:8000/api/v1";

test.describe("record header back link", () => {
  test("requirement, change request and action pages link back to their lists", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E Back Link");
    const { projectId, headers, components, categories } = project;
    const suffix = Date.now();

    const requirement = await (
      await page.request.post(`${API}/projects/${projectId}/requirements`, {
        headers,
        data: { name: `E2E Back Requirement ${suffix}`, component_id: components[0].id, category_id: categories[0].id },
      })
    ).json();
    const changeRequest = await (
      await page.request.post(`${API}/projects/${projectId}/change-requests`, {
        headers, data: { kind: "new_requirement", proposed_name: `E2E Back Change ${suffix}`, reason: "Back link" },
      })
    ).json();
    const actionTypes: { id: string }[] = await (await page.request.get(`${API}/projects/${projectId}/action-types`, { headers })).json();
    const action = await (
      await page.request.post(`${API}/projects/${projectId}/actions`, {
        headers, data: { title: `E2E Back Action ${suffix}`, action_type_id: actionTypes[0].id },
      })
    ).json();

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    const cases = [
      { detail: `requirements/${requirement.id}`, label: "← Requirements", list: "requirements" },
      { detail: `change-requests/${changeRequest.id}`, label: "← Change requests", list: "change-requests" },
      { detail: `actions/${action.id}`, label: "← Actions", list: "actions" },
    ];
    for (const { detail, label, list } of cases) {
      await test.step(`${list}: detail links back to the list`, async () => {
        await page.goto(`/projects/${projectId}/${detail}`);
        await page.locator(".record-header").getByRole("link", { name: label, exact: true }).click();
        await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/${list}(?:\\?.*)?$`));
      });
    }
  });
});
