import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgGroup, OrgUser, Principal, ProjectGroup } from "../../api/types";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { buildProject, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildPersona } from "./fixtures";
import { PersonaDetailPage } from "./PersonaDetailPage";
import type { Persona } from "./types";

const PROJECT_ID = "project-1";
const PERSONA_ID = "persona-1";
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

const LINKED_PAIN_POINT = buildGraphNode({ type: "pain_point", id: "pp-1", type_label: "Pain Point", label: "Reports arrive late", status: null });

function mockDetailApis(current: Persona, versions: unknown[] = [], represented: unknown[] = [], engagements: unknown[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === "/api/v1/orgs/org-1/groups") return ORG_GROUPS;
    if (path === `/api/v1/projects/${PROJECT_ID}/groups`) return PROJECT_GROUPS;
    if (path === "/api/v1/orgs/org-1/users") return ORG_USERS;
    if (path.startsWith("/api/v1/orgs/org-1/users/search")) {
      const q = new URL(path, "http://localhost").searchParams.get("q")?.toLowerCase() ?? "";
      return { members: ORG_USERS.filter((u) => u.display_name.toLowerCase().includes(q)), external: null };
    }
    if (path === `${PROJECT_BASE}/persona-types`) return [{ id: "type-primary", name: "Primary", display_order: 0, is_enabled: true, source: "org" }];
    if (path.includes(`/artefacts/persona/${PERSONA_ID}/link-graph`)) return buildGraph([[LINKED_PAIN_POINT]]);
    if (path.endsWith(`/personas/${PERSONA_ID}/stakeholders`)) return represented;
    if (path.endsWith(`/personas/${PERSONA_ID}/needs`)) return [];
    if (path === `${PROJECT_BASE}/engagements?persona_id=${PERSONA_ID}`) return engagements;
    if (path.endsWith(`/personas/${PERSONA_ID}`)) return current;
    if (path.endsWith("/versions")) return versions;
    if (path.endsWith("/comments")) return [];
    if (path.endsWith("/files")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof PersonaDetailPage> = {
  title: "Modules/Stakeholders/PersonaDetailPage",
  component: PersonaDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/modules/stakeholders/personas/${PERSONA_ID}`, "/projects/:projectId/modules/stakeholders/personas/:personaId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof PersonaDetailPage>;

export const ActiveOffersRetire: Story = {
  beforeEach: () => mockDetailApis(buildPersona()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Field Technician" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Activate" })).not.toBeInTheDocument();
    await expect(canvas.getByText("Active", { exact: true })).toBeInTheDocument();
    await expect(canvas.getByText("Offline access.")).toBeInTheDocument();
  },
};

export const DraftOffersActivateAndRetire: Story = {
  beforeEach: () => mockDetailApis(buildPersona({ status: "draft" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Activate" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
  },
};

export const RetiredOffersReactivateAndStaysEditable: Story = {
  beforeEach: () => mockDetailApis(buildPersona({ status: "retired" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Reactivate" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    // No approval gate, so no content lock.
    await expect(canvas.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  },
};

export const RetireAsksForConfirmation: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona());
    spyOn(api, "post").mockResolvedValue(buildPersona({ status: "retired" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Retire" }));
    await userEvent.click(canvas.getByRole("button", { name: "Retire" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Retire this Persona?" }));
    await userEvent.type(dialog.getByLabelText("Transition comment"), "Replaced by a newer persona");
    await userEvent.click(dialog.getByRole("button", { name: "Retire" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}/retire`, { comment: "Replaced by a newer persona" }),
    );
    await waitFor(() => expect(canvas.getByText("Retired", { exact: true })).toBeInTheDocument());
  },
};

