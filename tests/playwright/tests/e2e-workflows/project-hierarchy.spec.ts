import { expect, type Page, test } from "@playwright/test";

import { ensureExpanded, loginAs, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup } from "./helpers";

/**
 * Opens a project by name from the project list, forced to tile view. A
 * plain `getByText(name).click()` is ambiguous for any project that
 * participates in a parent/child relationship — a "Parent of:"/"Child of:"
 * cross-reference elsewhere on the page can carry the exact same text (see
 * helpers.ts's `openRequirementByCode` docstring for the general shape of
 * this class of bug). Tile rows carry a `title` attribute on their own name
 * link that a cross-reference link does not, which is what makes "this
 * project's own row" unambiguous.
 */
async function openProjectByName(page: Page, name: string): Promise<void> {
  await page.goto("/projects");
  await page.getByRole("button", { name: "Tile view" }).click();
  await page.locator(`a[title="${name}"]`).click();
}

/**
 * Job to be done: a large programme can be modelled as a parent project
 * with its own sub-projects, each with their own requirement sets, while
 * still being manageable as a whole — see docs/decisions.md's
 * "Hierarchical projects" entry for the full design (backend RBAC/cycle/
 * authorization correctness is covered exhaustively there and in
 * backend/tests/test_project_hierarchy.py; this spec proves the resulting
 * UI is actually wired up end to end against the real browser).
 *
 * Uses Gamma (single-org persona, avoids interfering with Alpha/Beta specs
 * sharing this suite's single-worker run — same choice org-group-nesting.spec.ts
 * and org-security-controls.spec.ts make) plus a second, project-scoped-only
 * persona (`projectMgrGamma`) for the relaxed child-creation path, and the
 * fixed Gamma-3/Gamma-4 fixture (backend/scripts/seed_e2e_dataset.py) for
 * scenarios that need a pre-existing, already-configured relationship
 * rather than one this spec builds itself.
 */
