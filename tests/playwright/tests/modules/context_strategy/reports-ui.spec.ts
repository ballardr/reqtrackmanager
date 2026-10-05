import { readFile } from "node:fs/promises";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, logout, PASSWORD } from "../../e2e-workflows/helpers";

const API_BASE_URL = "http://localhost:8000";
const CS = "context_strategy";

/**
 * Job to be done: docs/plans/module-01-context-and-strategy-plan.md Phase 13
 * — the shared Reports UI over the core report catalogue. Covers the project
 * Reports page (catalogue reports beside the requirement report), the R1 and
 * R4 custom views, PDF/CSV downloads (every catalogue report, plus branding
 * template pass-through), the Organisation Overview "Reports" group and its
 * org-role gate, and that a module- or sub-component-disabled project shows
 * no entry.
 *
 * Everything is created through the API in a disposable, `Date.now()`-suffixed
 * org (CLAUDE.md's test-independence rule) and deleted afterwards.
 */
installCleanupHook();

async function api(request: APIRequestContext, email: string, password = PASSWORD) {
  const login = await request.post(`${API_BASE_URL}/api/v1/auth/login`, { data: { email, password } });
  return { Authorization: `Bearer ${(await login.json()).access_token}` };
}

/**
 * A disposable org (Context & Strategy on) with an org admin, a project, two
 * scored open Pain Points (one a Blocker) and one overdue, unowned Open
 * Question. Leaves the page logged in as the org admin.
 */
