import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { buildProjectListItem, buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ProjectListPage } from "./ProjectListPage";

function org(overrides: Partial<Organization>): Organization {
  return {
    id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
    default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
    disabled_at: null, accent_color_hex: null, header_title: null,
    email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
    ...overrides,
  };
}

const singleOrgProjects = [
  buildProjectListItem({ id: "p1", name: "Atlas Platform", organization_id: "org-1", organization_name: "Acme Corp" }),
  buildProjectListItem({ id: "p2", name: "Beacon Mobile", organization_id: "org-1", organization_name: "Acme Corp", is_favorite: true }),
];

function mockProjectListApis(opts: { orgs: Organization[]; projects: ReturnType<typeof buildProjectListItem>[] }) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/orgs?mine=true")) return opts.orgs;
    if (path.startsWith("/api/v1/projects?archived=false") && !path.includes("limit")) return opts.projects;
    return opts.projects;
  });
  spyOn(api, "getPage").mockResolvedValue({ items: opts.projects, total: opts.projects.length });
}

const meta: Meta<typeof ProjectListPage> = {
  title: "Pages/ProjectListPage",
  component: ProjectListPage,
  decorators: [withStatefulAuth(buildUser({ is_server_admin: false })), withRouter("/projects"), withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectListPage>;

export const SingleOrgTilesView: Story = {
  beforeEach: () => mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    // A single org: the org filter dropdown and per-card org name are both hidden.
    await expect(canvas.queryByText("Acme Corp")).not.toBeInTheDocument();
  },
};

export const MultipleOrgsShowOrgColumnAndFilter: Story = {
  beforeEach: () =>
    mockProjectListApis({
      orgs: [org({ id: "org-1", name: "Acme Corp" }), org({ id: "org-2", name: "Beta Inc" })],
      projects: singleOrgProjects,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByText("Acme Corp").length).toBeGreaterThan(0));
    await expect(canvas.getByText("All organisations")).toBeInTheDocument();
  },
};

export const ListView: Story = {
  beforeEach: () => mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await expect(canvas.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
  },
};

// Hierarchical projects (docs/decisions.md).
const hierarchyProjects = [
  buildProjectListItem({
    id: "parent1", name: "Platform", organization_id: "org-1", organization_name: "Acme Corp",
    children: [{ id: "child1", name: "Authentication" }],
  }),
  buildProjectListItem({
    id: "child1", name: "Authentication", organization_id: "org-1", organization_name: "Acme Corp",
    parent_project_id: "parent1", parent_project_name: "Platform",
  }),
];

function mockProjectListApisWithTree(opts: {
  orgs: Organization[];
  projects: ReturnType<typeof buildProjectListItem>[];
  treeNodes?: unknown[];
}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/orgs?mine=true")) return opts.orgs;
    if (path.startsWith("/api/v1/projects/tree")) return opts.treeNodes ?? [];
    if (path.startsWith("/api/v1/projects?archived=false") && !path.includes("limit")) return opts.projects;
    return opts.projects;
  });
  spyOn(api, "getPage").mockResolvedValue({ items: opts.projects, total: opts.projects.length });
}

export const HierarchyLabelsOnTileView: Story = {
  beforeEach: () => mockProjectListApisWithTree({ orgs: [org({})], projects: hierarchyProjects }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // "Platform" appears twice — its own tile heading, and inside "Child
    // of: Platform" on the child's tile — so assert on the unambiguous
    // "Child of:"/"Parent of:" label text instead of the name itself.
    await waitFor(() => expect(canvas.getByText("Child of:")).toBeInTheDocument());
    await expect(canvas.getByText("Parent of:")).toBeInTheDocument();
  },
};

export const HierarchyLabelsOnListView: Story = {
  beforeEach: () => mockProjectListApisWithTree({ orgs: [org({})], projects: hierarchyProjects }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByText("Platform").length).toBeGreaterThan(0));
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await expect(canvas.getByText("Child of:")).toBeInTheDocument();
  },
};

/** No hierarchy anywhere in the accessible project set: the tree toggle
 * button must not render at all (`showTreeOption`), not just be disabled —
 * a tree mode with nothing to show a hierarchy for doesn't mean anything. */
export const TreeToggleHiddenWithoutHierarchy: Story = {
  beforeEach: () => mockProjectListApisWithTree({ orgs: [org({})], projects: singleOrgProjects }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Tree view" })).not.toBeInTheDocument();
  },
};

export const TreeViewRendersHierarchy: Story = {
  beforeEach: () =>
    mockProjectListApisWithTree({
      orgs: [org({})],
      projects: hierarchyProjects,
      treeNodes: [
        {
          id: "parent1", name: "Platform", organization_id: "org-1", is_archived: false,
          children: [{ id: "child1", name: "Authentication", organization_id: "org-1", is_archived: false, children: [] }],
        },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Tree view" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Tree view" }));
    await waitFor(() => expect(canvas.getAllByRole("link", { name: "Platform" }).length).toBeGreaterThan(0));
    await expect(canvas.getByRole("link", { name: "Authentication" })).toBeInTheDocument();
  },
};

/** Favourites-only filter (2026-08 UX audit roadmap row 511) — a new
 * `FilterCheckbox` in the existing `FilterPanel`, sending `favorite_only=true`
 * on the same `GET /projects` param `FavouritesPage.tsx` already used. */
export const FavouritesOnlyFilterNarrowsTheList: Story = {
  beforeEach: () => mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("checkbox", { name: "Favourites only" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("favorite_only=true"))
    );
  },
};

