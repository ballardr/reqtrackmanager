import { expect, type Page } from "@playwright/test";

import { API_BASE_URL, setUpOrg as setUpModuleOrg } from "../stakeholders/helpers";

export { API_BASE_URL };

/**
 * Shared setup for the Product Feedback specs: a disposable org + admin + project with the (default-off) Product
 * Feedback module switched on, built through the API per this repo's "tests must not depend on shared seeded state"
 * rule. The org admin is the project's manager and the organisation's admin, which compose with the module's
 * triager roles, so it can submit, triage, merge and move requests.
 */
export async function setUpOrg(page: Page, label: string) {
  return setUpModuleOrg(page, label, false, "Product Feedback");
}

/** Enables Context & Strategy (which holds the Pain Points) for the organisation, so a request can address one. */
export async function enablePainPoints(page: Page, orgId: string, headers: Record<string, string>) {
  const resp = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${orgId}/modules/context_strategy`, { headers, data: { enabled: true } });
  expect(resp.ok(), await resp.text()).toBeTruthy();
}

export const projectBase = (projectId: string) => `${API_BASE_URL}/api/v1/projects/${projectId}/modules/product_feedback`;
export const orgBase = (orgId: string) => `${API_BASE_URL}/api/v1/orgs/${orgId}/modules/product_feedback`;

/** Submits a request through the API (a project's, or the organisation's inbox when `base` is `orgBase`). */
export async function createRequest(
  page: Page, base: string, headers: Record<string, string>, data: Record<string, unknown>,
) {
  const resp = await page.request.post(`${base}/requests`, { headers, data });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  return resp.json();
}

/** The id of a named level of the organisation's `enhancement_request` scheme axis, as `levels` takes it. */
export async function requestLevels(page: Page, projectId: string, headers: Record<string, string>) {
  const scheme = await (
    await page.request.get(`${API_BASE_URL}/api/v1/projects/${projectId}/scoring-schemes/enhancement_request`, { headers })
  ).json();
  const level = (axis: string, name: string): string => {
    const found = scheme.axes.find((a: { key: string }) => a.key === axis)?.levels.find((l: { name: string }) => l.name === name);
    expect(found, `${axis} level ${name}`).toBeTruthy();
    return found.id;
  };
  return { level, scheme };
}
