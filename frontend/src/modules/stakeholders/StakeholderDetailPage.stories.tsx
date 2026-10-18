import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgGroup, OrgUser, Principal, ProjectGroup } from "../../api/types";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { buildProject, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildPersona, buildStakeholder, buildStakeholderGroup, buildStakeholderScheme } from "./fixtures";
import { StakeholderDetailPage } from "./StakeholderDetailPage";
import type { CadenceHint, HeldNeed, RepresentedLink, Stakeholder, StakeholderEngagement } from "./types";
import { chooseRecordAction, recordActionNames } from "../../testing/recordActions";

const PROJECT_ID = "project-1";
const STAKEHOLDER_ID = "stakeholder-1";
const PROJECT_BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];


const ORG_GROUPS: OrgGroup[] = [
  { id: "group-1", name: "Platform Architecture", member_user_ids: ["user-2"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const PROJECT_GROUPS: ProjectGroup[] = [
  { id: "pgroup-1", name: "Release board", roles: [], member_user_ids: ["user-2"], member_org_group_ids: [], member_source_project_ids: [] },
];
const TEAM: Principal = { type: "org_group", id: "group-1", label: "Platform Architecture", member_count: 3, exists: true };

const HINT: CadenceHint = { quadrant: "manage_closely", suggested_cadence: "monthly" };

interface Mocks {
  versions?: unknown[];
  represents?: RepresentedLink[];
  needs?: HeldNeed[];
  /** The stakeholder's engagement timeline. */
  engagements?: StakeholderEngagement[];
}

const LINKED_PAIN_POINT = buildGraphNode({ type: "pain_point", id: "pp-1", type_label: "Pain Point", label: "Reports arrive late", status: null });

const DETAIL_GROUPS = [
  buildStakeholderGroup({ id: "client", name: "Client" }),
  buildStakeholderGroup({ id: "pilot", scope: "project", organization_id: null, project_id: PROJECT_ID, name: "Pilot users", parent_group_id: "client" }),
];

function mockDetailApis(current: Stakeholder, { versions = [], represents = [], needs = [], engagements = [] }: Mocks = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === "/api/v1/orgs/org-1/groups") return ORG_GROUPS;
    if (path === `/api/v1/projects/${PROJECT_ID}/groups`) return PROJECT_GROUPS;
    if (path === "/api/v1/orgs/org-1/users") return ORG_USERS;
    if (path.startsWith("/api/v1/orgs/org-1/users/search")) return { members: ORG_USERS, external: null };
    if (path === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/stakeholder`) return buildStakeholderScheme();
    if (path === `${PROJECT_BASE}/stakeholder-groups`) return DETAIL_GROUPS;
    if (path === `${PROJECT_BASE}/stakeholder-types`) return [{ id: "stype-regulator", name: "Regulator", display_order: 0, is_enabled: true, source: "org" }];
    if (path === `${PROJECT_BASE}/personas`) return [buildPersona(), buildPersona({ id: "persona-3", name: "Control Room Operator" })];
    if (path.startsWith(`${PROJECT_BASE}/stakeholders/cadence-hint`)) return HINT;
    if (path.includes(`/artefacts/stakeholder/${STAKEHOLDER_ID}/link-graph`)) return buildGraph([[LINKED_PAIN_POINT]]);
    if (path.endsWith(`/stakeholders/${STAKEHOLDER_ID}/personas`)) return represents;
    if (path.endsWith(`/stakeholders/${STAKEHOLDER_ID}/needs`)) return needs;
    if (path.endsWith(`/stakeholders/${STAKEHOLDER_ID}/engagements`)) return engagements;
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
    await waitFor(() => canvas.getByRole("button", { name: "Stakeholder actions" }));
    await chooseRecordAction(canvas, "Stakeholder", "Delete permanently");
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
    await waitFor(() => canvas.getByRole("button", { name: "Stakeholder actions" }));
    await chooseRecordAction(canvas, "Stakeholder", "Archive");
    await userEvent.click(within(within(document.body).getByRole("dialog", { name: "Archive this Stakeholder?" })).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}/archive`));
    await waitFor(async () => expect(await recordActionNames(canvas, "Stakeholder")).toContain("Unarchive"));
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
    await expect(await recordActionNames(canvas, "Stakeholder")).not.toContain("Delete permanently");
    await expect(canvas.queryByRole("combobox", { name: "Persona to represent" })).not.toBeInTheDocument();
  },
};

const ORG_IN_PROJECT = { scope: "organization", organization_id: "org-1", project_id: null, project_hidden: false } as const;

export const OrgStakeholderCanBeHiddenFromTheProject: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder(ORG_IN_PROJECT));
    spyOn(api, "put").mockResolvedValue(buildStakeholder({ ...ORG_IN_PROJECT, project_hidden: true, hidden_override: true, hidden_source: "project" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("project-visibility")).toHaveTextContent("Visible"));
    await userEvent.click(canvas.getByRole("button", { name: "Hide from this project" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Hide Pat Regulator from this project?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Hide" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}/visibility`, { hidden: true }),
    );
  },
};

export const ExplicitlyShownOrgStakeholderCanRevertToInherited: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder({ ...ORG_IN_PROJECT, hidden_override: false, hidden_source: "project" }));
    spyOn(api, "delete").mockResolvedValue(buildStakeholder({ ...ORG_IN_PROJECT, project_hidden: true, hidden_source: "ancestor_project" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("project-visibility")).toHaveTextContent("Shown, although a parent project hides it"));
    await userEvent.click(canvas.getByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}/visibility`));
  },
};

export const ProjectStakeholderHasNoVisibilityControl: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Pat Regulator" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Hide from this project" })).not.toBeInTheDocument();
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
    await userEvent.click(canvas.getByRole("button", { name: "Add to Represents these Personas" }));
    const popover = within(within(document.body).getByRole("dialog", { name: "Add to Represents these Personas" }));
    await userEvent.selectOptions(popover.getByRole("combobox", { name: "Persona to represent" }), "persona-3");
    await userEvent.click(popover.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}/personas`, { persona_id: "persona-3" }),
    );
  },
};