export const ArchiveAsksForConfirmation: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona());
    spyOn(api, "post").mockResolvedValue(buildPersona({ is_archived: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Archive" }));
    await userEvent.click(canvas.getByRole("button", { name: "Archive" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Archive this Persona?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}/archive`));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Unarchive" })).toBeInTheDocument());
  },
};

export const WeightShowsItsSourceWithoutAnOverride: Story = {
  beforeEach: () => mockDetailApis(buildPersona({ weight: 2, effective_weight: 2, weight_source: "persona" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("effective-weight")).toHaveTextContent("2"));
    await expect(canvas.getByText("Persona's own weight")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Use inherited value" })).not.toBeInTheDocument();
  },
};

export const WeightInheritedFromParentProjectIsNamed: Story = {
  beforeEach: () => mockDetailApis(buildPersona({ effective_weight: 7, weight_override: null, weight_source: "ancestor_project" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Inherited from parent project")).toBeInTheDocument());
    await expect(canvas.getByTestId("effective-weight")).toHaveTextContent("7");
  },
};

export const OverrideCanBeSet: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona());
    spyOn(api, "put").mockResolvedValue(buildPersona({ effective_weight: 9, weight_override: 9, weight_source: "project" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Project weight override"));
    await expect(canvas.getByRole("button", { name: "Set override" })).toBeDisabled();
    await userEvent.type(canvas.getByLabelText("Project weight override"), "9");
    await userEvent.click(canvas.getByRole("button", { name: "Set override" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}/weight`, { weight: 9 }));
    // A custom value reads "Custom" with a way back, per `OverridePill`'s own convention.
    await waitFor(() => expect(canvas.getByText("Custom")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Use inherited value" })).toBeInTheDocument();
    await expect(canvas.getByTestId("effective-weight")).toHaveTextContent("9");
  },
};

export const OverrideCanBeResetToInherited: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona({ effective_weight: 9, weight_override: 9, weight_source: "project" }));
    spyOn(api, "delete").mockResolvedValue(buildPersona({ effective_weight: 2, weight_override: null, weight_source: "persona" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Use inherited value" }));
    await userEvent.click(canvas.getByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}/weight`));
    await waitFor(() => expect(canvas.getByText("Persona's own weight")).toBeInTheDocument());
  },
};

export const OrgPersonaInProjectIsReadOnlyApartFromWeight: Story = {
  beforeEach: () =>
    mockDetailApis(buildPersona({ scope: "organization", organization_id: "org-1", project_id: null })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/organisation-wide Persona/)).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "organisation view" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    await expect(canvas.getByLabelText("Project weight override")).toBeInTheDocument();
  },
};

const ORG_IN_PROJECT = { scope: "organization", organization_id: "org-1", project_id: null, project_hidden: false } as const;

export const OrgPersonaCanBeHiddenFromTheProject: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona(ORG_IN_PROJECT));
    spyOn(api, "put").mockResolvedValue(buildPersona({ ...ORG_IN_PROJECT, project_hidden: true, hidden_override: true, hidden_source: "project" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("project-visibility")).toHaveTextContent("Visible"));
    await userEvent.click(canvas.getByRole("button", { name: "Hide from this project" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Hide Field Technician from this project?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Hide" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}/visibility`, { hidden: true }),
    );
  },
};

export const ExplicitlyShownOrgPersonaCanRevertToInherited: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona({ ...ORG_IN_PROJECT, hidden_override: false, hidden_source: "project" }));
    spyOn(api, "delete").mockResolvedValue(buildPersona({ ...ORG_IN_PROJECT, project_hidden: true, hidden_source: "ancestor_project" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("project-visibility")).toHaveTextContent("Shown, although a parent project hides it"));
    await userEvent.click(canvas.getByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}/visibility`));
  },
};

export const ProjectPersonaHasNoVisibilityControl: Story = {
  beforeEach: () => mockDetailApis(buildPersona()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Field Technician" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Hide from this project" })).not.toBeInTheDocument();
  },
};

export const OwnerCanBeAssigned: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona());
    spyOn(api, "put").mockResolvedValue(buildPersona({ owner: { type: "user", id: "user-2", label: "Jamie Lee", member_count: null, exists: true } }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Persona owner"));
    await userEvent.type(canvas.getByLabelText("Persona owner"), "Jamie");
    await waitFor(() => canvas.getByText(/Jamie Lee/));
    await userEvent.click(canvas.getByText(/Jamie Lee/));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}`, { owner: { type: "user", id: "user-2" } }));
  },
};

