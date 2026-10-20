import { expect, test, type Page } from "@playwright/test";

import {
  apiHeaders, createDisposableProject, installCleanupHook, loginAs, onCleanup, PERSONAS, selectPreferencesGroup,
  type DisposableProject,
} from "./helpers";

// Archives each disposable project, and resets preferences a test changed, after the test.
installCleanupHook();

/**
 * Job to be done: find a record without knowing which project or module page it lives on. The header box
 * searches the narrowest scope that matches the page (no scope control in the box), a live dropdown shows
 * the top results without flickering, and the search page carries the text, scope, filters and the fields
 * searched in its URL.
 *
 * Covers: header box and Enter, the default scope by page, ID/Title/Tags as the default fields (a record
 * matched only by its description is found once Description is added in Preferences), a tag found by
 * default, the dropdown keeping its previous results while the next request runs, a viewer never
 * seeing a project they cannot open, and the Organisation filter only for a viewer in two organisations.
 *
 * Builds its own project and records through the API with run-unique words, so it depends on no shared fixture.
 */

const api = "http://localhost:8000/api/v1";

/** A word no other run or seed can contain. */
const unique = (prefix: string) => `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

async function createRequirement(
  project: DisposableProject, request: Parameters<typeof createDisposableProject>[0], name: string, extra: object = {},
): Promise<{ id: string; unique_code: string }> {
  const owner = await (await request.get(`${api}/auth/me`, { headers: project.headers })).json();
  const resp = await request.post(`${api}/projects/${project.projectId}/requirements`, {
    headers: project.headers,
    data: {
      name, reasoning: "e2e", component_id: project.components[0].id, category_id: project.categories[0].id, keywords: [],
      owner: { type: "user", id: owner.id }, ...extra,
    },
  });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  return resp.json();
}

const box = (page: Page) => page.getByRole("combobox", { name: "Search" });

/**
 * How long a search page may take to show its first results. A search authorises every project the person
 * can open, and these specs use a seeded persona with hundreds of projects while several workers log in and
 * list projects at once, so a search legitimately takes a few seconds here; the default 5s is for a quiet stack.
 */
const FIRST_RESULTS = { timeout: 20_000 };

test.describe("global search", () => {
  test("the header box finds a record by its title and opens it; the box has no scope control", async ({ page, request }) => {
    const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Search Title");
    const word = unique("zephyr");
    const requirement = await createRequirement(project, request, `Gust ${word} tolerance`);

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}/requirements`);
    await box(page).fill(word);
    const listbox = page.getByRole("listbox", { name: "Search results" });
    // The result sits in its record-type group; the footer option also names the text, so scope to the group.
    const result = listbox.getByRole("group", { name: "Requirement" }).getByRole("option", { name: new RegExp(word) });
    await expect(result).toBeVisible();
    // Inside a project the box searches that project, and names it only in the footer.
    await expect(listbox.getByText(`See all results for ‘${word}’ in This project`)).toBeVisible();
    await expect(page.getByRole("banner").getByRole("combobox", { name: /scope/i })).toHaveCount(0);

    await result.click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.projectId}/requirements/${requirement.id}$`));
  });

  test("Enter opens the search page with the text and scope in the URL, and the Scope filter widens it", async ({ page, request }) => {
    const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Search Page");
    const word = unique("quasar");
    await createRequirement(project, request, `Orbit ${word} budget`);

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}`);
    await box(page).fill(word);
    await box(page).press("Enter");
    await expect(page).toHaveURL(new RegExp(`/search\\?q=${word}&scope=project&project=${project.projectId}`));
    await expect(page.getByRole("heading", { name: `Results for ‘${word}’` })).toBeVisible();
    await expect(page.getByRole("link", { name: new RegExp(word) })).toBeVisible(FIRST_RESULTS);
    // The header box keeps the page's text.
    await expect(box(page)).toHaveValue(word);

    const scope = page.getByRole("combobox", { name: "Scope" });
    await expect(scope.locator("option")).toHaveText(["This project", "All projects"]);
    await scope.selectOption({ label: "All projects" });
    await expect(page).toHaveURL(new RegExp(`/search\\?q=${word}$`));
    await expect(page.getByRole("link", { name: new RegExp(word) })).toBeVisible(FIRST_RESULTS);
  });

  test("a description match is not found by default, and is once Description is added in Preferences", async ({ page, request }) => {
    const email = PERSONAS.orgAdminAlphaBeta.email;
    onCleanup(async (cleanup) => {
      await cleanup.patch(`${api}/auth/me/preferences`, {
        headers: await apiHeaders(cleanup, email), data: { ui_preferences: { search_default_fields: null } },
      });
    });
    const project = await createDisposableProject(request, email, "E2E Search Fields");
    const word = unique("nimbus");
    await createRequirement(project, request, "Plain name", { description: `mentions ${word} somewhere` });

    await loginAs(page, email);
    await page.goto(`/search?q=${word}`);
    await expect(page.getByText("Nothing found")).toBeVisible(FIRST_RESULTS);

    await page.goto("/preferences");
    await selectPreferencesGroup(page, "Search");
    await page.getByRole("button", { name: "Fields searched", exact: true }).click();
    await page.getByRole("group", { name: "Fields searched" }).getByRole("checkbox", { name: "Description" }).check();
    await page.keyboard.press("Escape");
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
      page.getByRole("button", { name: "Save preferences" }).click(),
    ]);

    await page.goto(`/search?q=${word}`);
    const hit = page.getByRole("link", { name: /Plain name/ });
    await expect(hit).toBeVisible(FIRST_RESULTS);
    await expect(hit.getByText("Description:")).toBeVisible();
  });

  test("a record matched only by a tag is found by default", async ({ page, request }) => {
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(request, email, "E2E Search Tags");
    const tag = unique("regulation");
    const requirement = await createRequirement(project, request, "Tagged without the word");
    const tagged = await request.post(`${api}/projects/${project.projectId}/artefacts/requirement/${requirement.id}/tags`, {
      headers: project.headers, data: { name: tag },
    });
    expect(tagged.ok(), await tagged.text()).toBeTruthy();

    await loginAs(page, email);
    await page.goto(`/search?q=${tag}`);
    const hit = page.getByRole("link", { name: /Tagged without the word/ });
    await expect(hit).toBeVisible(FIRST_RESULTS);
    await expect(hit.getByText("Tags:")).toBeVisible();
  });

  test("comments are searched only when chosen, never by default", async ({ page, request }) => {
    const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Search Comments");
    const word = unique("discussed");
    const requirement = await createRequirement(project, request, "Plain commented requirement");
    const comment = await request.post(`${api}/projects/${project.projectId}/requirements/${requirement.id}/comments`, {
      headers: project.headers, data: { body: `The reviewer raised ${word} in passing` },
    });
    expect(comment.ok(), await comment.text()).toBeTruthy();

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/search?q=${word}`);
    await expect(page.getByText("Nothing found")).toBeVisible(FIRST_RESULTS);

    await page.goto(`/search?q=${word}&fields=id%2Ctitle%2Ccomments`);
    const hit = page.getByRole("link", { name: /Plain commented requirement/ });
    await expect(hit).toBeVisible(FIRST_RESULTS);
    await expect(hit.getByText("Comments:")).toBeVisible();

    // Preferences never offer it as a saved default.
    await page.goto("/preferences");
    await selectPreferencesGroup(page, "Search");
    await page.getByRole("button", { name: "Fields searched", exact: true }).click();
    await expect(page.getByRole("group", { name: "Fields searched" }).getByRole("checkbox", { name: "Description" })).toBeVisible();
    await expect(page.getByRole("group", { name: "Fields searched" }).getByRole("checkbox", { name: "Comments" })).toHaveCount(0);
  });

  test("the dropdown keeps its previous results while the next request runs", async ({ page, request }) => {
    const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Search Flicker");
    const word = unique("cirrus");
    await createRequirement(project, request, `Cloud ${word} deck`);

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}`);
    let calls = 0;
    await page.route("**/api/v1/search", async (route) => {
      calls += 1;
      if (calls > 1) await new Promise((resolve) => setTimeout(resolve, 1200));
      await route.continue();
    });
    await box(page).fill(word);
    const option = page.getByRole("group", { name: "Requirement" }).getByRole("option", { name: new RegExp(word) });
    await expect(option).toBeVisible();
    // One more character: the old result stays visible, and "No results" is never shown, while the slow request is in flight.
    await box(page).press("End");
    await box(page).pressSequentially("x");
    await page.waitForTimeout(700);
    await expect(option).toBeVisible();
    await expect(page.getByText("No results")).toHaveCount(0);
    await expect(page.getByText("No results")).toBeVisible({ timeout: 5000 });
  });

  test("a viewer without a role never finds a project's records", async ({ page, request }) => {
    const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Search Isolation");
    const word = unique("hidden");
    await createRequirement(project, request, `Secret ${word} plan`);

    // Alpha's stakeholder has no role in this project (a disposable project's creator is its only member).
    await loginAs(page, PERSONAS.stakeholderAlpha.email);
    await page.goto(`/search?q=${word}&scope=all`);
    await expect(page.getByText("Nothing found")).toBeVisible(FIRST_RESULTS);
    // Naming the project directly answers like a project that does not exist.
    await page.goto(`/search?q=${word}&scope=project&project=${project.projectId}`);
    await expect(page.getByRole("alert")).toHaveText("Search scope not found.");
  });

  test("the Organisation filter shows only for a viewer in more than one organisation", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto("/search?q=alpha");
    await expect(page.getByRole("combobox", { name: "Organisation" })).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).click();
    await loginAs(page, PERSONAS.stakeholderAlpha.email);
    await page.goto("/search?q=alpha");
    await expect(page.getByRole("heading", { name: "Results for ‘alpha’" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Organisation" })).toHaveCount(0);
  });
});
