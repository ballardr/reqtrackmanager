import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, createRisk, riskLevels, setUpOrg, statusBadge } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: exit
 * criteria — Playwright e2e coverage of the Risk Management UI
 * (`frontend/src/modules/risk_management/`) against a real backend: record and
 * rate a risk and move it through its lifecycle with a version history; tell a
 * *linked* treatment from an *effective* one; record a review and clear an
 * overdue flag; read the configured matrix and narrow the register by a cell;
 * and reach the organisation's Risk type vocabulary.
 *
 * Each test builds its own disposable org (see `./helpers.ts`), so none depends
 * on seeded state or on another test having run.
 */

const links = (page: Page) => page.getByRole("region", { name: "Links", exact: true });
const treatments = (page: Page) => page.getByRole("region", { name: "Treatments", exact: true });

test.describe("Risk Management", () => {
  test("records and rates a risk, moves it through its lifecycle and keeps a version history", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "RiskLife");
    const title = `Supplier firmware late ${suffix}`;

    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Risks", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/risk_management/risks$`));
    await expect(page.getByText("No Risks recorded for this project yet.")).toBeVisible();

    // --- Create (a Modal layer); the rating is derived from the picked levels.
    await page.getByRole("button", { name: "New risk" }).click();
    const dialog = page.getByRole("dialog", { name: "New risk" });
    await dialog.getByLabel("Risk title").fill(title);
    await dialog.getByLabel("Risk statement").fill("If the supplier slips, testing starts late.");
    await dialog.getByLabel("Inherent likelihood").selectOption({ label: "Likely" });
    await dialog.getByLabel("Inherent consequence").selectOption({ label: "Major" });
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Risk created.")).toBeVisible();

    // --- The register renders label-mapped status and the derived band (Likely x Major = 16 of 25).
    const row = page.locator("tr", { hasText: title });
    await expect(row.getByText("Identified", { exact: true })).toBeVisible();
    await expect(row.getByText("High", { exact: true })).toBeVisible();

    await row.getByRole("link", { name: "RSK-001" }).click();
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    await expect(statusBadge(page, "Identified")).toBeVisible();

    // --- Move to Assessed behind a dialog offering only the legal next states.
    await page.getByRole("button", { name: "Change status" }).click();
    const move = page.getByRole("dialog", { name: "Change status of RSK-001" });
    await expect(move.getByRole("option", { name: "Assessed" })).toHaveCount(1);
    await expect(move.getByRole("option", { name: "Closed" })).toHaveCount(0);
    await move.getByLabel("New status").selectOption({ label: "Assessed" });
    await move.getByLabel("Status change comment").fill("Rated with the supplier");
    await move.getByRole("button", { name: "Change status" }).click();
    await expect(page.getByText("Risk moved to Assessed.")).toBeVisible();
    await expect(statusBadge(page, "Assessed")).toBeVisible();

    // --- Edit as a layer; the change becomes a new version.
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const edit = page.getByRole("dialog", { name: "Edit RSK-001" });
    await edit.getByLabel("Cause").fill("Single-source supplier with no contractual date.");
    await edit.getByLabel("Change note").fill("Added cause");
    await edit.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Single-source supplier with no contractual date.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Version history" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Added cause" })).toBeVisible();
  });

  test("tells a linked treatment from an effective one", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "RiskTreat");
    const api = `${API_BASE_URL}/api/v1/projects/${project.id}`;
    const { level } = await riskLevels(page, project.id, adminHeaders);
    const risk = await createRisk(page, project.id, adminHeaders, {
      title: `Overheating ${suffix}`,
      inherent_likelihood_level_id: level("likelihood", "Likely"),
      inherent_consequence_level_id: level("consequence", "Major"),
    });
    const component = await (await page.request.post(`${api}/components`, { headers: adminHeaders, data: { name: "Hardware", prefix: "HW" } })).json();
    const category = await (
      await page.request.post(`${api}/categories`, { headers: adminHeaders, data: { name: "Thermal", prefix: "THM", component_id: component.id } })
    ).json();
    const requirementName = `Limit case temperature ${suffix}`;
    await page.request.post(`${api}/requirements`, { headers: adminHeaders, data: { name: requirementName, component_id: component.id, category_id: category.id } });

    await page.goto(`/projects/${project.id}/modules/risk_management/risks/${risk.id}`);
    await expect(treatments(page).getByText(/No effective treatment yet/)).toBeVisible();

    // --- Linking a requirement through the Links panel only *proposes* a treatment.
    await links(page).getByRole("button", { name: "Add link" }).click();
    const add = page.getByRole("dialog", { name: "Add a link" });
    await add.getByLabel("Link to").selectOption({ label: "Requirement" });
    const record = add.getByLabel("Record");
    await expect(record.locator("option", { hasText: requirementName })).toHaveCount(1);
    await record.selectOption({ label: await record.locator("option", { hasText: requirementName }).innerText() });
    await add.getByLabel("Relationship").selectOption({ label: "Is mitigated by" });
    await add.getByRole("button", { name: "Add link" }).click();
    await expect(add).not.toBeVisible();

    const row = treatments(page).locator("tr", { hasText: requirementName });
    await expect(row.getByText("Proposed", { exact: true })).toBeVisible();
    await expect(page.getByText("No effective treatment", { exact: true })).toBeVisible();

    // --- The owner's verdict needs a rationale; then the risk counts as treated.
    await row.getByRole("button", { name: /^Assess/ }).click();
    const assess = page.getByRole("dialog", { name: /^Assess/ });
    await assess.getByRole("button", { name: "Save" }).click();
    await expect(assess.getByText(/rationale is required/i)).toBeVisible();
    await assess.getByLabel("Rationale").fill("Verified on the thermal rig.");
    await assess.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Treatment assessed.")).toBeVisible();
    await expect(row.getByText("Effective", { exact: true })).toBeVisible();
    await expect(treatments(page).getByText("1 effective treatment.")).toBeVisible();
    await expect(page.getByText("1 effective", { exact: true })).toBeVisible();
  });

  test("records a review, clears the overdue flag and keeps the history", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "RiskReview");
    const title = `Stale review ${suffix}`;
    const risk = await createRisk(page, project.id, adminHeaders, { title, review_date: "2020-01-01" });

    // --- The register can narrow to risks whose review date has passed.
    await page.goto(`/projects/${project.id}/modules/risk_management/risks`);
    await page.getByLabel("Review overdue").check();
    await expect(page.getByRole("link", { name: risk.unique_code })).toBeVisible();

    await page.goto(`/projects/${project.id}/modules/risk_management/risks/${risk.id}`);
    await expect(page.getByText("Review overdue", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Record review" }).click();
    const dialog = page.getByRole("dialog", { name: `Record review of ${risk.unique_code}` });
    await expect(dialog.getByRole("button", { name: "Save review" })).toBeDisabled();
    await dialog.getByLabel("Review notes").fill("Reviewed with the supplier; no change.");
    await dialog.getByLabel("Next review date").fill("2099-01-01");
    await dialog.getByRole("button", { name: "Save review" }).click();
    await expect(page.getByText("Review recorded.")).toBeVisible();

    await expect(page.getByText("Review overdue", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Next review: 2099-01-01")).toBeVisible();
    const history = page.getByRole("table", { name: "Review history" });
    await expect(history.getByText("Confirmed", { exact: true })).toBeVisible();
    await expect(history.getByText("Reviewed with the supplier; no change.")).toBeVisible();
  });

  test("plots risks on the configured matrix and narrows the register by a cell", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "RiskMatrix");
    const { level } = await riskLevels(page, project.id, adminHeaders);
    const high = await createRisk(page, project.id, adminHeaders, {
      title: `Likely and major ${suffix}`,
      inherent_likelihood_level_id: level("likelihood", "Likely"),
      inherent_consequence_level_id: level("consequence", "Major"),
    });
    const low = await createRisk(page, project.id, adminHeaders, {
      title: `Rare and minor ${suffix}`,
      inherent_likelihood_level_id: level("likelihood", "Rare"),
      inherent_consequence_level_id: level("consequence", "Minor"),
    });

    await page.goto(`/projects/${project.id}/modules/risk_management/risks`);
    await page.getByRole("tab", { name: "Matrix" }).click();
    await page.getByRole("button", { name: /Likelihood Likely, Consequence Major: High, 1 item/ }).click();

    // --- Back on the register, narrowed to that cell, with a chip that clears it.
    await expect(page.getByText(/Inherent: Likely likelihood, Major consequence/)).toBeVisible();
    await expect(page.getByRole("link", { name: high.unique_code })).toBeVisible();
    await expect(page.getByRole("link", { name: low.unique_code })).toHaveCount(0);
    await page.getByRole("button", { name: "Clear matrix filter" }).click();
    await expect(page.getByRole("link", { name: low.unique_code })).toBeVisible();
  });

  test("an organisation administrator reaches the seeded Risk type vocabulary", async ({ page }) => {
    await setUpOrg(page, "RiskTypes");
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
    await selectOrgAdminGroup(page, "Risk Types");
    await expect(page.locator(`input[value="Safety"]`)).toBeVisible();
    await expect(page.locator(`input[value="Schedule"]`)).toBeVisible();
  });
});