/** An organisation group can own the persona: picking it sends a typed principal. */
export const OwnerCanBeAnOrgGroup: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona());
    spyOn(api, "put").mockResolvedValue(buildPersona({ owner: TEAM }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Persona owner"));
    await userEvent.type(canvas.getByLabelText("Persona owner"), "platform");
    await userEvent.click(await canvas.findByText("Platform Architecture"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}`, { owner: { type: "org_group", id: "group-1" } }));
    await waitFor(() => expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument());
  },
};

/** A project persona may be championed by a project group. */
export const ChampionCanBeAProjectGroup: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona());
    spyOn(api, "put").mockResolvedValue(buildPersona());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Persona champion"));
    await userEvent.type(canvas.getByLabelText("Persona champion"), "release");
    await userEvent.click(await canvas.findByText("Release board"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}`, { champion: { type: "project_group", id: "pgroup-1" } }));
  },
};

/** A group owner shows its name and kind, and Unassign clears it. */
export const GroupOwnerIsNamedAndCanBeUnassigned: Story = {
  beforeEach: () => {
    mockDetailApis(buildPersona({ owner: TEAM }));
    spyOn(api, "put").mockResolvedValue(buildPersona());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Platform Architecture")).toBeInTheDocument());
    await expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Unassign: Persona owner" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${PROJECT_BASE}/personas/${PERSONA_ID}`, { owner: null }));
  },
};

export const VersionHistoryUsesLabels: Story = {
  beforeEach: () =>
    mockDetailApis(buildPersona({ version_number: 2 }), [
      { id: "v1", persona_id: PERSONA_ID, version_number: 1, valid_from: "2026-01-10T09:00:00Z", valid_to: "2026-01-11T09:00:00Z", name: "Field Technician", status: "draft", weight: null, owner: null, champion: null, change_note: "Initial creation.", created_at: "2026-01-10T09:00:00Z" },
      { id: "v2", persona_id: PERSONA_ID, version_number: 2, valid_from: "2026-01-11T09:00:00Z", valid_to: null, name: "Field Technician", status: "active", weight: 2, owner: TEAM, champion: null, change_note: "Activated", created_at: "2026-01-11T09:00:00Z" },
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Version history" })).toBeInTheDocument());
    await expect(canvas.getByText("Initial creation.")).toBeInTheDocument();
    await expect(canvas.getAllByText("Draft").length).toBeGreaterThan(0);
    // History shows who owned each version, naming a group with its kind.
    await expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument();
  },
};

export const RepresentedByListsStakeholdersAsLinks: Story = {
  beforeEach: () =>
    mockDetailApis(buildPersona(), [], [{ link_id: "l1", id: "stakeholder-1", name: "Pat Regulator", scope: "project" }]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByRole("link", { name: "Pat Regulator" })).toHaveAttribute(
        "href", `/projects/${PROJECT_ID}/modules/stakeholders/stakeholders/stakeholder-1`,
      ),
    );
    // Linking is owned from the Stakeholder side, so this end is read-only.
    await expect(canvas.queryByRole("combobox", { name: "Persona to represent" })).not.toBeInTheDocument();
  },
};

export const RepresentedByShowsAnEmptyState: Story = {
  beforeEach: () => mockDetailApis(buildPersona()),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No Stakeholder represents this Persona yet.")).toBeInTheDocument());
  },
};

/** The persona's engagement history is the engagements that covered it, with a "Log contact" quick add. */
export const ShowsEngagementsThatCoveredThePersona: Story = {
  beforeEach: () =>
    mockDetailApis(buildPersona(), [], [], [
      { id: "e1", title: "Technician focus group", channel: "focus_group", engagement_date: "2026-02-20" },
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: "2026-02-20 · Focus group · Technician focus group" });
    await expect(link).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/stakeholders/engagements/e1`);
    await expect(canvas.getByRole("button", { name: "Log contact" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ActiveOffersRetire };
export const DarkTheme: Story = { ...ActiveOffersRetire, globals: { theme: "dark" } };

/** Links live in the shared Links panel beside the page. */
export const LinksPanelShowsLinks: Story = {
  beforeEach: () => mockDetailApis(buildPersona()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reports arrive late" })).toBeInTheDocument());
  },
};
