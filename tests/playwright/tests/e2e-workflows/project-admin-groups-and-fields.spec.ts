import { expect, test } from "@playwright/test";

import { loginAs, openGroupCard, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: per-project custom fields of all four types (C-C-01,
 * C-C-02), project group membership management (C-U-11), and per-project
 * terminology overrides (C-C-03).
 *
 * Uses Beta-2. The terminology change is reverted at the end of the test
 * since it's a shared, persistent project setting other specs' nav-label
 * assertions could otherwise be surprised by. The four custom fields are
 * each given a per-run timestamp suffix rather than a fixed name — Custom
 * Fields has no server-side uniqueness constraint on name, so a fixed name
 * re-run against an already-mutated Beta-2 (no reseed in between) doesn't
 * fail outright but does leave every earlier run's own same-named fields
 * behind, which upstream steps and other specs sharing this project can
 * then trip over. A unique name per run avoids that regardless of how many
 * times, or in what order, this spec has run against the current database.
 */
test.describe("project admin: custom fields, groups, and terminology", () => {
  test("all four custom field types, group membership, and a terminology override", async ({ page }) => {
    const suffix = Date.now();
    const verificationMethodField = `Verification method ${suffix}`;
    const detailedRationaleField = `Detailed rationale ${suffix}`;
    const safetyCriticalField = `Safety critical ${suffix}`;
    const priorityField = `Priority ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.beta2).click();
    await page.getByRole("link", { name: "Project admin", exact: true }).click();

    await test.step("create a custom field of each type", async () => {
      // Custom fields now lives inside the merged "Fields & actions" tab
      // (2026-08 UX audit roadmap: Project Admin's 8 tabs -> 5).
      await page.getByRole("tab", { name: "Fields & actions" }).click();

      const fieldNameInput = page.getByPlaceholder("Field name");

      await fieldNameInput.fill(verificationMethodField);
      await expect(fieldNameInput).toHaveValue(verificationMethodField);
      await page.getByRole("combobox").nth(1).selectOption("short_text");
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText(verificationMethodField)).toBeVisible();

      await fieldNameInput.fill(detailedRationaleField);
      await expect(fieldNameInput).toHaveValue(detailedRationaleField);
      await page.getByRole("combobox").nth(1).selectOption("long_text");
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText(detailedRationaleField)).toBeVisible();

      await fieldNameInput.fill(safetyCriticalField);
      await expect(fieldNameInput).toHaveValue(safetyCriticalField);
      await page.getByRole("combobox").nth(1).selectOption("checkbox");
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText(safetyCriticalField)).toBeVisible();

      await fieldNameInput.fill(priorityField);
      await expect(fieldNameInput).toHaveValue(priorityField);
      await page.getByRole("combobox").nth(1).selectOption("list");
      await page.getByPlaceholder("Options (comma separated)").fill("Low, Medium, High");
      await page.getByLabel("Required").check();
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText(priorityField)).toBeVisible();
      await expect(page.getByText("Required").first()).toBeVisible();
    });

    await test.step("a new custom field shows up on the requirement create form", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("button", { name: "New Requirement" }).click();
      await page.getByRole("button", { name: "Add one" }).click();
      await expect(page.getByText(verificationMethodField)).toBeVisible();
      await expect(page.getByText(priorityField)).toBeVisible();
      await page.keyboard.press("Escape").catch(() => {});
      await page.goto(page.url());
    });

    await test.step("delete a custom field", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Fields & actions" }).click();
      const row = page.locator(".row", { hasText: safetyCriticalField });
      await row.getByRole("button").click();
      await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
      await expect(page.getByText(safetyCriticalField)).toHaveCount(0);
    });

    await test.step("add and remove a project group member", async () => {
      await page.getByRole("tab", { name: "Project groups" }).click();
      // Groups now render collapsed by default (2026-08 UX audit
      // "Directories at scale") — expand "Members" specifically before its
      // own add-member input is reachable at all.
      await openGroupCard(page, "Members");
      await page.getByPlaceholder("Type a name to add, or an email to invite…").last().fill(PERSONAS.memberAlphaBeta.name);
      await page.getByText(PERSONAS.memberAlphaBeta.email).click();
      await expect(page.getByText(PERSONAS.memberAlphaBeta.name)).toBeVisible();

      const removeButton = page.locator("li", { hasText: PERSONAS.memberAlphaBeta.email }).getByRole("button");
      await removeButton.click();
      await expect(page.getByText(PERSONAS.memberAlphaBeta.email)).toHaveCount(0);
    });

    await test.step("nest an org group into a project group directly from Project Admin", async () => {
      // The backend has always supported org_group_id here (add_project_group_member);
      // this closes the UX gap where no frontend surface sent it — only
      // OrgAdminPage's own "expanded project" panel could, previously.
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const projectId = page.url().match(/projects\/([0-9a-f-]+)\/admin/)![1];
      const project = await (
        await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
      ).json();
      const groupName = `E2E Nest Into Project ${Date.now()}`;
      await page.request.post(`http://localhost:8000/api/v1/orgs/${project.organization_id}/groups`, {
        headers: { Authorization: `Bearer ${token}` }, data: { name: groupName },
      });
      // ProjectAdminPage fetches org groups once on mount — the group just
      // created via a direct API call isn't in that state until reloaded.
      await page.reload();

      await page.getByRole("tab", { name: "Project groups" }).click();
      // Groups render collapsed by default — "Members" was expanded in the
      // step above, but that expand state is per-user/per-group and the
      // page was just reloaded, so re-assert it idempotently rather than
      // assume it survived (`openGroupCard` only clicks if collapsed).
      await openGroupCard(page, "Members");
      // Default project groups are created in a fixed order — Project
      // Managers, Project Administrators, Stakeholders, Members — so the
      // "Members" group's own org-group picker is reliably the last one
      // (same assumption the add-member step above already makes). Scoped
      // to `select` specifically — each group's own "add member"
      // `UserAutocomplete` input is `role="combobox"` too (WAI-ARIA
      // combobox pattern), so a bare role query is ambiguous here.
      const membersGroupSelect = page.locator("select").last();
      await membersGroupSelect.selectOption({ label: groupName });
      await membersGroupSelect.locator("xpath=../button").click();
      await expect(page.getByText(`${groupName} (`)).toBeVisible();

      const orgGroupRow = page.locator("li", { hasText: groupName });
      await orgGroupRow.getByRole("button").click();
      await expect(page.getByText(`${groupName} (`)).toHaveCount(0);
    });

    // Style guide "Pattern: create panels, popovers, and one door for
    // bulk" — closes the 2026-08 UX audit's "Groups tab manages membership
    // only, no create form at all" finding. Mirrors Org Admin's own "New
    // group" popover coverage, against the project-scoped endpoint (which
    // also requires a role up front, unlike the org-scoped one). Runs
    // *after* the steps above that rely on "Members" being the last
    // group in DOM order (`.last()` selectors) — the group created here
    // would otherwise become the new last one and break those.
    await test.step("create a new project group via the New group popover", async () => {
      await page.getByRole("tab", { name: "Project groups" }).click();
      const newGroupName = `E2E New Project Group ${Date.now()}`;

      await page.getByRole("button", { name: "New group" }).click();
      const dialog = page.getByRole("dialog", { name: "New group" });
      await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
      await dialog.getByPlaceholder("e.g. Reviewers").fill(newGroupName);
      await dialog.getByLabel("Role").selectOption("stakeholder");
      await dialog.getByRole("button", { name: "Create" }).click();

      // Principle 7 — every mutation ends with feedback.
      await expect(page.getByText("Group created")).toBeVisible();
      await expect(dialog).not.toBeVisible();
      await expect(page.getByText(newGroupName)).toBeVisible();
      await expect(page.getByText(newGroupName).locator("xpath=..").getByText("Stakeholder")).toBeVisible();
    });

    await test.step("override and then revert a terminology term", async () => {
      // Terminology now lives inside Overview ("Project settings") rather
      // than its own tab (2026-08 UX audit roadmap: Project Admin's 8
      // tabs -> 5) — still needs a tab click since we're currently on
      // "Project groups" from the step above (Overview is only the
      // *default* tab on a fresh mount, not the currently-active one
      // here). Its own Save button is labelled "Save terminology",
      // distinct from Overview's own "Save settings" button now that both
      // sit on the same screen.
      await page.getByRole("tab", { name: "Project settings" }).click();
      await page.getByPlaceholder("requirement").fill("Spec");
      await page.getByRole("button", { name: "Save terminology" }).click();
      await page.reload();
      await expect(page.getByPlaceholder("requirement")).toHaveValue("Spec");

      await page.getByRole("link", { name: "Specs", exact: true }).click();
      await expect(page.url()).toContain("/requirements");

      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByPlaceholder("requirement").fill("");
      await page.getByRole("button", { name: "Save terminology" }).click();
    });
  });
});