async function setup(page: Page, request: APIRequestContext) {
  const suffix = Date.now();
  const adminEmail = `e2e-reports-ui-${suffix}@example.com`;
  const serverHeaders = await api(request, "admin@example.com", "ChangeMe123!");
  const org = await (await request.post(`${API_BASE_URL}/api/v1/orgs`, {
    headers: serverHeaders, data: { name: `E2E Reports UI ${suffix}` },
  })).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Reports Admin", password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
  const headers = await api(request, adminEmail);
  const enable = await request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/${CS}`, {
    headers, data: { enabled: true, default_project_enabled: true },
  });
  expect(enable.ok(), await enable.text()).toBeTruthy();
  const project = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
    headers, data: { organization_id: org.id, name: `Reports UI Project ${suffix}`, summary: "" },
  })).json();
  const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/${CS}`;

  const scheme = await (await request.get(`${API_BASE_URL}/api/v1/projects/${project.id}/scoring-schemes/pain_point`, { headers })).json();
  const level = (axis: string, name: string): string =>
    scheme.axes.find((a: { key: string }) => a.key === axis).levels.find((l: { name: string }) => l.name === name).id;
  const types = await (await request.get(`${base}/pain-point-types`, { headers })).json();

  const titles = { major: `Major constant ${suffix}`, blocker: `Blocker rare ${suffix}` };
  const scores: Record<keyof typeof titles, [string, string]> = { major: ["Major", "Constant"], blocker: ["Blocker", "Rare"] };
  for (const key of Object.keys(titles) as (keyof typeof titles)[]) {
    const created = await request.post(`${base}/pain-points`, { headers, data: { pain_point_type_id: types[0].id, title: titles[key] } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const scored = await request.put(`${base}/pain-points/${(await created.json()).id}/scores`, {
      headers,
      data: { scores: [{ target_id: null, severity_level_id: level("severity", scores[key][0]), frequency_level_id: level("frequency", scores[key][1]), confidence_level_id: level("confidence", "High") }] },
    });
    expect(scored.ok(), await scored.text()).toBeTruthy();
  }
  const question = `Which regions are in scope ${suffix}?`;
  const oq = await request.post(`${base}/open-questions`, {
    headers, data: { question, priority: "high", due_date: "2026-01-15" },
  });
  expect(oq.ok(), await oq.text()).toBeTruthy();
  return { org, project, headers, titles, question, suffix };
}

/** The "Report" picker on the Reports surfaces. */
function picker(page: Page) {
  return page.getByRole("combobox", { name: "Report", exact: true });
}

test.describe("Context & Strategy: Reports UI", () => {
  test("the project Reports page offers catalogue reports beside the requirement report", async ({ page, request }) => {
    const { project } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports`);

    await expect(picker(page)).toHaveValue("requirements");
    await expect(page.getByRole("button", { name: "Generate PDF" })).toBeVisible();
    const options = await picker(page).locator("option").allTextContents();
    expect(options[0]).toBe("Requirements report");
    expect(options).toEqual(expect.arrayContaining(["Pain Point prioritisation", "Open Question register", "Strategy cascade and alignment"]));

    // The selection is the URL, so a report is linkable and survives a reload.
    await picker(page).selectOption({ label: "Open Question register" });
    await expect(page).toHaveURL(/report=open-question-register/);
    await page.reload();
    await expect(picker(page)).toHaveValue("open-question-register");
  });

  test("R1 shows the matrix, ranked list and Blocker, and switches model and roll-up", async ({ page, request }) => {
    const { project, titles } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports?report=pain-point-prioritisation`);

    const ranked = page.getByRole("table", { name: "Ranked Pain Points" });
    await expect(ranked).toBeVisible();
    await expect(ranked.locator("tbody tr")).toHaveCount(2);
    await expect(ranked.locator("tbody tr").nth(0)).toContainText(titles.major);
    await expect(ranked.locator("tbody tr").nth(1)).toContainText(titles.blocker);
    await expect(ranked.locator("tbody tr").nth(1).getByText("Blocker", { exact: true })).toBeVisible();

    // Each Pain Point sits in its worst persona's cell of the shared matrix.
    await expect(page.getByLabel(/Severity Major, Frequency Constant: .*1 item/)).toBeVisible();
    await expect(page.getByLabel(/Severity Blocker, Frequency Rare: .*1 item/)).toBeVisible();

    // The view owns model and roll-up, so the generic form does not offer them twice.
    await expect(page.getByRole("combobox", { name: "Scoring model" })).toHaveCount(1);
    await expect(page.getByRole("combobox", { name: "Rollup" })).toHaveCount(0);

    const modelRequest = page.waitForRequest((r) => r.url().includes("pain-point-prioritisation") && r.url().includes("model_key=sxf"));
    await page.getByRole("combobox", { name: "Scoring model" }).selectOption({ label: "Severity × Frequency" });
    await modelRequest;
    await expect(page.getByRole("heading", { name: "Severity × Frequency", exact: true })).toBeVisible();

    const rollupRequest = page.waitForRequest((r) => r.url().includes("pain-point-prioritisation") && r.url().includes("rollup=worst_case"));
    await page.getByRole("combobox", { name: "Combine personas by" }).selectOption({ label: "Worst case" });
    await rollupRequest;
    await expect(ranked.locator("tbody tr").getByText("Blocker", { exact: true })).toBeVisible(); // survives every roll-up
  });

  test("R4 highlights the overdue, unowned question in one table", async ({ page, request }) => {
    const { project, question } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports?report=open-question-register`);

    const row = page.getByRole("row", { name: new RegExp(question.replace("?", "\\?")) });
    await expect(row).toBeVisible();
    await expect(row.getByText("Overdue", { exact: true })).toBeVisible();
    await expect(row.getByText("Unowned", { exact: true })).toBeVisible();
    await expect(row.getByText("High", { exact: true })).toBeVisible();
  });

  test("a generic report renders from its sections with no custom view", async ({ page, request }) => {
    const { project } = await setup(page, request);
    await page.goto(`/projects/${project.id}/reports?report=pain-point-coverage`);
    await expect(page.getByRole("region", { name: "Type × status" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Accepted Pain Points with no Requirement" })).toBeVisible();
  });

  test("every catalogue report downloads as PDF and CSV, and a branding template passes through", async ({ page, request }) => {
    const { project, org, headers, titles } = await setup(page, request);
    const template = await (await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/report-templates`, {
      headers, data: { name: "E2E Reports Branding", accent_color_hex: "#112233" },
    })).json();
    await page.goto(`/projects/${project.id}/reports`);
    await expect(picker(page)).toBeVisible();

    const reports = (await picker(page).locator("option").evaluateAll((els) =>
      els.map((e) => ({ value: (e as HTMLOptionElement).value, label: e.textContent ?? "" })),
    )).filter((o) => o.value !== "requirements");
    expect(reports.length).toBeGreaterThanOrEqual(7);

    for (const report of reports) {
      await test.step(`${report.label}: PDF and CSV`, async () => {
        await picker(page).selectOption(report.value);
        await expect(page.getByRole("button", { name: "Export" })).toBeVisible();
        for (const kind of ["PDF", "CSV"] as const) {
          await page.getByRole("button", { name: "Export" }).click();
          const [download] = await Promise.all([
            page.waitForEvent("download"),
            page.getByRole("button", { name: `Download ${kind} report` }).click(),
          ]);
          expect(download.suggestedFilename()).toBe(`${report.value}.${kind.toLowerCase()}`);
          await expect(page.getByText(`Downloaded ${report.label} (${kind}).`)).toBeVisible();
        }
      });
    }

    await test.step("the CSV is the report's first section, scoped to the screen's values", async () => {
      await picker(page).selectOption("pain-point-prioritisation");
      await page.getByRole("button", { name: "Export" }).click();
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.getByRole("button", { name: "Download CSV report" }).click(),
      ]);
      const csv = await readFile((await download.path())!, "utf8");
      expect(csv).toContain(titles.major);
      expect(csv).toContain(titles.blocker);
    });

    await test.step("the chosen branding template is sent with the PDF only", async () => {
      await picker(page).selectOption("pain-point-prioritisation");
      await page.getByRole("combobox", { name: "Branding template (PDF)" }).selectOption({ label: template.name });
      await page.getByRole("button", { name: "Export" }).click();
      const pdf = page.waitForResponse((r) => r.url().includes("format=pdf") && r.url().includes(`report_template_id=${template.id}`));
      await page.getByRole("button", { name: "Download PDF report" }).click();
      const response = await pdf;
      expect(response.status()).toBe(200);
      expect(response.headers()["content-type"]).toContain("application/pdf");
    });
  });

  test("a module-disabled project shows no module reports", async ({ page, request }) => {
    const { project, headers } = await setup(page, request);
    const off = await request.put(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/${CS}/enablement`, {
      headers, data: { enabled: false },
    });
    expect(off.ok(), await off.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/reports`);
    await expect(page.getByRole("button", { name: "Generate PDF" })).toBeVisible();
    await expect(picker(page)).toHaveCount(0);
  });

  test("a disabled sub-component removes only its own reports", async ({ page, request }) => {
    const { project, headers } = await setup(page, request);
    const off = await request.put(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/${CS}/subcomponents/open_question`, {
      headers, data: { enabled: false },
    });
    expect(off.ok(), await off.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/reports`);
    await expect(picker(page)).toBeVisible();
    const options = await picker(page).locator("option").allTextContents();
    expect(options).toContain("Pain Point prioritisation");
    expect(options).not.toContain("Open Question register");
  });

  test("organisation reports are listed for an org admin and need the org role for anyone else", async ({ page, request }) => {
    const { org, project, headers, suffix, titles } = await setup(page, request);
    const memberEmail = `e2e-reports-member-${suffix}@example.com`;
    const member = await (await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: headers, data: { email: memberEmail, display_name: "E2E Reports Member", password: PASSWORD, role: "member" },
    })).json();
    const memberRole = await request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/roles`, {
      headers: headers, data: { user_id: member.user_id, role: "member" },
    });
    expect(memberRole.status()).toBe(204);

    await test.step("an org admin sees the Reports group and its org-wide reports", async () => {
      await page.goto(`/orgs/${org.id}/overview`);
      await page.getByRole("link", { name: "Reports", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/orgs/${org.id}/overview/reports`));
      await picker(page).selectOption({ label: "Pain Point prioritisation" });
      await expect(page.getByRole("table", { name: "Ranked Pain Points" })).toContainText(titles.major);
      // Project-only reports (e.g. the Strategy cascade) are not org-wide.
      expect(await picker(page).locator("option").allTextContents()).not.toContain("Strategy cascade and alignment");
    });

    await test.step("an org report can be narrowed to one project with the Project picker", async () => {
      const other = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
        headers, data: { organization_id: org.id, name: `Reports UI Other ${suffix}`, summary: "" },
      })).json();
      // A project the org admin holds no role on is outside this report's scope, so it is not offered.
      const ownerEmail = `e2e-reports-owner-${suffix}@example.com`;
      await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
        headers, data: { email: ownerEmail, display_name: "E2E Reports Owner", password: PASSWORD, role: "project_creator" },
      });
      const ownerHeaders = await api(request, ownerEmail);
      const hidden = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
        headers: ownerHeaders, data: { organization_id: org.id, name: `Reports UI Hidden ${suffix}`, summary: "" },
      })).json();
      await page.goto(`/orgs/${org.id}/overview/reports?report=pain-point-prioritisation`);
      const projectPicker = page.getByRole("combobox", { name: "Project", exact: true });
      await expect(page.getByRole("table", { name: "Ranked Pain Points" })).toContainText(titles.major);
      await expect(projectPicker.locator("option")).toHaveText(["All projects", project.name, other.name].sort((x, y) => (x === "All projects" ? -1 : y === "All projects" ? 1 : x.localeCompare(y))));

      await expect(projectPicker.locator("option", { hasText: hidden.name })).toHaveCount(0);

      // The other project has no Pain Points, so narrowing to it empties the ranking.
      const narrowed = page.waitForRequest((r) => r.url().includes("pain-point-prioritisation") && r.url().includes(`project_id=${other.id}`));
      await projectPicker.selectOption({ label: other.name });
      await narrowed;
      await expect(page.getByRole("table", { name: "Ranked Pain Points" })).toHaveCount(0);

      await projectPicker.selectOption({ label: project.name });
      await expect(page.getByRole("table", { name: "Ranked Pain Points" })).toContainText(titles.major);
      // One project: the list no longer needs a Project column.
      const ranking = page.getByRole("table", { name: "Ranked Pain Points" });
      await expect(ranking.getByRole("columnheader", { name: "Project", exact: true })).toHaveCount(0);

      await projectPicker.selectOption({ label: "All projects" });
      await expect(ranking.getByRole("columnheader", { name: "Project", exact: true })).toBeVisible();
    });

    await test.step("a project member without the org report role sees no Reports group", async () => {
      await logout(page);
      await loginAs(page, memberEmail, PASSWORD);
      await page.goto(`/orgs/${org.id}/overview`);
      await expect(page.getByRole("heading", { name: /E2E Reports UI/ })).toBeVisible();
      await expect(page.getByRole("link", { name: "Reports", exact: true })).toHaveCount(0);
      await page.goto(`/orgs/${org.id}/overview/reports`);
      await expect(picker(page)).toHaveCount(0);
    });

    await test.step("granting the org role makes the group appear", async () => {
      const grant = await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users/${member.user_id}/module-roles`, {
        headers: headers, data: { module_key: CS, role_key: "org_reports_viewer" },
      });
      expect(grant.status()).toBe(204);
      await page.goto(`/orgs/${org.id}/overview`);
      await expect(page.getByRole("link", { name: "Reports", exact: true })).toBeVisible();
    });
  });
});
