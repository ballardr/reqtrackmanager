import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Category, Component, ProjectStage } from "../api/types";
import { buildProjectListItem, buildRequirement, buildUser, withRouter, withStatefulAuth, withTerminology, withToast } from "../testing/storybook-helpers";
import { RequirementsPage } from "./RequirementsPage";

const PROJECT_ID = "project-1";

const components: Component[] = [
  { id: "c1", project_id: PROJECT_ID, name: "Authentication", prefix: "AUTH", sort_order: 0 },
  { id: "c2", project_id: PROJECT_ID, name: "Reporting", prefix: "RPT", sort_order: 1 },
];
const categories: Category[] = [
  { id: "cat1", project_id: PROJECT_ID, component_id: "c1", name: "Login", prefix: "LOG", sort_order: 0 },
  { id: "cat2", project_id: PROJECT_ID, component_id: "c2", name: "Export", prefix: "EXP", sort_order: 0 },
];
const stages: ProjectStage[] = [
  { id: "s1", project_id: PROJECT_ID, name: "Build", status: "scoping", sort_order: 0, is_current: true, approved_at: null, completed_at: null, completed_by: null, review_deadline: null },
  { id: "s2", project_id: PROJECT_ID, name: "Test", status: "scoping", sort_order: 1, is_current: false, approved_at: null, completed_at: null, completed_by: null, review_deadline: null },
];

function mockRequirementsListApis(myRoles: "manager" | "member", opts: { components?: Component[]; categories?: Category[] } = {}) {
  const comps = opts.components ?? components;
  const cats = opts.categories ?? categories;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("archived=false")) return [buildProjectListItem({ id: PROJECT_ID, my_roles: myRoles === "manager" ? ["project_manager"] : ["member"] })];
    if (path.includes("/components")) return comps;
    if (path.includes("/categories")) return cats;
    if (path.includes("/stages")) return stages;
    if (path.includes("custom-fields")) return [];
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1", name: "Atlas Platform" };
    if (path.includes("/users")) return [];
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "getPage").mockResolvedValue({
    items: [
      buildRequirement({ id: "r1", unique_code: "AUTH-LOG-001", name: "Reset password", component_id: "c1", category_id: "cat1", target_stage_id: "s1" }),
      buildRequirement({ id: "r2", unique_code: "RPT-EXP-002", name: "Nightly export", component_id: "c2", category_id: "cat2", target_stage_id: "s1", status: "approved" }),
    ],
    total: 2,
  });
}

const meta: Meta<typeof RequirementsPage> = {
  title: "Pages/RequirementsPage",
  component: RequirementsPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1" })),
    withTerminology(),
    withRouter(`/projects/${PROJECT_ID}/requirements`, "/projects/:projectId/requirements"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof RequirementsPage>;

export const TilesView: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await expect(canvas.getByText("Nightly export")).toBeInTheDocument();
  },
};

/** Style guide "Pattern: create panels, popovers, and one door for bulk":
 * "New requirement" opens a popover offering "Add one" (which itself opens
 * the create form as a `SidePanel` layer, not an inline block that reflows
 * the list underneath) and "Import from CSV" (the wizard's own file picker,
 * triggered externally — see CsvImportWizard.stories.tsx's
 * HiddenImportTriggerOpensViaRef for that half), instead of the inline
 * form and the CSV wizard's own "Import CSV" button competing as two
 * separate, permanently-visible blocks above the list. */
export const NewRequirementMenuOffersOneOrBulk: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());

    // The CSV wizard's own "Import CSV" trigger is hidden now that this
    // page's split button is the one door for both — Export/template stay,
    // combined behind their own single "Export" popover trigger (see
    // CsvImportWizard.stories.tsx's ExportMenuOffersCsvAndTemplate).
    await expect(canvas.queryByText("Import CSV")).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Export" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const menu = within(document.body).getByRole("dialog", { name: "New requirement" });
    await expect(within(menu).getByRole("button", { name: "Add one" })).toBeInTheDocument();
    await expect(within(menu).getByRole("button", { name: "Import from CSV" })).toBeInTheDocument();

    await userEvent.click(within(menu).getByRole("button", { name: "Add one" }));
    await expect(within(document.body).queryByRole("dialog", { name: "New requirement" })).toBeInTheDocument();
    // The create form is a `SidePanel` — a layer portalled to
    // `document.body`, not an inline block inside `canvasElement` — so the
    // list underneath stays untouched (Principle 3) and the field lives
    // outside `canvas`.
    await expect(within(document.body).getByPlaceholderText("Name")).toBeInTheDocument();
  },
};

