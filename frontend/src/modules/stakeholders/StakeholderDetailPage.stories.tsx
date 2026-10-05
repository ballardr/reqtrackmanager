import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { buildProject, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildPersona, buildStakeholder, buildStakeholderScheme } from "./fixtures";
import { StakeholderDetailPage } from "./StakeholderDetailPage";
import type { CadenceHint, RepresentedLink, Stakeholder } from "./types";

const PROJECT_ID = "project-1";
const STAKEHOLDER_ID = "stakeholder-1";
const PROJECT_BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const HINT: CadenceHint = { quadrant: "manage_closely", suggested_cadence: "monthly" };

interface Mocks {
  versions?: unknown[];
  represents?: RepresentedLink[];
}

function mockDetailApis(current: Stakeholder, { versions = [], represents = [] }: Mocks = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === "/api/v1/orgs/org-1/users") return ORG_USERS;
    if (path.startsWith("/api/v1/orgs/org-1/users/search")) return { members: ORG_USERS, external: null };
    if (path === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/stakeholder`) return buildStakeholderScheme();
    if (path === `${PROJECT_BASE}/stakeholder-types`) return [{ id: "stype-regulator", name: "Regulator", display_order: 0, is_enabled: true, source: "org" }];
    if (path === `${PROJECT_BASE}/personas`) return [buildPersona(), buildPersona({ id: "persona-3", name: "Control Room Operator" })];
    if (path.startsWith(`${PROJECT_BASE}/stakeholders/cadence-hint`)) return HINT;
    if (path.endsWith(`/stakeholders/${STAKEHOLDER_ID}/personas`)) return represents;
    if (path.endsWith(`/stakeholders/${STAKEHOLDER_ID}`)) return current;
    if (path.endsWith("/versions")) return versions;
    if (path.endsWith("/comments")) return [];
    if (path.endsWith("/files")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof StakeholderDetailPage> = {
  title: "Modules/Stakeholders/StakeholderDetailPage",
  component: StakeholderDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/modules/stakeholders/stakeholders/${STAKEHOLDER_ID}`, "/projects/:projectId/modules/stakeholders/stakeholders/:stakeholderId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof StakeholderDetailPage>;

export const ActiveShowsFieldsPositionAndCadence: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Pat Regulator" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Activate" })).not.toBeInTheDocument();
    await expect(canvas.getByText("Active", { exact: true })).toBeInTheDocument();
    await expect(canvas.getByText("Traceable records.")).toBeInTheDocument();
    await expect(canvas.getByText("pat@authority.example.com")).toBeInTheDocument();
    // Levels and cadence render through their label maps/names, never the raw wire value.
    await waitFor(() => expect(canvas.getByTestId("grid-position")).toHaveTextContent("Influence: High · Interest: Medium · Manage closely"));
    await expect(canvas.getByTestId("cadence")).toHaveTextContent("Target cadence: Quarterly (suggested by their position: Monthly)");
    await expect(canvas.queryByText("quarterly")).not.toBeInTheDocument();
  },
};

export const DraftOffersActivateAndRetire: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder({ status: "draft" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Activate" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
  },
};