test.describe("hierarchical (parent/child) projects", () => {
  test("create a sub-project via the modal, mirror-all requires confirmation, and hierarchy labels + tree view render", async ({
    page,
  }) => {
    const suffix = Date.now();
    const parentName = `Hierarchy Parent ${suffix}`;
    const childName = `Hierarchy Child ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/projects");

    await test.step("create the parent as an ordinary root project", async () => {
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.getByLabel("Name", { exact: true }).fill(parentName);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: parentName })).toBeVisible();
    });

    await test.step("can_be_parent defaults off — opt in via the settings tab before this project can be used as a parent", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      const addSubProject = page.getByRole("button", { name: "Add sub-project" });
      await expect(addSubProject).toBeDisabled();
      await page.getByLabel(/Allow this .* to be a parent/).check();
      await page.getByRole("button", { name: "Save settings" }).click();
      await expect(addSubProject).toBeEnabled();
    });

    await test.step("'Add sub-project' from the parent's own admin page pre-fills the parent and opens the create modal", async () => {
      await page.getByRole("button", { name: "Add sub-project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      // The parent select's current selection resolves to the parent
      // project's own name as its chosen <option> text.
      await expect(dialog.getByLabel("Parent project").locator("option:checked")).toHaveText(parentName);

      await dialog.getByLabel("Name", { exact: true }).fill(childName);
    });

    await test.step("selecting 'Mirror all roles' requires confirmation naming the parent before it takes effect", async () => {
      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.getByLabel("Inherit access from parent").selectOption("mirror_all");

      const confirm = page.getByRole("dialog", { name: "Enable access inheritance?" });
      await expect(confirm).toBeVisible();
      await expect(confirm.getByText(new RegExp(`holds any role on '${parentName}'`))).toBeVisible();
      // Cancelling leaves the mode unchanged (still "None") rather than
      // silently applying it.
      await confirm.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog.getByLabel("Inherit access from parent")).toHaveValue("none");

      await dialog.getByLabel("Inherit access from parent").selectOption("mirror_all");
      await page.getByRole("dialog", { name: "Enable access inheritance?" }).getByRole("button", { name: "Enable inheritance" }).click();
      await expect(dialog.getByLabel("Inherit access from parent")).toHaveValue("mirror_all");

      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: childName })).toBeVisible();
    });

    await test.step("'Child of:'/'Parent of:' labels render on the project list", async () => {
      await page.goto("/projects");
      await page.getByRole("button", { name: "Tile view" }).click();
      const cardFor = (name: string) =>
        page.locator(`a[title="${name}"]`).locator(
          "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]"
        );

      const childCard = cardFor(childName);
      await expect(childCard.getByText("Child of:")).toBeVisible();
      await expect(childCard.getByRole("link", { name: parentName, exact: true })).toBeVisible();
      const parentCard = cardFor(parentName);
      await expect(parentCard.getByText("Parent of:")).toBeVisible();
      await expect(parentCard.getByRole("link", { name: childName, exact: true })).toBeVisible();
    });

    await test.step("tree view renders the new parent/child pair", async () => {
      await page.getByRole("button", { name: "Tree view" }).click();
      const treeParentRow = page.getByRole("link", { name: parentName, exact: true }).locator("xpath=ancestor::li[1]");
      await expect(treeParentRow.getByRole("link", { name: childName, exact: true })).toBeVisible();
    });
  });

  test("member sources are managed from the parent's admin page only, and effective members show inherited provenance with materialize", async ({
    page,
  }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);

    await test.step("Gamma-3 (the parent) lists Gamma-4 as a member source", async () => {
      await openProjectByName(page, PROJECT_NAMES.gamma3);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Member sources" })).toBeVisible();
      await expect(page.getByRole("link", { name: PROJECT_NAMES.gamma4, exact: true })).toBeVisible();
    });

    await test.step("Gamma-4 (the child) has no way to manage that relationship from its own page", async () => {
      await openProjectByName(page, PROJECT_NAMES.gamma4);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Member sources" })).toBeVisible();
      // Gamma-3's own name is expected to appear elsewhere on this page (the
      // "Parent project" field always shows the current parent plainly to
      // the child's own manager, per docs/decisions.md) — what must NOT
      // exist is any control letting Gamma-4 manage *being consumed by*
      // Gamma-3. Gamma-4 has no children of its own, so the member-sources
      // section renders its empty state — proof there is nothing to add or
      // remove there, which is the actual property under test.
      await expect(page.getByText("No direct sub-projects available to add.")).toBeVisible();
    });

    await test.step("effective members shows the stakeholder-on-Gamma-3 as forward-inherited (mirror all roles) on Gamma-4", async () => {
      await page.getByRole("tab", { name: "Project groups" }).click();
      await ensureExpanded(page, "Effective members");
      await page.getByRole("button", { name: "Show members" }).click();
      const memberRow = page.locator("tr", { hasText: PERSONAS.projectMgrGamma.name });
      await expect(memberRow).toBeVisible();
      await expect(
        memberRow.getByText(/Inherited from '.*Gamma-3 Hierarchy Parent.*' \(mirror all roles\) \(Stakeholder\)/)
      ).toBeVisible();
    });

    await test.step("materializing converts that inherited access into a direct role, without dropping the inherited grant", async () => {
      await page.getByRole("button", { name: "Convert all inherited access to direct roles" }).click();
      await expect(page.getByText(/Converted \d+ users? to direct roles\./)).toBeVisible();
      const memberRow = page.locator("tr", { hasText: PERSONAS.projectMgrGamma.name });
      // A user with both a direct grant and an inherited one shows both
      // sources (docs/decisions.md) — merged text nodes mean an exact
      // "Direct" match can be unreliable, hence the substring regex.
      await expect(memberRow.getByText(/Direct \(Stakeholder\)/)).toBeVisible();
      await expect(memberRow.getByText(/Inherited from/)).toBeVisible();

      // Materialize is a one-way, permanent grant — revert it via a direct
      // API call so this spec stays idempotent across repeated runs against
      // the same database (this project's test-independence rule), leaving
      // Gamma-4 back at "stakeholder access purely via inheritance" for the
      // next run, exactly as this test found it.
      const gamma4Id = page.url().match(/\/projects\/([0-9a-f-]+)\/admin/)![1];
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const authHeaders = { Authorization: `Bearer ${token}` };
      const members: { user_id: string; display_name: string }[] = await page
        .request.get(`http://localhost:8000/api/v1/projects/${gamma4Id}/effective-members`, { headers: authHeaders })
        .then((r) => r.json());
      const projectMgr = members.find((m) => m.display_name === PERSONAS.projectMgrGamma.name)!;
      await page.request.delete(
        `http://localhost:8000/api/v1/projects/${gamma4Id}/roles/${projectMgr.user_id}/stakeholder`,
        { headers: authHeaders }
      );
    });
  });

  test("a project manager with no org-level role can create a sub-project under a project they manage, but cannot detach it until granted org rights", async ({
    page,
  }) => {
    const suffix = Date.now();
    const childName = `Relaxed Path Child ${suffix}`;

    await test.step("projectMgrGamma (member-only, PM on Gamma-1 via direct role) creates a sub-project of Gamma-1", async () => {
      await loginAs(page, PERSONAS.projectMgrGamma.email);
      await openProjectByName(page, PROJECT_NAMES.gamma1);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("button", { name: "Add sub-project" }).click();

      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.getByLabel("Name", { exact: true }).fill(childName);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: childName })).toBeVisible();
    });

    await test.step("that same user cannot detach it — the parent_required guard closes the create-then-detach bypass", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Project settings" }).click();
      await page.getByLabel("Parent project").selectOption({ label: "None (top-level project)" });
      await page.getByRole("button", { name: "Save settings" }).click();
      await expect(page.getByText(/must remain nested under a parent/)).toBeVisible();
    });

    await test.step("once granted org-level rights, the same detach succeeds", async () => {
      await loginAs(page, PERSONAS.orgAdminGamma.email);
      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Users");
      await ensureExpanded(page, "Organisation users");
      const row = page.locator("tr", { hasText: PERSONAS.projectMgrGamma.email });
      await row.getByRole("button", { name: `${PERSONAS.projectMgrGamma.name}'s roles` }).click();
      await page.getByRole("checkbox", { name: `Grant Project creator to ${PERSONAS.projectMgrGamma.name}` }).click();

      await loginAs(page, PERSONAS.projectMgrGamma.email);
      await openProjectByName(page, childName);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Project settings" }).click();
      await page.getByLabel("Parent project").selectOption({ label: "None (top-level project)" });
      await page.getByRole("button", { name: "Save settings" }).click();
      await expect(page.getByText(/must remain nested under a parent/)).toHaveCount(0);
      await expect(page.getByLabel("Parent project")).toHaveValue("");
    });
  });

  test("an org admin can disable the relaxed child-creation path, blocking a plain project manager's 'Add sub-project'", async ({
    page,
  }) => {
    await test.step("turn the org toggle off", async () => {
      await loginAs(page, PERSONAS.orgAdminGamma.email);
      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Security");
      await ensureExpanded(page, "Security");
      const toggle = page.getByRole("switch", { name: /Allow \S+ managers to create sub-\S+s/ });
      await expect(toggle).toBeChecked();
      await toggle.click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save security settings" }).click(),
      ]);
    });

    await test.step("the plain project manager's 'Add sub-project' now fails", async () => {
      await loginAs(page, PERSONAS.projectMgrGamma.email);
      await openProjectByName(page, PROJECT_NAMES.gamma1);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("button", { name: "Add sub-project" }).click();

      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.getByLabel("Name", { exact: true }).fill(`Blocked Sub-Project ${Date.now()}`);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      await expect(dialog.getByText("Only org admins or project creators may create projects.")).toBeVisible();
    });

    await test.step("restore the toggle so later/other runs aren't affected", async () => {
      await loginAs(page, PERSONAS.orgAdminGamma.email);
      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Security");
      await ensureExpanded(page, "Security");
      const toggle = page.getByRole("switch", { name: /Allow \S+ managers to create sub-\S+s/ });
      await expect(toggle).not.toBeChecked();
      await toggle.click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save security settings" }).click(),
      ]);
    });
  });
});
