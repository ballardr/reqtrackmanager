import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import {
  apiHeaders,
  ensureExpanded,
  installCleanupHook,
  loginAs,
  onCleanup,
  openProjectGroupPanel,
  ORG_NAMES,
  PERSONAS,
  PROJECT_NAMES,
  selectOrgAdminGroup,
  selectProjectAdminGroup,
} from "./helpers";

/** The title link of the tile card for a project (the card's own title, not a "Child of" / "Parent of" link to it). */
function tileTitleLink(page: Page, name: string) {
  return page.locator("a.tile-card-title").filter({ has: page.getByText(name, { exact: true }) });
}

/**
 * Opens a project by name from the project list, forced to tile view. A plain `getByText(name).click()` is ambiguous
 * for a project in a parent/child relationship, because a "Parent of:"/"Child of:" cross-reference elsewhere on the
 * page can carry the same text (see `openRequirementByCode` in helpers.ts). A tile's own name link has the
 * `tile-card-title` class that a cross-reference link lacks.
 */
async function openProjectByName(page: Page, name: string): Promise<void> {
  await page.goto("/projects");
  await page.getByRole("button", { name: "Tile view" }).click();
  // Search first: the list pages at 30 and Gamma's projects outgrow it.
  await page.getByPlaceholder("Search projects").fill(name);
  await tileTitleLink(page, name).click();
}

/**
 * Job to be done: a large programme can be modelled as a parent project with its own sub-projects, each with their
 * own requirement sets, while remaining manageable as a whole (design: docs/decisions.md "Hierarchical projects"
 * entry; backend RBAC, cycle and authorization correctness is covered in backend/tests/test_project_hierarchy.py;
 * this spec proves the UI is wired up end to end in a real browser).
 *
 * Uses Gamma (single-org persona, avoiding interference with Alpha/Beta specs, as org-group-nesting.spec.ts and
 * org-security-controls.spec.ts do), a second project-scoped-only persona (`projectMgrGamma`) for the relaxed
 * child-creation path, and the fixed Gamma-3/Gamma-4 fixture (backend/scripts/seed_e2e_dataset.py) for scenarios
 * needing a pre-existing, configured relationship.
 */
/** Looks up the seeded Gamma organisation's id (for onCleanup closures). */
async function gammaOrgId(request: APIRequestContext, headers: Record<string, string>): Promise<string> {
  const orgs: { id: string; name: string }[] = await (await request.get("http://localhost:8000/api/v1/orgs", { headers })).json();
  return orgs.find((o) => o.name === ORG_NAMES.gamma)!.id;
}

