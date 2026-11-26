import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { DRAFT_ARTEFACT_ID } from "../api/artefactLinks";
import { api } from "../api/client";
import type { Category, Component, ProjectStage } from "../api/types";
import { buildCandidate, buildGraph, buildOption } from "../testing/artefactLinksFixtures";
import { buildRecordColumns } from "../testing/recordTablesFixtures";
import { buildChangeRequest, buildRequirement, buildUser, withRouter, withStatefulAuth, withTerminology, withToast, buildRequirementTypes } from "../testing/storybook-helpers";
import { ChangeRequestsPage } from "./ChangeRequestsPage";
import { chooseExport } from "../testing/listActionsMenu";

const PROJECT_ID = "project-1";

const components: Component[] = [{ id: "c1", project_id: PROJECT_ID, name: "Authentication", prefix: "AUTH", sort_order: 0 }];
const categories: Category[] = [{ id: "cat1", project_id: PROJECT_ID, component_id: "c1", name: "Login", prefix: "LOG", sort_order: 0 }];
const stages: ProjectStage[] = [
  { id: "s1", project_id: PROJECT_ID, name: "Build", workflow_id: "wf1", workflow_name: "Standard", phase_id: "ph-scoping", phase_name: "Scoping", phase_kind: "open", sort_order: 0, is_current: true, approved_at: null, completed_at: null, completed_by: null, owner: null, review_deadline: null },
];
// "approved" (locked): a modify change request can only target a locked requirement; a draft
// is absent from the "Select a requirement" dropdown.
const requirement = buildRequirement({
  id: "req-1", unique_code: "AUTH-LOG-001", name: "Reset password", component_id: "c1", category_id: "cat1",
  target_stage_id: "s1", reasoning: "Locked-out users need a self-service recovery path.", status: "approved",
});

/** `links` also answers the Links finder's reads (the proposed-links section), as a user who may link would see them. */
function mockChangeRequestsListApis({ links = false }: { links?: boolean } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/records/change_request/columns")) {
      return buildRecordColumns({
        label: "Change requests", importable: false, can_import: false,
        not_importable_reason: "A change request is a proposal, so it is authored in its form, not in a file.",
      });
    }
    if (links && path.includes("/link-graph")) return buildGraph([], { can_link: true });
    if (links && path.includes("/link-types")) return [buildOption({ other_types: [{ type: "decision", label: "Decision", can_create: false }] })];
    if (links && path.includes("/link-candidates")) return { items: [buildCandidate()], truncated: false };
    if (links && path.includes("/link-browse")) return null;
    if (links && path.includes("/link-candidate-projects")) return { items: [], truncated: false };
    if (path.endsWith("/requirements")) return [requirement];
    if (path.includes("/components")) return components;
    if (path.includes("/categories")) return categories;
    if (path.includes("custom-fields")) return [];
    if (path.endsWith("/requirement-types")) return buildRequirementTypes();
    if (path.includes("/stages")) return stages;
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
    if (path.includes("/users")) return [];
    if (path.includes("/resources")) return [];
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "getPage").mockResolvedValue({
    items: [
      buildChangeRequest({ id: "cr1", requirement_id: "req-1", status: "submitted", proposed_target_stage_id: "s1" }),
      buildChangeRequest({ id: "cr2", requirement_id: "req-1", kind: "new_requirement", status: "draft", proposed_name: "Add SSO login" }),
    ],
    total: 2,
  });
}

const meta: Meta<typeof ChangeRequestsPage> = {
  title: "Pages/ChangeRequestsPage",
  component: ChangeRequestsPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1" })),
    withTerminology(),
    withRouter(`/projects/${PROJECT_ID}/change-requests`, "/projects/:projectId/change-requests"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ChangeRequestsPage>;

export const ListOfChangeRequests: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Add SSO login" })).toBeInTheDocument();
    // Each request leads with its record code in a Code column.
    await expect(canvas.getAllByText(/CR-\d{3}/).length).toBeGreaterThan(0);
  },
};