export const RetiredOffersReactivateAndStaysEditable: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder({ status: "retired" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Reactivate" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  },
};

export const RetireAsksForConfirmation: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder());
    spyOn(api, "post").mockResolvedValue(buildStakeholder({ status: "retired" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Retire" }));
    await userEvent.click(canvas.getByRole("button", { name: "Retire" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Retire this Stakeholder?" }));
    await userEvent.type(dialog.getByLabelText("Transition comment"), "Left the company");
    await userEvent.click(dialog.getByRole("button", { name: "Retire" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}/retire`, { comment: "Left the company" }),
    );
    await waitFor(() => expect(canvas.getByText("Retired", { exact: true })).toBeInTheDocument());
  },
};

export const DeleteIsTierTwoAndNeedsTheExactName: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder());
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Delete permanently" }));
    await userEvent.click(canvas.getByRole("button", { name: "Delete permanently" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Permanently delete Pat Regulator?" }));
    await expect(dialog.getByText(/This cannot be undone/)).toBeInTheDocument();
    const confirm = dialog.getByRole("button", { name: "Delete permanently" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(dialog.getByPlaceholderText("Pat Regulator"), "Pat Regulator");
    await expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}`));
  },
};

export const ArchiveAsksForConfirmation: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder());
    spyOn(api, "post").mockResolvedValue(buildStakeholder({ is_archived: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Archive" }));
    await userEvent.click(canvas.getByRole("button", { name: "Archive" }));
    await userEvent.click(within(within(document.body).getByRole("dialog", { name: "Archive this Stakeholder?" })).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}/archive`));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Unarchive" })).toBeInTheDocument());
  },
};

export const OrgStakeholderInProjectIsReadOnly: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder({ scope: "organization", organization_id: "org-1", project_id: null })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/organisation-wide Stakeholder/)).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "organisation view" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Delete permanently" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: "Persona to represent" })).not.toBeInTheDocument();
  },
};

export const RepresentsListsPersonasAndAddsMore: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder(), { represents: [{ link_id: "l1", id: "persona-1", name: "Field Technician", scope: "project" }] });
    spyOn(api, "post").mockResolvedValue({ link_id: "l2", id: "persona-3", name: "Control Room Operator", scope: "project" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Field Technician" })).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Persona to represent" }), "persona-3");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}/personas`, { persona_id: "persona-3" }),
    );
  },
};

export const OwnerCanBeAssigned: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder());
    spyOn(api, "put").mockResolvedValue(buildStakeholder({ owner_id: "user-2" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Stakeholder owner"));
    await userEvent.type(canvas.getByLabelText("Stakeholder owner"), "Jamie");
    await waitFor(() => canvas.getByText(/Jamie Lee/));
    await userEvent.click(canvas.getByText(/Jamie Lee/));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}`, { owner_id: "user-2" }));
  },
};

export const LinkedPlatformUserIsNamed: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder({ user_id: "user-2" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Platform user")).toBeInTheDocument());
    await waitFor(() => expect(canvas.getAllByText("Jamie Lee").length).toBeGreaterThan(0));
  },
};

export const VersionHistoryUsesLabels: Story = {
  beforeEach: () =>
    mockDetailApis(buildStakeholder({ version_number: 2 }), {
      versions: [
        { id: "v1", stakeholder_id: STAKEHOLDER_ID, version_number: 1, valid_from: "2026-01-10T09:00:00Z", valid_to: "2026-01-11T09:00:00Z", name: "Pat Regulator", status: "draft", target_cadence: null, change_note: "Initial creation.", created_at: "2026-01-10T09:00:00Z" },
        { id: "v2", stakeholder_id: STAKEHOLDER_ID, version_number: 2, valid_from: "2026-01-11T09:00:00Z", valid_to: null, name: "Pat Regulator", status: "active", target_cadence: "quarterly", change_note: "Activated", created_at: "2026-01-11T09:00:00Z" },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Version history" })).toBeInTheDocument());
    await expect(canvas.getByText("Initial creation.")).toBeInTheDocument();
    await expect(canvas.getAllByText("Quarterly").length).toBeGreaterThan(0);
  },
};

export const EditOpensThePrefilledForm: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Edit" }));
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Edit Pat Regulator" }));
    await expect(dialog.getByLabelText("Stakeholder name")).toHaveValue("Pat Regulator");
    await expect(dialog.getByLabelText("Target engagement cadence")).toHaveValue("quarterly");
  },
};

export const LightTheme: Story = { ...ActiveShowsFieldsPositionAndCadence };
export const DarkTheme: Story = { ...ActiveShowsFieldsPositionAndCadence, globals: { theme: "dark" } };