test.describe("hierarchical (parent/child) projects", () => {
  installCleanupHook();

  test("create a sub-project via the modal, mirror-all requires confirmation, and hierarchy labels + tree view render", async ({
    page,
  }) => {
    const suffix = Date.now();
    const parentName = `Hierarchy Parent ${suffix}`;
    const childName = `Hierarchy Child ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await page.goto("/projects");

    // Archives (projects have no hard-delete endpoint, `archive_project` in routers/projects.py) both throwaway
    // projects in an onCleanup (afterEach, which runs even on timeout). Leaving them behind accumulates "Hierarchy
    // Parent/Child {timestamp}" pairs until a `toBeVisible` on a new project's card times out. Each archive call is
    // wrapped individually so a failure archiving one does not skip the other or mask the `try` block's failure.
    onCleanup(async (request) => {
      const headers = await apiHeaders(request, PERSONAS.orgAdminGamma.email);
      const projects: { id: string; name: string }[] = await (await request.get(`http://localhost:8000/api/v1/projects?archived=false`, { headers })).json();
      for (const project of projects.filter((p) => p.name === parentName || p.name === childName)) {
        await request.post(`http://localhost:8000/api/v1/projects/${project.id}/archive`, { headers });
      }
    });
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
      // Parent, inheritance and mirrored role sit in one "Nesting" group that starts collapsed (the
      // choice is remembered per person, so open it only when it is closed).
      const nesting = dialog.getByRole("button", { name: "Nesting section" });
      await expect(nesting).toBeVisible();
      if (!(await dialog.getByLabel("Parent project").isVisible())) await nesting.click();
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
      // Narrowed to this run's pair (both names share the suffix): Gamma's
      // org admin has more projects than one page holds, so new ones can
      // land past the first page.
      await page.getByRole("textbox", { name: "Search projects" }).fill(String(suffix));
      const cardFor = (name: string) =>
        tileTitleLink(page, name).locator(
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
      // "Member sources" render on the Groups tab as a type-badged row in the same table as real project groups; the row
      // has no `<Link>` (the Groups tab's row-click affordance is reserved for real groups), so this checks the row's cell
      // text instead of a link role.
      await selectProjectAdminGroup(page, "Project groups");
      await expect(page.getByRole("heading", { name: "Member sources" })).toBeVisible();
      await expect(page.getByRole("cell", { name: PROJECT_NAMES.gamma4, exact: true })).toBeVisible();
    });

    await test.step("Gamma-4 (the child) has no way to manage that relationship from its own page", async () => {
      await openProjectByName(page, PROJECT_NAMES.gamma4);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await selectProjectAdminGroup(page, "Project groups");
      await expect(page.getByRole("heading", { name: "Member sources" })).toBeVisible();
      // Gamma-3's name appears elsewhere on this page (the "Parent project" field shows the current parent to the child's
      // manager, per docs/decisions.md). What must not exist is a control letting Gamma-4 manage being consumed by
      // Gamma-3: `ProjectMemberSource` rows live only on the receiving side's list. Gamma-4's "consume from" picker
      // offers other same-organisation projects (Gamma-3 included) as candidates under the generalised member-source
      // design (docs/decisions.md), which does not weaken the authorization asymmetry.
      const sourceProjectSelect = page.getByRole("combobox", { name: "Source project" });
      await expect(sourceProjectSelect).toBeVisible();
      // A native <select>'s own <option>s report as Playwright-"hidden"
      // even when selectable (the dropdown isn't open) — assert presence
      // via count, not visibility, matching this file's own established
      // `option:checked` CSS-selector workaround for the same native-select
      // limitation (see the "New project" dialog test above).
      await expect(sourceProjectSelect.getByRole("option", { name: PROJECT_NAMES.gamma1, exact: true })).toHaveCount(1);
    });

    await test.step("effective members shows the stakeholder-on-Gamma-3 as forward-inherited (mirror all roles) on Gamma-4", async () => {
      // Effective members are on their own "Members" section (docs/decisions.md), rendered by the unified
      // `ProjectMembersTable` immediately (no lazy "Show members" button or collapsed section).
      await selectProjectAdminGroup(page, "Members");
      const memberRow = page.locator("tr", { hasText: PERSONAS.projectMgrGamma.name });
      await expect(memberRow).toBeVisible();
      // The Source cell's per-source detail lives behind a click-to-open
      // popover now (ProjectMembersTable.tsx's own doc comment), not always-visible
      // text in the cell — this member has no direct role on Gamma-4, so
      // the row's summary button reads plain "Group".
      await memberRow.getByRole("button", { name: "Group" }).click();
      await expect(
        page
          .getByRole("dialog", { name: `${PERSONAS.projectMgrGamma.name}'s access sources` })
          .getByText(/Inherited from '.*Gamma-3 Hierarchy Parent.*' \(mirror all roles\) \(Stakeholder\)/)
      ).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("materializing converts that inherited access into a direct role, without dropping the inherited grant", async () => {
      await page.getByRole("button", { name: "Convert all inherited access to direct roles" }).click();
      await expect(page.getByText(/Converted \d+ users? to direct roles\./)).toBeVisible();
      const memberRow = page.locator("tr", { hasText: PERSONAS.projectMgrGamma.name });
      // A user with both a direct grant and an inherited one shows "Direct and group" as the row's summary button; the
      // per-source breakdown (both lines) is behind the same popover as above.
      await memberRow.getByRole("button", { name: "Direct and group" }).click();
      const popover = page.getByRole("dialog", { name: `${PERSONAS.projectMgrGamma.name}'s access sources` });
      await expect(popover.getByText(/Direct \(Stakeholder\)/)).toBeVisible();
      await expect(popover.getByText(/Inherited from/)).toBeVisible();
      await page.keyboard.press("Escape");

      // Materialize is a one-way, permanent grant: revert it through a direct API call so repeated runs against the same
      // database stay idempotent, leaving Gamma-4 at "stakeholder access purely via inheritance".
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
    // undone by an onCleanup (afterEach) so a mid-test failure or timeout can't leave this
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

    // No project auto-creates a group, so this test maintains its own dedicated, fixed-name custom group for the
    // project-referencing-group case, created idempotently (get-or-create) so the defensive `cleanup()` below, and a
    // fresh run after one that failed mid-test, find the same group rather than accumulating duplicates.
    const sourceRefGroupName = "E2E Gamma-1 Source Ref Group";
    async function ensureSourceRefGroup(): Promise<{ id: string; name: string }> {
      const groups: { id: string; name: string }[] = await page
        .request.get(`http://localhost:8000/api/v1/projects/${gamma1Id}/groups`, { headers: authHeaders })
        .then((r) => r.json());
      const existing = groups.find((g) => g.name === sourceRefGroupName);
      if (existing) return existing;
      // `ProjectGroupCreate` takes no role: the group is created bare, since this test exercises only the group's
      // project-reference UI, never its granted access.
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
    // Undoes both shared-fixture mutations even if this test fails or times
    // out (afterEach via onCleanup) — the API equivalent of `cleanup()` above.
    onCleanup(async (request) => {
      const headers = await apiHeaders(request, PERSONAS.orgAdminGamma.email);
      await request.delete(`http://localhost:8000/api/v1/projects/${gamma1Id}/member-sources/${gamma2Id}`, { headers });
      const groups: { id: string; name: string; member_source_project_ids: string[] }[] = await (
        await request.get(`http://localhost:8000/api/v1/projects/${gamma1Id}/groups`, { headers })
      ).json();
      const membersGroup = groups.find((g) => g.name === sourceRefGroupName);
      if (membersGroup?.member_source_project_ids.includes(gamma2Id)) {
        await request.delete(`http://localhost:8000/api/v1/projects/${gamma1Id}/groups/${membersGroup.id}/members/${gamma2Id}`, { headers });
      }
    });
    await test.step("add Gamma-2 as a 'Mirror all roles' member source of Gamma-1 (unrelated projects, not parent/child)", async () => {
      await openProjectByName(page, PROJECT_NAMES.gamma1);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      // "Member sources" render on the Groups tab as a type-badged row in the same table as real project groups: a `<tr>`
      // with no `<Link>` on its name (read-only detail; a real group row keeps the click-to-open affordance) and two
      // `.badge` spans (Type, then mode).
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

    await test.step("Gamma-1's own dedicated source-ref group can also define a member as 'Gamma-2's members' directly (get-or-created above, not a per-run throwaway one — `DELETE .../groups/{id}` exists, but this test doesn't need it, and a fixed name lets a defensive re-run's own cleanup() find it)", async () => {
      await selectProjectAdminGroup(page, "Project groups");
      const panel = await openProjectGroupPanel(page, sourceRefGroup.name);
      await panel.getByRole("combobox", { name: "Referenced project" }).selectOption({ label: PROJECT_NAMES.gamma2 });
      await panel.getByRole("button", { name: "Reference another project's members…" }).click();
      await expect(panel.getByText(`${PROJECT_NAMES.gamma2}'s members`)).toBeVisible();
      // The referenced-project line also links to that project's
      // own new Members page now, with a "this is live" clarifying hint.
      await expect(panel.getByRole("link", { name: "View members" })).toBeVisible();
      // Scoped to the hint's `<p>` element (`viaProjectMembersHint`, strings.ts), not a page-wide `getByText(/Live/)`:
      // this org (Gamma) can accumulate other specs' leftover dynamically named projects (e.g. single-org-admin.spec.ts's
      // "Gamma E2E Live {timestamp}", never cleaned up by design), which also render as `<option>`s in the "Referenced
      // project" combobox, so a bare substring match can resolve to one of those and violate strict mode.
      await expect(panel.locator("p", { hasText: "Live" })).toBeVisible();
      await page.getByRole("button", { name: "Close" }).click();
    });
  });

  test("a project manager with no org-level role can create a sub-project under a project they manage, but cannot detach it until granted org rights", async ({
    page,
  }) => {
    const suffix = Date.now();
    const childName = `Relaxed Path Child ${suffix}`;

    // This test grants `projectMgrGamma` the org-wide "Project creator" role partway through (the third step below) to
    // prove the detach-guard's success path. Left in place, it would change this persona from "a plain project manager
    // with no org-level role" for other specs (the next test in this file expects it to be blocked from creating a
    // sub-project once relaxed child creation is off). The onCleanup (afterEach) revokes the grant even if this test
    // fails or times out; it is a no-op if the grant was never made.
    onCleanup(async (request) => {
      const headers = await apiHeaders(request, PERSONAS.orgAdminGamma.email);
      const orgId = await gammaOrgId(request, headers);
      const users: { user_id: string; email: string }[] = await (await request.get(`http://localhost:8000/api/v1/orgs/${orgId}/users`, { headers })).json();
      const userId = users.find((u) => u.email === PERSONAS.projectMgrGamma.email)?.user_id;
      if (userId) await request.delete(`http://localhost:8000/api/v1/orgs/${orgId}/users/${userId}/roles/project_creator`, { headers });
    });
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
      // Waits for the grant's `POST .../roles` response before the next line navigates away (`loginAs` calls
      // `page.goto("/login")`): otherwise `page.goto` can abort an in-flight fetch from the click's `onChange` handler and
      // the grant never reaches the server although the checkbox ticked. As in the "turn the org toggle off" step above
      // (`Promise.all([waitForResponse(...), click()])`).
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/roles") && r.request().method() === "POST"),
        page.getByRole("checkbox", { name: `Grant Project creator to ${PERSONAS.projectMgrGamma.name}` }).click(),
      ]);

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
    // This test flips a shared, org-wide toggle off partway through and must always flip it back: every other test in
    // this file (and this persona's "plain project manager" status) depends on it starting `true`. The onCleanup
    // (afterEach) restores it even if the middle assertion fails, and is idempotent: it flips the toggle only if it is off.
    onCleanup(async (request) => {
      const headers = await apiHeaders(request, PERSONAS.orgAdminGamma.email);
      const orgId = await gammaOrgId(request, headers);
      const settings = await (await request.get(`http://localhost:8000/api/v1/orgs/${orgId}/advanced-settings`, { headers })).json();
      if (!settings.allow_relaxed_child_project_creation) {
        await request.put(`http://localhost:8000/api/v1/orgs/${orgId}/advanced-settings`, {
          headers, data: { ...settings, allow_relaxed_child_project_creation: true },
        });
      }
    });
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
  });
});