/** Target, Level and Created order the whole list on the server through the header. */
export const TargetAndLevelHeadersSortOnTheServer: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    for (const [header, key] of [["Target", "target"], ["Level", "level"]] as const) {
      await userEvent.click(canvas.getByRole("button", { name: header }));
      await waitFor(() => expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining(`sort=${key}&order=asc`)));
    }
  },
};

/** Every column is drawn by default; the chooser hides Created and the reset brings it back. */
export const ColumnChooserHidesAnOptionalColumn: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    for (const name of ["Code", "Name", "Target", "Level", "Created"]) {
      await expect(canvas.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    await userEvent.click(canvas.getByRole("button", { name: "Choose columns" }));
    const dialog = await screen.findByRole("dialog", { name: "Columns" });
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Created" }));
    await expect(canvas.queryByRole("columnheader", { name: "Created" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Show the default columns" }));
    await expect(canvas.getByRole("columnheader", { name: "Created" })).toBeInTheDocument();
  },
};

/** The list opens by code ascending and Sort by offers Created and Modified; choosing Modified newest first is sent to the server. */
export const SortFieldOrdersByModifiedNewestFirst: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    await expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=unique_code&order=asc"));
    const sortBy = canvas.getByRole("combobox", { name: "Sort by" });
    await expect(within(sortBy).getAllByRole("option").map((o) => o.textContent)).toEqual(["Code", "Name", "Status", "Target", "Level", "Components", "External references", "Created", "Modified"]);
    await userEvent.selectOptions(sortBy, "modified");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Order" }), "desc");
    await waitFor(() => expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=modified&order=desc")));
  },
};

/** The shared list actions: Export downloads the list with the page's filters (the default "Active" view); a change request has no Import. */
export const ExportIsOnTheTitleRowAndThereIsNoImport: Story = {
  beforeEach: () => {
    mockChangeRequestsListApis();
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code,title\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    await chooseExport(canvas, "CSV");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith("/api/v1/projects/project-1/records/change_request/export?active_only=true&sort=unique_code&order=asc"));
    await expect(canvas.queryByText("Import")).not.toBeInTheDocument();
  },
};

/** A refused read shows what failed with Retry, not a spinner that never ends; Retry reads the list again. */
export const FailedLoadOffersRetry: Story = {
  beforeEach: () => {
    mockChangeRequestsListApis();
    const answer = (api.getPage as unknown as { getMockImplementation: () => () => Promise<unknown> }).getMockImplementation();
    let calls = 0;
    spyOn(api, "getPage").mockImplementation((async () => {
      calls += 1;
      if (calls === 1) throw new Error("The server is down.");
      return answer?.();
    }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("alert")).toHaveTextContent("The change request list could not be loaded.");
    await userEvent.click(canvas.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
  },
};

export const EmptyState: Story = {
  beforeEach: () => {
    mockChangeRequestsListApis();
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No change requests to show.")).toBeInTheDocument());
  },
};

/**
 * Ticking a field's checkbox pre-fills its editor from the selected requirement's current value;
 * an untouched field is neither shown nor submitted (help/03-change-requests.md). The create form
 * is a `Modal` portalled to `document.body`, so its fields are queried with `within(document.body)`.
 */
export const ModifyRequirementFieldTogglePrefills: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() => expect(within(dialog).getByText("Fields to change")).toBeInTheDocument());
    // Untoggled: no editor for Reasoning is rendered at all.
    await expect(within(dialog).queryByDisplayValue(requirement.reasoning)).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Reasoning" }));
    await expect(within(dialog).getByDisplayValue(requirement.reasoning)).toBeInTheDocument();
    // Untick again: the editor (and its value) disappears.
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Reasoning" }));
    await expect(within(dialog).queryByDisplayValue(requirement.reasoning)).not.toBeInTheDocument();
  },
};