export const ListView: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await expect(canvas.getByRole("columnheader", { name: "ID" })).toBeInTheDocument();
  },
};

/** Column-header sorting (2026-08 UX audit roadmap) — this list is backend-
 * paginated (`PAGE_SIZE`/`LoadMoreButton`), so a header click refetches with
 * `sort`/`order` query params rather than reordering just the loaded page. */
export const SortByNameRefetchesWithSortParams: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await userEvent.click(canvas.getByRole("button", { name: "Name" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=name&order=asc"))
    );
    // Re-queried after every click rather than cached: `reload()` clears
    // `requirements` to `null` before each refetch, which unmounts and
    // remounts the whole table (and its `<th>` nodes) — a `th` reference
    // captured before an earlier click goes stale once that happens.
    await waitFor(() =>
      expect(canvas.getByRole("button", { name: "Name" }).closest("th")).toHaveAttribute("aria-sort", "ascending")
    );

    await userEvent.click(canvas.getByRole("button", { name: "Name" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=name&order=desc"))
    );
    await waitFor(() =>
      expect(canvas.getByRole("button", { name: "Name" }).closest("th")).toHaveAttribute("aria-sort", "descending")
    );

    await userEvent.click(canvas.getByRole("button", { name: "Name" }));
    await waitFor(() => expect(api.getPage).toHaveBeenLastCalledWith(expect.not.stringContaining("sort=")));
    await waitFor(() =>
      expect(canvas.getByRole("button", { name: "Name" }).closest("th")).toHaveAttribute("aria-sort", "none")
    );
  },
};

export const FilterByStatusBadge: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    const [draftBadge] = canvas.getAllByText("Draft");
    await userEvent.click(draftBadge);
    const statusSelect = canvas.getByLabelText("Status");
    await expect(statusSelect).toHaveValue("draft");
  },
};

/** The "Include archived" filter checkbox (2026-08 UX audit roadmap:
 * unarchive endpoint + Restore button) is what makes an archived
 * requirement reachable at all — the default list excludes them entirely,
 * and `RequirementDetailPage.tsx`'s new Restore button only helps once a
 * user can get to that page in the first place. Mirrors
 * `ProjectActionsPage.tsx`'s existing `include_archived` checkbox. */
export const IncludeArchivedFilterShowsArchivedRequirement: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager");
    spyOn(api, "getPage").mockImplementation(async (path: string) => {
      if (path.includes("include_archived=true")) {
        return {
          items: [
            buildRequirement({ id: "r1", unique_code: "AUTH-LOG-001", name: "Reset password", component_id: "c1", category_id: "cat1", target_stage_id: "s1" }),
            buildRequirement({ id: "r3", unique_code: "AUTH-LOG-003", name: "Retired requirement", component_id: "c1", category_id: "cat1", target_stage_id: "s1", is_archived: true }),
          ],
          total: 2,
        };
      }
      return {
        items: [buildRequirement({ id: "r1", unique_code: "AUTH-LOG-001", name: "Reset password", component_id: "c1", category_id: "cat1", target_stage_id: "s1" })],
        total: 1,
      };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await expect(canvas.queryByText("Retired requirement")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByLabelText("Include archived"));
    await waitFor(() => expect(canvas.getByText("Retired requirement")).toBeInTheDocument());
    await expect(canvas.getByText("Archived", { selector: "span.badge" })).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager");
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No requirements to show.")).toBeInTheDocument());
  },
};