export const OwnerCanBeAssigned: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder());
    spyOn(api, "put").mockResolvedValue(buildStakeholder({ owner: { type: "user", id: "user-2", label: "Jamie Lee", member_count: null, exists: true } }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Stakeholder owner"));
    await userEvent.type(canvas.getByLabelText("Stakeholder owner"), "Jamie");
    await waitFor(() => canvas.getByText(/Jamie Lee/));
    await userEvent.click(canvas.getByText(/Jamie Lee/));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}`, { owner: { type: "user", id: "user-2" } }));
  },
};

/** A project group can own a project stakeholder; the picked group goes out as a typed principal. */
export const OwnerCanBeAProjectGroup: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder());
    spyOn(api, "put").mockResolvedValue(buildStakeholder());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Stakeholder owner"));
    await userEvent.type(canvas.getByLabelText("Stakeholder owner"), "release");
    await userEvent.click(await canvas.findByText("Release board"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}`, { owner: { type: "project_group", id: "pgroup-1" } }));
  },
};

/** A group owner shows its name and kind. */
export const GroupOwnerIsNamedWithItsKind: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder({ owner: TEAM })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Platform Architecture")).toBeInTheDocument());
    await expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument();
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
        { id: "v1", stakeholder_id: STAKEHOLDER_ID, version_number: 1, valid_from: "2026-01-10T09:00:00Z", valid_to: "2026-01-11T09:00:00Z", name: "Pat Regulator", status: "draft", target_cadence: null, owner: null, change_note: "Initial creation.", created_at: "2026-01-10T09:00:00Z" },
        { id: "v2", stakeholder_id: STAKEHOLDER_ID, version_number: 2, valid_from: "2026-01-11T09:00:00Z", valid_to: null, name: "Pat Regulator", status: "active", target_cadence: "quarterly", owner: TEAM, change_note: "Activated", created_at: "2026-01-11T09:00:00Z" },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Versions" })).toBeInTheDocument());
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

export const ListsTheNeedsTheStakeholderHas: Story = {
  beforeEach: () =>
    mockDetailApis(buildStakeholder(), { needs: [{ link_id: "n1", id: "need-1", name: "Diagnose faults quickly", status: "active" }] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: "Diagnose faults quickly (Active)" });
    await expect(link).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/stakeholders/needs/need-1`);
  },
};

/** The engagement timeline lists the stakeholder's contacts newest first, and "Last engaged" reads the derived date. */
export const ShowsTheEngagementTimelineAndLastEngaged: Story = {
  beforeEach: () =>
    mockDetailApis(buildStakeholder({ last_engaged: "2026-04-02" }), {
      engagements: [
        { id: "e2", title: "Evidence follow-up", channel: "email", engagement_date: "2026-04-02" },
        { id: "e1", title: "Quarterly review", channel: "meeting", engagement_date: "2026-03-12" },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: "2026-04-02 · Email · Evidence follow-up" });
    await expect(link).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/stakeholders/engagements/e2`);
    await expect(canvas.getByTestId("last-engaged")).toHaveTextContent("Last engaged: 2026-04-02");
  },
};

/** A stakeholder who has never been engaged says so. */
export const NeverEngagedSaysSo: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder({ last_engaged: null })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("last-engaged")).toHaveTextContent("Last engaged: Never"));
    await waitFor(() => expect(canvas.getByText("No engagements logged yet.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ActiveShowsFieldsPositionAndCadence };
export const DarkTheme: Story = { ...ActiveShowsFieldsPositionAndCadence, globals: { theme: "dark" } };

/** Links live in the shared Links panel beside the page. */
export const LinksPanelShowsLinks: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reports arrive late" })).toBeInTheDocument());
  },
};

const PILOT_REF = { id: "pilot", name: "Pilot users", scope: "project" as const, parent_group_id: "client" };

export const ShowsTheStakeholdersGroupsWithTheirPath: Story = {
  beforeEach: () => mockDetailApis(buildStakeholder({ groups: [PILOT_REF] })),
  play: async ({ canvasElement }) => {
    const badge = await within(canvasElement).findByText("Pilot users", { selector: ".badge" });
    await expect(badge).toHaveAttribute("title", "Client › Pilot users");
  },
};

export const GroupsAreChangedWithOneSave: Story = {
  beforeEach: () => {
    mockDetailApis(buildStakeholder({ groups: [] }));
    spyOn(api, "put").mockResolvedValue([PILOT_REF]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Project groups" }));
    // Organisation groups show in the tree but belong to the organisation view.
    await expect(within(document.body).getByRole("checkbox", { name: "Client" })).toBeDisabled();
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Pilot users" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save groups" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/stakeholders/${STAKEHOLDER_ID}/groups`, { group_ids: ["pilot"] }),
    );
    await waitFor(() => expect(canvas.getByText("Pilot users", { selector: ".badge" })).toBeInTheDocument());
  },
};