export const ModifyRequirementCreateDisabledUntilFieldSelected: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() => expect(within(dialog).getByText("Fields to change")).toBeInTheDocument());
    await userEvent.type(within(dialog).getByLabelText("Reason for change"), "Extend the recovery window");
    await expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();
    await expect(within(dialog).getByText("Select at least one field to change.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Reasoning" }));
    await expect(within(dialog).getByRole("button", { name: "Create" })).toBeEnabled();
  },
};

/** Switching to "New requirement" replaces the field-toggle form with a plain create form. */
export const NewRequirementKindShowsPlainCreateForm: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() => expect(within(dialog).getByText("Modify requirement")).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("radio", { name: "New requirement" }));
    await expect(within(dialog).getByLabelText("Proposed name")).toBeInTheDocument();
    await expect(within(dialog).queryByText("Fields to change")).not.toBeInTheDocument();
  },
};

/** Column-header sorting on the server-paginated list refetches with `sort`/`order` rather than
 * reordering the loaded page; sorting applies in list view only. */
export const SortByCreatedRefetchesWithSortParams: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await userEvent.click(canvas.getByRole("button", { name: "Created" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=created&order=asc"))
    );
    const th = canvas.getByRole("button", { name: "Created" }).closest("th");
    await expect(th).toHaveAttribute("aria-sort", "ascending");

    await userEvent.click(canvas.getByRole("button", { name: "Created" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=created&order=desc"))
    );
  },
};

/** The free-text search is sent to the server so it finds a change request on any page. */
export const SearchRefetchesWithSearchParam: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const searchBox = await canvas.findByPlaceholderText("Search by name, reason or requirement ID");
    await userEvent.type(searchBox, "telemetry");
    await waitFor(() => expect(api.getPage).toHaveBeenCalledWith(expect.stringContaining("search=telemetry")));
  },
};

export const SubmitCreatesChangeRequest: Story = {
  beforeEach: () => {
    mockChangeRequestsListApis();
    spyOn(api, "post").mockResolvedValue({ id: "cr-new", unique_code: "CR-007" } as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() => expect(within(dialog).getByText("Fields to change")).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Reasoning" }));
    await userEvent.type(within(dialog).getByLabelText("Reason for change"), "Extend the recovery window");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/change-requests`,
        expect.objectContaining({ kind: "modify_requirement", changed_fields: ["reasoning"] })
      )
    );
    // Principle 7: every mutation ends with feedback.
    await expect(within(document.body).getByText("Change request CR-007 created.")).toBeInTheDocument();
    // The Modal closes itself on a successful create (`setShowForm(false)`).
    await expect(dialog).not.toBeInTheDocument();
  },
};

/** A modify request can carry proposed links. The finder reads the selected requirement; the
 * links are sent with the request (display-only fields dropped) and nothing is created by the dialog. */
export const ModifyRequestSendsItsProposedLinks: Story = {
  beforeEach: () => {
    mockChangeRequestsListApis({ links: true });
    spyOn(api, "post").mockResolvedValue({ id: "cr-new", unique_code: "CR-007" } as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Add a link" }));
    const picker = within(await within(document.body).findByRole("dialog", { name: "Add a link" }));
    await picker.findByRole("option", { name: "DEC-002 Use Redis" });
    await userEvent.selectOptions(picker.getByLabelText("Record"), "dec-2");
    await userEvent.click(picker.getByRole("button", { name: "Add to the request" }));
    await waitFor(() => expect(within(dialog).getByText("DEC-002 Use Redis")).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Reasoning" }));
    await userEvent.type(within(dialog).getByLabelText("Reason for change"), "Trace the decision");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/change-requests`,
        expect.objectContaining({
          kind: "modify_requirement",
          proposed_links: [{
            link_type_id: "lt-related", direction: "outgoing", other_type: "decision", other_id: "dec-2",
            other_project_id: undefined,
          }],
        })
      )
    );
  },
};

