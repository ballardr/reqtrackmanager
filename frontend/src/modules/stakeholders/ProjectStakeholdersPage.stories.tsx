import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildStakeholder, buildStakeholderScheme } from "./fixtures";
import { ProjectStakeholdersPage } from "./ProjectStakeholdersPage";
import type { EffectivePersonaType, Stakeholder } from "./types";

const PROJECT_ID = "project-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;

const TYPES: EffectivePersonaType[] = [
  { id: "stype-regulator", name: "Regulator", display_order: 0, is_enabled: true, source: "org" },
  { id: "stype-off", name: "Switched off", display_order: 1, is_enabled: false, source: "project_override" },
];

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

function mockPageApis(stakeholders: Stakeholder[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`${BASE}/stakeholders`)) return stakeholders;
    if (path === `${BASE}/stakeholder-types`) return TYPES;
    if (path === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/stakeholder`) return buildStakeholderScheme();
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === "/api/v1/orgs/org-1/users") return ORG_USERS;
    if (path.startsWith("/api/v1/orgs/org-1/users/search")) return { members: ORG_USERS, external: null };
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectStakeholdersPage> = {
  title: "Modules/Stakeholders/ProjectStakeholdersPage",
  component: ProjectStakeholdersPage,
  decorators: [
    withRouter(`/projects/${PROJECT_ID}/modules/stakeholders/stakeholders`, "/projects/:projectId/modules/stakeholders/stakeholders"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectStakeholdersPage>;

export const ListsProjectAndOrgStakeholders: Story = {
  beforeEach: () =>
    mockPageApis([
      buildStakeholder(),
      buildStakeholder({
        id: "stakeholder-2", scope: "organization", organization_id: "org-1", project_id: null, name: "Sam Sponsor",
        status: "draft", stakeholder_type_name: "Project sponsor", target_cadence: "monthly", influence_level_id: "infl-low",
        interest_level_id: null,
      }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Pat Regulator")).toBeInTheDocument());
    await expect(canvas.getByText("Sam Sponsor")).toBeInTheDocument();
    // Scope, status, cadence and levels go through label maps / level names, never raw wire values.
    const table = within(canvas.getByRole("table", { name: "Stakeholders" }));
    await expect(table.getByText("Organisation")).toBeInTheDocument();
    await expect(table.getByText("Draft")).toBeInTheDocument();
    await expect(table.getByText("Quarterly")).toBeInTheDocument();
    await expect(table.getByText("Monthly")).toBeInTheDocument();
    await expect(table.getByText("High")).toBeInTheDocument();
    await expect(canvas.queryByText("organization")).not.toBeInTheDocument();
    await expect(canvas.queryByText("quarterly")).not.toBeInTheDocument();
  },
};

const ORG = { scope: "organization", organization_id: "org-1", project_id: null } as const;
const HIDDEN_BY_PROJECT = buildStakeholder({
  ...ORG, id: "stakeholder-hidden", name: "Hidden Regulator", project_hidden: true, hidden_override: true, hidden_source: "project",
});
const HIDDEN_BY_PARENT = buildStakeholder({
  ...ORG, id: "stakeholder-parent", name: "Parent-hidden Sponsor", project_hidden: true, hidden_override: null,
  hidden_source: "ancestor_project",
});

/** The list mock honouring `include_hidden`: hidden stakeholders only come back when asked for. */
function mockListWithHidden() {
  const visible = buildStakeholder({ ...ORG, id: "stakeholder-visible", name: "Visible Sponsor", project_hidden: false });
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`${BASE}/stakeholders`)) {
      return path.includes("include_hidden=true") ? [visible, HIDDEN_BY_PROJECT, HIDDEN_BY_PARENT] : [visible];
    }
    if (path === `${BASE}/stakeholder-types`) return TYPES;
    if (path === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/stakeholder`) return buildStakeholderScheme();
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === "/api/v1/orgs/org-1/users") return ORG_USERS;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

export const HiddenStakeholdersAreOnlyListedOnRequest: Story = {
  beforeEach: () => mockListWithHidden(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Visible Sponsor")).toBeInTheDocument());
    await expect(canvas.queryByText("Hidden Regulator")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByLabelText("Show hidden"));
    await waitFor(() => expect(canvas.getByText("Hidden Regulator")).toBeInTheDocument());
    // Who hid each one goes through the label map; neither raw enum value appears.
    await expect(canvas.getByText("Hidden by this project")).toBeInTheDocument();
    await expect(canvas.getByText("Hidden by a parent project")).toBeInTheDocument();
    await expect(canvas.queryByText("ancestor_project")).not.toBeInTheDocument();
  },
};