/** No components/categories yet: a manager sees a quick-create form for
 * them inside the same `SidePanel` layer the "New requirement" form itself
 * uses — not an inline block on the page. */
export const NoComponentsManagerCanCreateInline: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager", { components: [], categories: [] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Add one" }));
    const panel = within(document.body).getByRole("dialog", { name: "New requirement" });
    await waitFor(() => expect(within(panel).getByText("This project has no components or categories yet.")).toBeInTheDocument());
    await expect(within(panel).getByPlaceholderText("Prefix")).toBeInTheDocument();
  },
};

/** The same empty state for a plain member instead links to Project Admin
 * rather than offering an inline create form — `canManageProject` gates it. */
export const NoComponentsMemberSeesLinkToAdmin: Story = {
  beforeEach: () => {
    mockRequirementsListApis("member", { components: [], categories: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Add one" }));
    const panel = within(document.body).getByRole("dialog", { name: "New requirement" });
    await waitFor(() => expect(within(panel).getByRole("link", { name: "Add one in Project Admin before creating requirements." })).toBeInTheDocument());
    await expect(within(panel).queryByPlaceholderText("Prefix")).not.toBeInTheDocument();
  },
};

/** Changing the component in the create form resets the category to the
 * first one belonging to the newly-selected component — the tree/cascade
 * rule from help/01-overview.md. */
export const CreateFormCascadesCategoryOnComponentChange: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Add one" }));
    const panel = within(document.body).getByRole("dialog", { name: "New requirement" });
    await waitFor(() => expect(within(panel).getByPlaceholderText("Name")).toBeInTheDocument());
    const componentSelect = within(panel).getByLabelText("Component");
    const categorySelect = within(panel).getByLabelText("Category");
    await expect(categorySelect).toHaveValue("cat1");
    await userEvent.selectOptions(componentSelect, "c2");
    await expect(categorySelect).toHaveValue("cat2");
  },
};

/** Creating shows a success toast (Principle 7, sixth-pass audit — the
 * audit named this page specifically: it got real interaction-model work
 * this pass, `SidePanel`/`FilterBadge`, without picking up Toast, so a
 * create still just silently re-rendered the list). */
