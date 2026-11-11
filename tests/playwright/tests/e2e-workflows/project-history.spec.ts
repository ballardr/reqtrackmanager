import { expect, test, type Page } from "@playwright/test";

import { createDisposableProject, installCleanupHook, loginAs, openProject, openRequirementByCode, PERSONAS, PROJECT_NAMES } from "./helpers";

installCleanupHook();

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a unified, filterable timeline of a project's changes over time (C-A-10) — a table of what
 * happened (Time, Type, Event, Record, Person) narrowed by period, type (records by module, then metadata), change and person or group, with
 * discussion comments excluded by default; every filter lives in the URL so Back and a reload restore the view.
 */

/** Ticks (or clears) types or groups in the Type filter's list, then closes it. */
async function chooseTypes(page: Page, names: string[], checked = true): Promise<void> {
  await page.getByRole("button", { name: "Type", exact: true }).click();
  for (const name of names) {
    const box = page.getByRole("group", { name: "Type", exact: true }).getByRole("checkbox", { name, exact: true });
    if (checked) await box.check();
    else await box.uncheck();
  }
  await page.keyboard.press("Escape");
}

/** The project's history page, opened through the navigation rail, with its project id. */
async function openHistory(page: Page): Promise<string> {
  await page.getByRole("link", { name: "Project history", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Project history", exact: true })).toBeVisible();
  const match = /\/projects\/([0-9a-f-]+)\/history/.exec(page.url());
  expect(match).not.toBeNull();
  return match![1];
}

test.describe("project history / changes-over-time view", () => {
  test("filters by type, kind of event and period, keeps the filters in the URL and links to the record", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);

    await test.step("post a comment first, so there is something for the include-comments filter to reveal", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByCode(page, "HW-FN-001");
      await page.getByPlaceholder("Add comment").fill("E2E: project-history spec comment marker.");
      await page.getByRole("button", { name: "Add comment", exact: true }).click();
    });

    await test.step("the history table lists activity by default, with comments excluded", async () => {
      await openHistory(page);
      const table = page.getByRole("table", { name: "Project history" });
      await expect(table).toBeVisible();
      for (const heading of ["Time", "Type", "Event", "Record", "Person"]) {
        await expect(table.getByRole("columnheader", { name: new RegExp(`^${heading}`) })).toBeVisible();
      }
      await expect(page.getByText("E2E: project-history spec comment marker.")).toHaveCount(0);
    });

    await test.step("a row links back to the requirement it is about", async () => {
      await chooseTypes(page, ["Requirement"]);
      const requirementLink = page.getByRole("table", { name: "Project history" }).getByRole("link").first();
      await expect(requirementLink).toBeVisible();
      await expect(requirementLink).toHaveAttribute("href", /\/requirements\//);
      await expect(page).toHaveURL(/[?&]type=requirement/);
    });

    await test.step("the Change filter narrows to status changes and survives a reload", async () => {
      await page.getByRole("button", { name: "Change", exact: true }).click();
      await page.getByRole("checkbox", { name: "Status changes" }).check();
      await expect(page).toHaveURL(/[?&]kind=status/);
      await page.keyboard.press("Escape");
      await page.reload();
      await expect(page.getByRole("button", { name: "Type", exact: true })).toContainText("Requirement");
      await expect(page.getByRole("button", { name: "Change", exact: true })).toContainText("Status changes");
    });

    await test.step("going back from a record restores the filters", async () => {
      const link = page.getByRole("table", { name: "Project history" }).getByRole("link").first();
      if (await link.count()) {
        await link.click();
        await page.goBack();
        await expect(page).toHaveURL(/[?&]kind=status/);
        await expect(page.getByRole("button", { name: "Type", exact: true })).toContainText("Requirement");
      }
    });

    await test.step("clearing the filters empties the URL's filters", async () => {
      await chooseTypes(page, ["Requirement"], false);
      await page.getByRole("button", { name: "Change", exact: true }).click();
      await page.getByRole("checkbox", { name: "Status changes" }).uncheck();
      await page.keyboard.press("Escape");
      await expect(page).not.toHaveURL(/[?&]kind=/);
    });

    await test.step("including comments reveals the comment event", async () => {
      await page.getByLabel("Include discussion comments").check();
      await expect(page).toHaveURL(/[?&]comments=1|[?&]comments=true/);
      await expect(page.getByText(/commented on/i).first()).toBeVisible();
      await page.getByLabel("Include discussion comments").uncheck();
    });

    await test.step("a future custom period shows no events and offers Clear filters", async () => {
      const future = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000);
      await page.getByLabel("Period", { exact: true }).selectOption("custom");
      // A native `datetime-local` input can dispatch intermediate input events while it fills, each of which
      // loads; `toPass` retries until the final, correct request has landed.
      await page.getByLabel("From", { exact: true }).fill(future.toISOString().slice(0, 16));
      await expect(async () => {
        await expect(page.getByText("No events match these filters.")).toBeVisible();
      }).toPass();
      await page.getByRole("button", { name: "Clear filters" }).click();
      await expect(page.getByRole("table", { name: "Project history" })).toBeVisible();
    });

    await test.step("sorting by Time asks for the oldest events first", async () => {
      const [request] = await Promise.all([
        page.waitForRequest((r) => r.url().includes("/changes?") && r.url().includes("order=oldest")),
        page.getByRole("button", { name: /^Time/ }).click(),
      ]);
      expect(request.url()).toContain("order=oldest");
    });
  });

  test("the List actions menu downloads the filtered history as CSV", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await openHistory(page);
    await chooseTypes(page, ["Requirement"]);
    await page.getByRole("button", { name: "List actions" }).click();
    await page.getByRole("menuitem", { name: "Download shown items" }).click();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("menuitem", { name: /CSV/ }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
  });
});