/** `Pattern: role display` (2026-08 UX audit roadmap row 510) — a user
 * holding both `project_manager` and a lower tier for the same project (a
 * data shape the effective-role resolver can genuinely produce, via
 * different group memberships) shows only "Project manager," not every
 * role held. */
export const RoleBadgesCollapseToTheEffectiveHighest: Story = {
  beforeEach: () =>
    mockProjectListApis({
      orgs: [org({})],
      projects: [
        buildProjectListItem({
          id: "p1", name: "Atlas Platform", organization_id: "org-1", organization_name: "Acme Corp",
          my_roles: ["project_manager", "stakeholder"],
        }),
        buildProjectListItem({
          id: "p2", name: "Beacon Mobile", organization_id: "org-1", organization_name: "Acme Corp",
          my_roles: ["project_administrator", "stakeholder"],
        }),
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    // p1: manager + stakeholder held -> manager alone (top tier wins).
    await expect(canvas.getByText("Your roles: Project manager")).toBeInTheDocument();
    // p2: administrator + stakeholder held, no manager -> both shown (tied tier).
    await expect(canvas.getByText("Your roles: Project administrator, Stakeholder")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockProjectListApis({ orgs: [org({})], projects: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No projects to show.")).toBeInTheDocument());
  },
};

/** Style guide "Pattern: modal dialog for entity create/rename" — "New
 * project" opens a `Modal` instead of a permanently-visible inline block
 * that reflows the list underneath it. */
export const CreateProjectFormOpens: Story = {
  beforeEach: () => {
    mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects });
    spyOn(api, "post").mockResolvedValue({ id: "new-project" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());

    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: /New project/ }));
    const dialog = body.getByRole("dialog", { name: "New project" });
    const createButton = within(dialog).getByRole("button", { name: "Create" });
    await expect(createButton).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Name"), "New Project");
    await expect(createButton).toBeEnabled();
  },
};

/** Creating shows a success toast in addition to navigating to the new
 * project (Principle 7, sixth-pass audit) — the toast is mounted at the
 * app root, so it persists across the navigation the create triggers. */
export const CreateProjectShowsToast: Story = {
  beforeEach: () => {
    mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects });
    spyOn(api, "post").mockResolvedValue({ id: "new-project" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /New project/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New project" });
    await userEvent.type(within(dialog).getByLabelText("Name"), "New Project");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/projects", expect.objectContaining({ name: "New Project" })));
    await expect(within(document.body).getByText("Project created")).toBeInTheDocument();
  },
};

/** Cancelling the modal creates nothing and leaves the list untouched. */
export const CreateProjectModalCancel: Story = {
  beforeEach: () => {
    mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects });
    spyOn(api, "post").mockResolvedValue({ id: "new-project" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /New project/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New project" });
    await userEvent.type(within(dialog).getByLabelText("Name"), "Discarded Project");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** Picking an import file replaces the (otherwise silently-disappearing)
 * template picker with an explanatory note, rather than the field simply
 * vanishing with no indication of why (2026-08 UX audit, "How things get
 * created" — a small usability fix noted alongside this item's own
 * container-swap scope). */
export const CreateProjectImportFileHidesTemplateWithNote: Story = {
  beforeEach: () =>
    mockProjectListApis({
      orgs: [org({ default_template_project_id: null })],
      projects: [
        ...singleOrgProjects,
        buildProjectListItem({ id: "tpl1", name: "Standard Template", organization_id: "org-1", organization_name: "Acme Corp", is_template: true }),
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /New project/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New project" });

    await expect(within(dialog).getByText("Create from template")).toBeInTheDocument();
    const fileInput = dialog.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["fake zip content"], "bundle.zip", { type: "application/zip" });
    await userEvent.upload(fileInput, file);

    await expect(within(dialog).queryByText("Create from template")).not.toBeInTheDocument();
    await expect(
      within(dialog).getByText("A bundle brings its own structure, so template selection doesn't apply once a file is chosen above.")
    ).toBeInTheDocument();
  },
};

/** can_be_parent (docs/decisions.md) defaults to false — with nothing
 * eligible in the org, the "Parent project" field doesn't render at all
 * rather than showing a picker with only "None" in it. */
export const CreateProjectHidesParentFieldWithNoEligibleCandidates: Story = {
  beforeEach: () => {
    mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects });
    spyOn(api, "post").mockResolvedValue({ id: "new-project" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /New project/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New project" });
    await expect(within(dialog).queryByText("Parent project")).not.toBeInTheDocument();
  },
};

/** Once at least one project in the org has opted in (can_be_parent), the
 * field appears and offers it. */
export const CreateProjectOffersEligibleParent: Story = {
  beforeEach: () => {
    mockProjectListApis({
      orgs: [org({})],
      projects: [...singleOrgProjects, buildProjectListItem({ id: "p3", name: "Eligible Parent", organization_id: "org-1", organization_name: "Acme Corp", can_be_parent: true })],
    });
    spyOn(api, "post").mockResolvedValue({ id: "new-project" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /New project/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New project" });
    await expect(within(dialog).getByText("Parent project")).toBeInTheDocument();
    // Not offered: opted-out sibling projects.
    await expect(within(dialog).queryByRole("option", { name: "Beacon Mobile" })).not.toBeInTheDocument();
    await expect(within(dialog).getByRole("option", { name: "Eligible Parent" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...SingleOrgTilesView, globals: { theme: "light" } };
export const DarkTheme: Story = { ...SingleOrgTilesView, globals: { theme: "dark" } };