export const CreateRequirementShowsToast: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager");
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Add one" }));
    const panel = within(document.body).getByRole("dialog", { name: "New requirement" });
    await waitFor(() => expect(within(panel).getByPlaceholderText("Name")).toBeInTheDocument());
    await userEvent.type(within(panel).getByPlaceholderText("Name"), "Reset password via SMS");
    await userEvent.click(within(panel).getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/requirements`,
        expect.objectContaining({ name: "Reset password via SMS" })
      )
    );
    await expect(within(document.body).getByText("Requirement created")).toBeInTheDocument();
  },
};

/** A failed reorder now surfaces an error toast (sixth-pass audit — this
 * used to be an unhandled rejection with zero visible feedback, named
 * explicitly in the audit's "Confirmation & feedback" findings). */
export const MoveFailureShowsToast: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager");
    spyOn(api, "post").mockRejectedValue(new Error("Something went wrong."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await userEvent.click(canvas.getAllByRole("button", { name: "Move down" })[0]);
    await waitFor(() => expect(within(document.body).getByText("Something went wrong.")).toBeInTheDocument());
  },
};

/** Style guide "Pattern: bulk operations on a list" (2026-08 UX audit
 * roadmap: bulk operations on list pages, piloted here). Checking a row
 * checkbox in list view surfaces the contextual toolbar — "N selected",
 * "Clear selection", and the two bulk actions — right above the table;
 * unchecking back down to zero hides it again. */
export const BulkSelectShowsToolbar: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));

    await expect(canvas.queryByText("2 selected")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByLabelText("Select AUTH-LOG-001 Reset password"));
    await expect(canvas.getByText("1 selected")).toBeInTheDocument();
    await userEvent.click(canvas.getByLabelText("Select RPT-EXP-002 Nightly export"));
    await expect(canvas.getByText("2 selected")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Archive selected" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Move to stage" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Clear selection" }));
    await expect(canvas.queryByText("2 selected")).not.toBeInTheDocument();
  },
};

/** The header checkbox selects/deselects every currently-loaded row. */
export const SelectAllHeaderCheckbox: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));

    await userEvent.click(canvas.getByLabelText("Select all"));
    await expect(canvas.getByText("2 selected")).toBeInTheDocument();
    await userEvent.click(canvas.getByLabelText("Select all"));
    await expect(canvas.queryByText(/selected/)).not.toBeInTheDocument();
  },
};

/** A plain member (no manager/admin role) sees no checkbox column or
 * toolbar at all — bulk archive/move both require the same role the
 * single-row Archive button already requires on `RequirementDetailPage`. */
export const MemberSeesNoBulkControls: Story = {
  beforeEach: () => mockRequirementsListApis("member"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await expect(canvas.queryByLabelText("Select all")).not.toBeInTheDocument();
    await expect(canvas.queryByLabelText(/^Select AUTH-LOG-001/)).not.toBeInTheDocument();
  },
};

/** Archiving selected rows goes through the same Tier-1 `ConfirmDialog`
 * as the single-row archive button (copy pluralised, count-bearing), then
 * reports a CSV-import-wizard-style "N updated" summary via `Toast`,
 * clearing the selection and refreshing the list. */
export const BulkArchiveConfirmAndToast: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager");
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await userEvent.click(canvas.getByLabelText("Select all"));
    await userEvent.click(canvas.getByRole("button", { name: "Archive selected" }));

    const dialog = within(within(document.body).getByRole("dialog", { name: "Archive 2 requirements?" }));
    await expect(dialog.getByText("They move out of the active list, but their history and links are kept.")).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Archive selected" }));

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/requirements/r1`));
    await expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/requirements/r2`);
    await expect(within(document.body).getByText("2 updated")).toBeInTheDocument();
  },
};

/** Moving selected rows to a chosen stage: the toolbar's "Move to stage"
 * button opens a `Popover` with the same stage source the single-
 * requirement create form already uses, then a `ConfirmDialog` names the
 * count and destination stage before anything happens. */
export const BulkMoveToStageConfirmAndToast: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager");
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await userEvent.click(canvas.getByLabelText("Select all"));
    await userEvent.click(canvas.getByRole("button", { name: "Move to stage" }));

    const popover = within(within(document.body).getByRole("dialog", { name: "Move to stage" }));
    await userEvent.selectOptions(popover.getByLabelText("Target version"), "s2");
    await userEvent.click(popover.getByRole("button", { name: "Move" }));

    const dialog = within(within(document.body).getByRole("dialog", { name: 'Move 2 requirements to "Test"?' }));
    await expect(dialog.getByText("Their target stage changes immediately.")).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));

    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/requirements/r1`,
        expect.objectContaining({ target_stage_id: "s2" })
      )
    );
    await expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/requirements/r2`,
      expect.objectContaining({ target_stage_id: "s2" })
    );
    await expect(within(document.body).getByText("2 updated")).toBeInTheDocument();
  },
};

/** One failure among several selected rows doesn't silently drop it — the
 * summary toast switches to the "N updated, M failed" shape, modelled on
 * `CsvImportWizard`'s own "N created, M error(s)" wording. */
export const BulkArchivePartialFailureShowsToast: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager");
    spyOn(api, "delete").mockImplementation(async (path: string) => {
      if (path.endsWith("/r2")) throw new Error("Cannot archive a locked requirement.");
      return undefined;
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await userEvent.click(canvas.getByLabelText("Select all"));
    await userEvent.click(canvas.getByRole("button", { name: "Archive selected" }));

    const dialog = within(within(document.body).getByRole("dialog", { name: "Archive 2 requirements?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Archive selected" }));

    await waitFor(() => expect(within(document.body).getByText("1 updated, 1 failed")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...TilesView, globals: { theme: "light" } };
export const DarkTheme: Story = { ...TilesView, globals: { theme: "dark" } };
