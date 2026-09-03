import { expect, type Page, test } from "@playwright/test";

import { ensureExpanded, loginAs, openProjectGroupPanel, PERSONAS, PROJECT_NAMES, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

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
      // PR5 of the members/groups directory rework plan: "Member sources"
      // moved from the Overview tab onto the Groups tab, rendering as a
      // type-badged row in the same table as real project groups rather
      // than a separate `<ul>` — no more `<Link>` on the row itself (the
      // Groups tab's row-click affordance is reserved for real groups), so
      // this now checks for the row's cell text instead of a link role.
      await selectProjectAdminGroup(page, "Project groups");
      await expect(page.getByRole("heading", { name: "Member sources" })).toBeVisible();
      await expect(page.getByRole("cell", { name: PROJECT_NAMES.gamma4, exact: true })).toBeVisible();
    });

    await test.step("Gamma-4 (the child) has no way to manage that relationship from its own page", async () => {
      await openProjectByName(page, PROJECT_NAMES.gamma4);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Project groups");
      await expect(page.getByRole("heading", { name: "Member sources" })).toBeVisible();
      // Gamma-3's own name is expected to appear elsewhere on this page (the
      // "Parent project" field always shows the current parent plainly to
      // the child's own manager, per docs/decisions.md) — what must NOT
      // exist is any control letting Gamma-4 manage *being consumed by*
      // Gamma-3: there simply is no such control anywhere, on either
      // project's page — `ProjectMemberSource` rows only ever live on the
      // receiving side's own list. Generalized member-source (docs/
      // decisions.md) means Gamma-4's own "consume from" picker is no
      // longer restricted to direct children and does offer other
      // same-organisation projects (Gamma-3 included) as candidates —
      // proof of the generalization working end to end, not evidence of
      // the authorization asymmetry being any weaker.
      const sourceProjectSelect = page.getByRole("combobox", { name: "Source project" });
      await expect(sourceProjectSelect).toBeVisible();
      // A native <select>'s own <option>s report as Playwright-"hidden"
      // even when selectable (the dropdown isn't open) — assert presence
      // via count, not visibility, matching this file's own established
      // `option:checked` CSS-selector workaround for the same native-select
      // limitation (see the "New project" dialog test above).
      await expect(sourceProjectSelect.getByRole("option", { name: PROJECT_NAMES.gamma1 })).toHaveCount(1);
    });

    await test.step("effective members shows the stakeholder-on-Gamma-3 as forward-inherited (mirror all roles) on Gamma-4", async () => {
      // Effective members moved onto its own "Members" section (Phase 5,
      // docs/decisions.md) — the old combined "Project groups" tab no
      // longer has it. Rebuilt again in Phase D (follow-up UX batch,
      // 2026-08-31) onto the unified `ProjectMembersTable`, which renders
      // immediately (no lazy "Show members" button/collapsed section any
      // more — this is now the tab's primary content, not a secondary
      // audit view).
      await selectProjectAdminGroup(page, "Members");
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

  test("generalized member-source (any same-org project, mirror modes) and project-referencing group members work end to end", async ({
    page,
  }) => {
    // Uses Gamma-1/Gamma-2 — unrelated (no parent/child relationship)
    // same-org projects, proving the generalization beyond strict
    // parent/child (docs/decisions.md). Both mutations this test makes are
    // undone in a `finally` block so a mid-test failure can't leave this
    // shared fixture mutated for the next run — self-healing against its
    // own prior partial runs too, via the same cleanup helper called once
    // defensively up front, per this project's test-independence rule.
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const projectIdByName = async (name: string): Promise<string> => {
      await openProjectByName(page, name);
      return page.url().match(/\/projects\/([0-9a-f-]+)/)![1];
    };
    const gamma1Id = await projectIdByName(PROJECT_NAMES.gamma1);
    const gamma2Id = await projectIdByName(PROJECT_NAMES.gamma2);

    // No project auto-creates any group any more (follow-up UX batch Phase
    // C, 2026-08-31) — Gamma-1 previously had a default "Members" group
    // this test reused for its own project-referencing-group case; that no
    // longer exists, so this test now maintains its own dedicated, fixed-
    // name custom group instead (created idempotently — get-or-create, not
    // always-create — so the defensive `cleanup()` below, and a fresh run
    // after an earlier one failed mid-test, both still find the same group
    // rather than accumulating duplicates).
    const sourceRefGroupName = "E2E Gamma-1 Source Ref Group";
    async function ensureSourceRefGroup(): Promise<{ id: string; name: string }> {
      const groups: { id: string; name: string }[] = await page
        .request.get(`http://localhost:8000/api/v1/projects/${gamma1Id}/groups`, { headers: authHeaders })
        .then((r) => r.json());
      const existing = groups.find((g) => g.name === sourceRefGroupName);
      if (existing) return existing;
      // PR7 of the members/groups directory rework plan: `ProjectGroupCreate`
      // no longer accepts a role — created bare, which is fine here since
      // this test only exercises the group's project-reference UI, never
      // its actual granted access.
      return page
        .request.post(`http://localhost:8000/api/v1/projects/${gamma1Id}/groups`, {
          headers: authHeaders, data: { name: sourceRefGroupName },
        })
        .then((r) => r.json());
    }
    const sourceRefGroup = await ensureSourceRefGroup();

    async function cleanup(): Promise<void> {
      await page.request.delete(
        `http://localhost:8000/api/v1/projects/${gamma1Id}/member-sources/${gamma2Id}`, { headers: authHeaders },
      );
      const groups: { id: string; name: string; member_source_project_ids: string[] }[] = await page
        .request.get(`http://localhost:8000/api/v1/projects/${gamma1Id}/groups`, { headers: authHeaders })
        .then((r) => r.json());
      const membersGroup = groups.find((g) => g.name === sourceRefGroupName);
      if (membersGroup?.member_source_project_ids.includes(gamma2Id)) {
        await page.request.delete(
          `http://localhost:8000/api/v1/projects/${gamma1Id}/groups/${membersGroup.id}/members/${gamma2Id}`,
          { headers: authHeaders },
        );
      }
    }

    await cleanup();
    try {
      await test.step("add Gamma-2 as a 'Mirror all roles' member source of Gamma-1 (unrelated projects, not parent/child)", async () => {
        await openProjectByName(page, PROJECT_NAMES.gamma1);
        await page.getByRole("link", { name: "Project admin", exact: true }).click();
        // PR5: "Member sources" moved from the Overview tab onto the Groups
        // tab, as a type-badged row in the same table as real project
        // groups rather than a separate `<ul>` — the row is now a `<tr>`,
        // not a `<li>`, has no `<Link>` on its name (read-only detail; a
        // real group row keeps the click-to-open affordance instead), and
        // carries two `.badge` spans (Type, then mode), not one.
        await selectProjectAdminGroup(page, "Project groups");
        await expect(page.getByRole("heading", { name: "Member sources" })).toBeVisible();
        await page.getByRole("combobox", { name: "Source project" }).selectOption({ label: PROJECT_NAMES.gamma2 });
        await page.getByRole("combobox", { name: "Mirror mode" }).selectOption({ label: "Mirror all roles" });
        await page.getByRole("button", { name: "Add", exact: true }).click();
        const gamma2SourceRow = page.locator("tr", { hasText: PROJECT_NAMES.gamma2 });
        await expect(gamma2SourceRow.getByRole("cell", { name: PROJECT_NAMES.gamma2, exact: true })).toBeVisible();
        await expect(gamma2SourceRow.getByText("Project", { exact: true })).toBeVisible();
        await expect(gamma2SourceRow.getByText("Mirror all roles", { exact: true })).toBeVisible();
      });

      await test.step("Gamma-1's own dedicated source-ref group can also define a member as 'Gamma-2's members' directly (get-or-created above, not a per-run throwaway one — `DELETE .../groups/{id}` exists as of Phase 5, but this test doesn't need it, and a fixed name lets a defensive re-run's own cleanup() find it)", async () => {
        await selectProjectAdminGroup(page, "Project groups");
        const panel = await openProjectGroupPanel(page, sourceRefGroup.name);
        await panel.getByRole("combobox", { name: "Referenced project" }).selectOption({ label: PROJECT_NAMES.gamma2 });
        await panel.getByRole("button", { name: "Reference another project's members…" }).click();
        await expect(panel.getByText(`${PROJECT_NAMES.gamma2}'s members`)).toBeVisible();
        // Phase 5: the referenced-project line also links to that project's
        // own new Members page now, with a "this is live" clarifying hint.
        await expect(panel.getByRole("link", { name: "View members" })).toBeVisible();
        // Scoped to the hint's own `<p>` element (`viaProjectMembersHint`,
        // strings.ts), not a bare page-wide `getByText(/Live/)` — this org
        // (Gamma) can independently accumulate other specs' own leftover,
        // dynamically-named fixture projects (e.g. single-org-admin.spec.ts's
        // "Gamma E2E Live {timestamp}", never cleaned up by design), which
        // also render as `<option>`s in this same panel's "Referenced
        // project" combobox — a bare substring match can incidentally
        // resolve to one of those instead of this hint text, a real
        // strict-mode violation found running the full suite together.
        await expect(panel.locator("p", { hasText: "Live" })).toBeVisible();
        await page.getByRole("button", { name: "Close" }).click();
      });
    } finally {
      await test.step("clean up: remove both additions so this shared fixture is left as found", cleanup);
    }
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
      await selectProjectAdminGroup(page, "Project settings");
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
      await selectProjectAdminGroup(page, "Project settings");
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
