import { expect, type Page } from "@playwright/test";

import { API_BASE_URL, setUpOrg as setUpModuleOrg, statusBadge } from "../stakeholders/helpers";

export { API_BASE_URL, statusBadge };

/**
 * Shared setup for the Risk Management specs: a disposable org + admin + project
 * with the (default-off) Risk Management module switched on, built through the
 * API per this repo's "tests must not depend on shared seeded state" rule. The
 * org admin is the project's `PROJECT_MANAGER`, which composes with the module's
 * project-scoped roles, so it can create, edit, transition and review risks.
 */
export async function setUpOrg(page: Page, label: string) {
  return setUpModuleOrg(page, label, false, "Risk Management");
}

/** The ids of the five default Likelihood and Consequence levels of the project's `risk` scheme, by name. */
export async function riskLevels(page: Page, projectId: string, headers: Record<string, string>) {
  const scheme = await (await page.request.get(`${API_BASE_URL}/api/v1/projects/${projectId}/scoring-schemes/risk`, { headers })).json();
  const level = (axis: string, name: string): string => {
    const found = scheme.axes.find((a: { key: string }) => a.key === axis)?.levels.find((l: { name: string }) => l.name === name);
    expect(found, `${axis} level ${name}`).toBeTruthy();
    return found.id;
  };
  return { level };
}

/** Creates a risk through the API and returns it. */
export async function createRisk(
  page: Page, projectId: string, headers: Record<string, string>, data: Record<string, unknown>,
) {
  const resp = await page.request.post(`${API_BASE_URL}/api/v1/projects/${projectId}/modules/risk_management/risks`, { headers, data });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  return resp.json();
}
