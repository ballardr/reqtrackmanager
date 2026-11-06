import { expect, test } from "@playwright/test";

import { installCleanupHook, selectOrgAdminGroup, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { expandScoringLevels } from "../scoringLevels";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an organisation administrator chooses which scoring models are shown, defines its own scoring
 * criteria (an axis and a model) and hides built-in ones it does not use; a project does the same for itself and edits
 * the levels of an axis it defined.
 *
 * Builds its own disposable org (see `./helpers.ts`), so it depends on no seeded state.
 */
test.describe("Enhancement requests: scoring administration", () => {
  test("the organisation defines an axis and a model, chooses the models shown, and hides and restores one", async ({ page }) => {
    const { org, adminHeaders } = await setUpOrg(page, "FeedbackScoringOrg");
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Request Scoring");

    await test.step("a derived axis edits a threshold per level, a manual axis does not", async () => {
      await expandScoringLevels(page);
      await expect(page.getByRole("spinbutton", { name: "Demand level threshold" }).first()).toBeVisible();
      await expect(page.getByRole("spinbutton", { name: "Impact level threshold" })).toHaveCount(0);
    });

    await test.step("defines an axis with its levels", async () => {
      await page.getByRole("button", { name: "Add axis" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Name", { exact: true }).fill("Strategic fit");
      await dialog.getByLabel("Level 1 name").fill("Weak");
      await dialog.getByLabel("Level 1 weight").fill("1");
      await dialog.getByLabel("Level 2 name").fill("Strong");
      await dialog.getByLabel("Level 2 weight").fill("3");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Axis added.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Edit Strategic fit" })).toBeVisible();
      await expandScoringLevels(page);
      await expect(page.getByRole("textbox", { name: "Strategic fit level name" }).first()).toBeVisible();
    });

    await test.step("defines a weighted-sum model that must total 100 per cent", async () => {
      await page.getByRole("button", { name: "Add model" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Name", { exact: true }).fill("Weighted value");
      await dialog.getByLabel("Combination").selectOption({ label: "Weighted sum" });
      await dialog.getByLabel("Impact role").selectOption({ label: "Add" });
      await dialog.getByLabel("Strategic fit role").selectOption({ label: "Add" });
      await dialog.getByLabel("Impact importance").fill("70");
      await dialog.getByLabel("Strategic fit importance").fill("20");
      await expect(dialog.getByText("Importance totals 90%; it must total 100%.")).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
      await dialog.getByLabel("Strategic fit importance").fill("30");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Model added.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Edit Weighted value" })).toBeVisible();
    });

    await test.step("the new axis and model are part of the organisation's scheme", async () => {
      const scheme = await (
        await page.request.get(`${API_BASE_URL}/api/v1/orgs/${org.id}/scoring-schemes/enhancement_request`, { headers: adminHeaders })
      ).json();
      expect(scheme.axes.some((a: { label: string; origin: string }) => a.label === "Strategic fit" && a.origin === "org")).toBeTruthy();
      expect(scheme.models.some((m: { label: string; combination: string }) => m.label === "Weighted value" && m.combination === "weighted_sum")).toBeTruthy();
    });

    await test.step("choosing the models shown saves, and the default model stays on", async () => {
      await expect(page.getByRole("checkbox", { name: /^Show RICE \(/ })).toBeDisabled();
      await page.getByRole("checkbox", { name: "Show Weighted value" }).click();
      await expect(page.getByText("Models shown saved.")).toBeVisible();
      await page.reload();
      await selectOrgAdminGroup(page, "Request Scoring");
      await expect(page.getByRole("checkbox", { name: "Show Weighted value" })).not.toBeChecked();
    });

    await test.step("hiding a built-in model asks first and lists it as hidden until restored", async () => {
      await page.getByRole("button", { name: /^Hide ICE \(/ }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Hide", exact: true }).click();
      await expect(page.getByText(/^ICE \(.*\) hidden\.$/)).toBeVisible();
      await expect(page.getByRole("button", { name: /^Restore ICE \(/ })).toBeVisible();
      await page.getByRole("button", { name: /^Restore ICE \(/ }).click();
      await expect(page.getByText(/^ICE \(.*\) restored\.$/)).toBeVisible();
      await expect(page.getByRole("button", { name: /^Hide ICE \(/ })).toBeVisible();
    });

    await test.step("an axis a model uses cannot be deleted, with the reason shown", async () => {
      await page.getByRole("button", { name: "Delete Strategic fit" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Delete axis" }).click();
      await expect(page.getByText(/Model\(s\) still use this axis: Weighted value/)).toBeVisible();
    });
  });

  test("a project defines its own axis, edits its levels, and hides a model", async ({ page }) => {
    const { project } = await setUpOrg(page, "FeedbackScoringProject");
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Request Scoring");

    await test.step("defines an axis that belongs to this project", async () => {
      await page.getByRole("button", { name: "Add axis" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Name", { exact: true }).fill("Local fit");
      await dialog.getByLabel("Level 1 name").fill("Poor");
      await dialog.getByLabel("Level 1 weight").fill("1");
      await dialog.getByLabel("Level 2 name").fill("Good");
      await dialog.getByLabel("Level 2 weight").fill("2");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Axis added.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Edit Local fit" })).toBeVisible();
    });

    await test.step("edits a level of that axis, but not an organisation axis's levels", async () => {
      await expandScoringLevels(page);
      const name = page.getByRole("textbox", { name: "Local fit level name" }).first();
      await name.fill("Awful");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(page.getByText("Level saved.")).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Impact level name" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Edit Impact" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Hide Impact" })).toBeVisible();
    });

    await test.step("the project chooses its own models shown, then goes back to inheriting", async () => {
      await page.getByRole("checkbox", { name: /^Show ICE \(/ }).click();
      await expect(page.getByText("Models shown saved.")).toBeVisible();
      await page.getByRole("button", { name: "Use inherited value" }).first().click();
      await expect(page.getByText("Models shown reset.")).toBeVisible();
      await expect(page.getByRole("checkbox", { name: /^Show ICE \(/ })).toBeChecked();
    });
  });

  test("a project sets its own demand thresholds beside the organisation's, and goes back to them", async ({ page }) => {
    const { project, adminHeaders } = await setUpOrg(page, "FeedbackScoringThresholds");
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Request Scoring");
    await expandScoringLevels(page);

    const field = (level: string) => page.getByRole("spinbutton", { name: `Demand ${level} threshold in this project` });
    const projectScheme = async () => (
      await page.request.get(`${API_BASE_URL}/api/v1/projects/${project.id}/scoring-schemes/enhancement_request`, { headers: adminHeaders })
    ).json();

    await test.step("starts on the organisation's values; an ordinary axis offers no threshold", async () => {
      await expect(page.getByText("Organisation values")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save thresholds" })).toBeDisabled();
      await expect(page.getByRole("spinbutton", { name: /^Impact .* threshold/ })).toHaveCount(0);
    });

    await test.step("thresholds that do not rise are refused before saving", async () => {
      const many = field("Many");
      const original = await many.inputValue();
      await many.fill("1");
      await expect(page.getByText("Each level must start above the one before.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save thresholds" })).toBeDisabled();
      await many.fill(original);
    });

    await test.step("saving sets the project's own values and keeps the organisation's visible", async () => {
      await field("Many").fill("100");
      await field("Widespread").fill("200");
      await page.getByRole("button", { name: "Save thresholds" }).click();
      await expect(page.getByText("Thresholds saved.")).toBeVisible();
      await expect(page.getByText("Own thresholds")).toBeVisible();
      const axis = (await projectScheme()).axes.find((a: { key: string }) => a.key === "demand");
      expect(axis.thresholds_source).toBe("project");
      expect(axis.levels.map((l: { threshold: number }) => l.threshold).slice(-2)).toEqual([100, 200]);
      expect(axis.levels.map((l: { org_threshold: number }) => l.org_threshold).slice(-2)).toEqual([15, 30]);
    });

    await test.step("using the inherited values clears them", async () => {
      await page.getByRole("button", { name: "Use inherited values" }).click();
      await expect(page.getByText("Thresholds reset.")).toBeVisible();
      await expect(page.getByText("Own thresholds")).toHaveCount(0);
      expect((await projectScheme()).axes.find((a: { key: string }) => a.key === "demand").thresholds_source).toBe("organisation");
    });
  });
});