/** A new-requirement request asks the finder about the draft id, since the requirement does not exist yet. */
export const NewRequirementRequestSearchesAsADraft: Story = {
  beforeEach: () => mockChangeRequestsListApis({ links: true }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await userEvent.click(within(dialog).getByRole("radio", { name: /New/ }));
    await within(dialog).findByRole("button", { name: "Add a link" });
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/artefacts/requirement/${DRAFT_ARTEFACT_ID}/link-types`)
    );
  },
};

/** Without the right to link requirements the section is not offered at all. */
export const NoProposedLinksSectionWithoutTheRightToLink: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() => expect(within(dialog).getByText("Fields to change")).toBeInTheDocument());
    await expect(within(dialog).queryByRole("button", { name: "Add a link" })).not.toBeInTheDocument();
  },
};

/** The status filter defaults to "Active" (`active_only=true`, no `cr_status`), hiding terminal
 * statuses; "All statuses" sends neither parameter. */
export const StatusFilterDefaultsToActiveAndWidensToAll: Story = {
  beforeEach: () => {
    mockChangeRequestsListApis();
    spyOn(api, "getPage").mockImplementation(async (path: string) => {
      if (path.includes("active_only=true")) {
        return {
          items: [buildChangeRequest({ id: "cr1", requirement_id: "req-1", status: "submitted", proposed_target_stage_id: "s1" })],
          total: 1,
        };
      }
      return {
        items: [
          buildChangeRequest({ id: "cr1", requirement_id: "req-1", status: "submitted", proposed_target_stage_id: "s1" }),
          buildChangeRequest({ id: "cr3", requirement_id: "req-1", kind: "new_requirement", status: "approved", proposed_name: "Approved CR" }),
        ],
        total: 2,
      };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(api.getPage).toHaveBeenCalledWith(expect.stringContaining("active_only=true")));
    const statusSelect = canvas.getByLabelText("Status");
    await expect(statusSelect).toHaveValue("active");
    await expect(canvas.queryByText("Approved CR")).not.toBeInTheDocument();

    await userEvent.selectOptions(statusSelect, "");
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.not.stringContaining("active_only"))
    );
    await waitFor(() => expect(canvas.getByText("Approved CR")).toBeInTheDocument());
  },
};

/** Filter options render through `CHANGE_REQUEST_STATUS_LABEL` ("In review", not "in_review"). */
export const StatusFilterOptionsUseLabelMap: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    const statusSelect = canvas.getByLabelText("Status") as HTMLSelectElement;
    const optionLabels = Array.from(statusSelect.options).map((o) => o.textContent);
    await expect(optionLabels).toContain("In review");
    await expect(optionLabels).not.toContain("in_review");
  },
};

/** A hint explains why a draft-only project offers no requirement to modify, instead of an empty select. */
export const NoLockableRequirementsShowsHint: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/requirements")) return [buildRequirement({ id: "req-draft", status: "draft" })];
      if (path.includes("/components")) return components;
      if (path.includes("/categories")) return categories;
      if (path.includes("custom-fields")) return [];
      if (path.endsWith("/requirement-types")) return buildRequirementTypes();
      if (path.includes("/stages")) return stages;
      if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
      if (path.includes("/users")) return [];
      if (path.includes("/resources")) return [];
      throw new Error(`unmocked path: ${path}`);
    });
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() =>
      expect(within(dialog).getByText("No requirements are approved yet — approve one first, or edit a draft requirement directly.")).toBeInTheDocument()
    );
    const requirementSelect = within(dialog).getByLabelText("Select a requirement") as HTMLSelectElement;
    await expect(requirementSelect.options).toHaveLength(0);
  },
};

export const LightTheme: Story = { ...ListOfChangeRequests, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListOfChangeRequests, globals: { theme: "dark" } };