export const ShowingAProjectHiddenStakeholderDropsTheOverride: Story = {
  beforeEach: () => {
    mockListWithHidden();
    spyOn(api, "delete").mockResolvedValue(buildStakeholder({ ...ORG, id: "stakeholder-hidden", project_hidden: false }));
    spyOn(api, "put").mockResolvedValue(buildStakeholder());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Show hidden"));
    await userEvent.click(canvas.getByLabelText("Show hidden"));
    await userEvent.click(await canvas.findByRole("button", { name: "Show Hidden Regulator in this project" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/stakeholders/stakeholder-hidden/visibility`));
    await expect(api.put).not.toHaveBeenCalled();
  },
};

export const ShowingAParentHiddenStakeholderOverridesIt: Story = {
  beforeEach: () => {
    mockListWithHidden();
    spyOn(api, "delete").mockResolvedValue(buildStakeholder());
    spyOn(api, "put").mockResolvedValue(buildStakeholder({ ...ORG, project_hidden: false, hidden_override: false }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Show hidden"));
    await userEvent.click(canvas.getByLabelText("Show hidden"));
    await userEvent.click(await canvas.findByRole("button", { name: "Show Parent-hidden Sponsor in this project" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/stakeholders/stakeholder-parent/visibility`, { hidden: false }));
    await expect(api.delete).not.toHaveBeenCalled();
  },
};

export const StatusBadgeFiltersTheList: Story = {
  beforeEach: () => mockPageApis([buildStakeholder(), buildStakeholder({ id: "stakeholder-2", name: "Sam Sponsor", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Sam Sponsor"));
    await userEvent.click(canvas.getByRole("button", { name: "Draft" }));
    await waitFor(() => expect(canvas.queryByText("Pat Regulator")).not.toBeInTheDocument());
    await expect(canvas.getByText("Sam Sponsor")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No Stakeholders recorded for this project yet.")).toBeInTheDocument());
  },
};

export const CreateOffersOnlyEnabledTypes: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Stakeholder" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Stakeholder" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.getByRole("option", { name: "Regulator" })).toBeInTheDocument();
    await expect(dialog.queryByRole("option", { name: "Switched off" })).not.toBeInTheDocument();
  },
};

export const CreateStakeholder: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockResolvedValue(buildStakeholder());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Stakeholder" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Stakeholder" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Stakeholder name"), "Pat Regulator");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/stakeholders`, expect.objectContaining({ name: "Pat Regulator" })),
    );
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const CreateErrorKeepsModalOpen: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockRejectedValue(new ApiError(403, "Only a Stakeholder Owner (or admin/manager) may do this."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Stakeholder" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Stakeholder" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Stakeholder name"), "X");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(dialog.getByText("Only a Stakeholder Owner (or admin/manager) may do this.")).toBeInTheDocument());
  },
};

export const AddFromOrgUser: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockResolvedValue(buildStakeholder({ name: "Jamie Lee", user_id: "user-2" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add from org user" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add from org user" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Organisation user"), "Jamie");
    await waitFor(() => dialog.getByText(/Jamie Lee/));
    await userEvent.click(dialog.getByText(/Jamie Lee/));
    await userEvent.click(dialog.getByRole("button", { name: "Add Stakeholder" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/stakeholders/from-user`, { user_id: "user-2", stakeholder_type_id: null, role: "" }),
    );
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const AddFromOrgUserDuplicateKeepsModalOpen: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockRejectedValue(new ApiError(409, "A Stakeholder already represents this user."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add from org user" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add from org user" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Organisation user"), "Jamie");
    await waitFor(() => dialog.getByText(/Jamie Lee/));
    await userEvent.click(dialog.getByText(/Jamie Lee/));
    await userEvent.click(dialog.getByRole("button", { name: "Add Stakeholder" }));
    await waitFor(() => expect(dialog.getByText("A Stakeholder already represents this user.")).toBeInTheDocument());
  },
};

export const LoadErrorShowsMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Module is not enabled."));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Module is not enabled.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListsProjectAndOrgStakeholders };
export const DarkTheme: Story = { ...ListsProjectAndOrgStakeholders, globals: { theme: "dark" } };