test.describe("project history / metadata separated from records", () => {
  test("a created link is filed under Metadata, not Created, and Event cells start with a capital", async ({ page }) => {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, "E2E history metadata");
    const suffix = Date.now();
    const ids: string[] = [];
    for (const name of [`Meta source ${suffix}`, `Meta target ${suffix}`]) {
      const created = await page.request.post(`${API}/projects/${project.projectId}/requirements`, {
        headers: project.headers,
        data: { name, component_id: project.components[0].id, category_id: project.categories[0].id },
      });
      expect(created.ok()).toBeTruthy();
      ids.push((await created.json()).id);
    }
    const linkTypes: { id: string; forward_name: string }[] = await (
      await page.request.get(`${API}/orgs/${project.organizationId}/link-types`, { headers: project.headers })
    ).json();
    const link = await page.request.post(`${API}/projects/${project.projectId}/artefacts/requirement/${ids[0]}/links`, {
      headers: project.headers,
      data: { link_type_id: linkTypes.find((type) => type.forward_name === "Related to")!.id, direction: "outgoing", other_type: "requirement", other_id: ids[1] },
    });
    expect(link.ok()).toBeTruthy();

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.goto(`/projects/${project.projectId}/history`);
    const table = page.getByRole("table", { name: "Project history" });
    const linkRow = table.getByRole("row").filter({ hasText: "Created a link" });

    await test.step("every Event cell starts with a capital letter", async () => {
      await expect(linkRow).toBeVisible();
      for (const cell of await table.locator("tbody tr td:nth-child(3) > span > span:first-child").all()) {
        expect(await cell.innerText()).toMatch(/^[\p{Lu}\p{N}]/u);
      }
    });

    await test.step("Change: Created does not include the link", async () => {
      await page.getByRole("button", { name: "Change", exact: true }).click();
      await page.getByRole("checkbox", { name: "Created", exact: true }).check();
      await page.keyboard.press("Escape");
      await expect(page).toHaveURL(/[?&]kind=created/);
      await expect(table.getByRole("row").filter({ hasText: "Created a link" })).toHaveCount(0);
      await page.getByRole("button", { name: "Change", exact: true }).click();
      await page.getByRole("checkbox", { name: "Created", exact: true }).uncheck();
      await page.keyboard.press("Escape");
    });

    await test.step("the Metadata group Links and files finds the link, and survives a reload", async () => {
      await chooseTypes(page, ["Links and files"]);
      await expect(page).toHaveURL(/[?&]group=metadata%3Alinks/);
      await expect(linkRow).toBeVisible();
      await expect(table.getByRole("row").filter({ hasText: "Requirement" }).filter({ hasNotText: "Created a link" })).toHaveCount(0);
      await page.reload();
      await expect(page.getByRole("button", { name: "Type", exact: true })).toContainText("Links and files");
      await expect(linkRow).toBeVisible();
    });
  });
});

/**
 * The period is the person's own wall-clock time, converted to UTC instants in the browser. Each case runs in a
 * browser whose time zone is fixed, so the instants sent to the server are exact: 09:00 at UTC+11 (Sydney in
 * summer), 23:00 at UTC-8 (Los Angeles in winter), and the same 09:00 a week either side of Sydney's daylight
 * saving change (5 April 2026), which differ by an hour in UTC.
 */
const BOUNDARY_CASES: { zone: string; since: string; until: string; sinceUtc: string; untilUtc: string }[] = [
  { zone: "Australia/Sydney", since: "2026-01-15T09:00", until: "2026-01-15T17:00", sinceUtc: "2026-01-14T22:00:00.000Z", untilUtc: "2026-01-15T06:00:59.999Z" },
  { zone: "America/Los_Angeles", since: "2026-01-15T23:00", until: "2026-01-15T23:30", sinceUtc: "2026-01-16T07:00:00.000Z", untilUtc: "2026-01-16T07:30:59.999Z" },
  { zone: "Australia/Sydney", since: "2026-03-29T09:00", until: "2026-03-29T09:30", sinceUtc: "2026-03-28T22:00:00.000Z", untilUtc: "2026-03-28T22:30:59.999Z" },
  { zone: "Australia/Sydney", since: "2026-04-12T09:00", until: "2026-04-12T09:30", sinceUtc: "2026-04-11T23:00:00.000Z", untilUtc: "2026-04-11T23:30:59.999Z" },
];

for (const { zone, since, until, sinceUtc, untilUtc } of BOUNDARY_CASES) {
  test.describe(`history period in ${zone}`, () => {
    test.use({ timezoneId: zone });

    test(`${since} to ${until} is sent as ${sinceUtc} to ${untilUtc}`, async ({ page }) => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await openProject(page, PROJECT_NAMES.alpha1);
      await openHistory(page);
      await page.getByLabel("Period", { exact: true }).selectOption("custom");
      await page.getByLabel("From", { exact: true }).fill(since);
      const request = await (async () => {
        const [req] = await Promise.all([
          page.waitForRequest((r) => r.url().includes("/changes?") && r.url().includes(encodeURIComponent(sinceUtc)) && r.url().includes("until")),
          page.getByLabel("To", { exact: true }).fill(until),
        ]);
        return req;
      })();
      const params = new URL(request.url()).searchParams;
      expect(params.get("since")).toBe(sinceUtc);
      expect(params.get("until")).toBe(untilUtc);
    });
  });
}
