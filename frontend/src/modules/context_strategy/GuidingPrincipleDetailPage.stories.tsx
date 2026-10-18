import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import type { OrgGroup, OrgUser, Principal, ProjectGroup } from "../../api/types";
import { api } from "../../api/client";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { buildProject, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { GuidingPrincipleDetailPage } from "./GuidingPrincipleDetailPage";
import type { GuidingPrinciple } from "./types";

const PROJECT_ID = "project-1";
const GUIDING_PRINCIPLE_ID = "gp-1";

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false,
    module_roles: [], custom_roles: [],
  },
];

const ORG_GROUPS: OrgGroup[] = [
  { id: "group-1", name: "Platform Architecture", member_user_ids: ["user-2"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const PROJECT_GROUPS: ProjectGroup[] = [
  { id: "pgroup-1", name: "Release board", roles: [], member_user_ids: ["user-2"], member_org_group_ids: [], member_source_project_ids: [] },
];
const TEAM: Principal = { type: "org_group", id: "group-1", label: "Platform Architecture", member_count: 3, exists: true };
const SQUAD: Principal = { type: "project_group", id: "pgroup-1", label: "Release board", member_count: 1, exists: true };

function guidingPrinciple(overrides: Partial<GuidingPrinciple> = {}): GuidingPrinciple {
  return {
    id: GUIDING_PRINCIPLE_ID, scope: "project", organization_id: null, project_id: PROJECT_ID, unique_code: "GP-001", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, name: "Field data is captured once",
    principle_statement: "Every field observation is recorded exactly once, at the point of inspection.",
    rationale: "Re-keying paper forms introduces errors and delay.", priority: "high", status: "proposed",
    owner: null, version_number: 2, is_locked: false,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

const LINKED_DECISION = buildGraphNode({ type: "decision", id: "dec-1", type_label: "Decision", label: "DEC-001 Use Postgres", status: null });

function mockDetailApis(current: GuidingPrinciple, versions: unknown[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === `/api/v1/orgs/org-1/users`) return ORG_USERS;
    if (path.startsWith("/api/v1/orgs/org-1/users/search")) {
      const q = new URL(path, "http://localhost").searchParams.get("q")?.toLowerCase() ?? "";
      return { members: ORG_USERS.filter((u) => u.display_name.toLowerCase().includes(q)), external: null };
    }
    if (path === "/api/v1/orgs/org-1/groups") return ORG_GROUPS;
    if (path === `/api/v1/projects/${PROJECT_ID}/groups`) return PROJECT_GROUPS;
    if (path.endsWith(`/guiding-principles/${GUIDING_PRINCIPLE_ID}`)) return current;
    if (path.endsWith("/versions")) return versions;
    if (path.includes("/comments")) return [];
    if (path.includes("/files")) return [];
    if (path.includes("/artefacts/guiding_principle/") && path.includes("/link-graph")) return buildGraph([[LINKED_DECISION]]);
    if (path.endsWith("/strategies")) return [];
    if (path.endsWith("/requirements")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/**
 * A real routed page — stories go through `withRouter`/`withAuth` rather
 * than passing props directly, mirroring `StrategyDetailPage.stories.tsx`'s
 * own identical convention.
 */
const meta: Meta<typeof GuidingPrincipleDetailPage> = {
  title: "Modules/ContextStrategy/GuidingPrincipleDetailPage",
  component: GuidingPrincipleDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(
      `/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles/${GUIDING_PRINCIPLE_ID}`,
      "/projects/:projectId/modules/context_strategy/guiding-principles/:guidingPrincipleId"
    ),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof GuidingPrincipleDetailPage>;

export const DraftShowsPropose: Story = {
  beforeEach: () => mockDetailApis(guidingPrinciple({ status: "draft" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Field data is captured once" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Propose" })).toBeInTheDocument();
  },
};

export const ProposedShowsApproveAndSendBack: Story = {
  beforeEach: () => mockDetailApis(guidingPrinciple()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Send back" })).toBeInTheDocument();
    // No "Submit for review" — Guiding Principle's own shorter lifecycle has
    // no `under_review` step.
    await expect(canvas.queryByRole("button", { name: "Submit for review" })).not.toBeInTheDocument();
  },
};

export const ApprovedShowsActivate: Story = {
  beforeEach: () => mockDetailApis(guidingPrinciple({ status: "approved", is_locked: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Activate" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  },
};

export const ActiveShowsSupersedeAndRetire: Story = {
  beforeEach: () => mockDetailApis(guidingPrinciple({ status: "active", is_locked: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Supersede" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/new attachments can no longer be added/)).toBeInTheDocument();
  },
};

export const RetiredIsTerminal: Story = {
  beforeEach: () => mockDetailApis(guidingPrinciple({ status: "retired", is_locked: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Retired", { exact: true })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Supersede" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
  },
};

export const SendBackRequiresComment: Story = {
  beforeEach: () => mockDetailApis(guidingPrinciple()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Send back" }));
    await userEvent.click(canvas.getByRole("button", { name: "Send back" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Send this Guiding Principle back to Draft?" }));
    await expect(dialog.getByRole("button", { name: "Send back" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Send-back comment"), "Needs a stronger rationale first.");
    await expect(dialog.getByRole("button", { name: "Send back" })).toBeEnabled();
  },
};

export const ApproveGuidingPrinciple: Story = {
  beforeEach: () => {
    mockDetailApis(guidingPrinciple());
    spyOn(api, "post").mockImplementation(async (path: string) => {
      if (path.endsWith("/approve")) return guidingPrinciple({ status: "approved" });
      throw new Error(`Unmocked POST: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Approve" }));
    await userEvent.click(canvas.getByRole("button", { name: "Approve" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Approve this Guiding Principle?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles/${GUIDING_PRINCIPLE_ID}/approve`,
      { comment: null }
    ));
    await waitFor(() => expect(canvas.getByText("Approved")).toBeInTheDocument());
  },
};

export const OwnerCanBeAssigned: Story = {
  beforeEach: () => {
    mockDetailApis(guidingPrinciple());
    spyOn(api, "put").mockImplementation(async (path: string) => {
      if (path.endsWith(`/guiding-principles/${GUIDING_PRINCIPLE_ID}`)) return guidingPrinciple({ owner: { type: "user", id: "user-2", label: "Jamie Lee", member_count: null, exists: true } });
      throw new Error(`Unmocked PUT: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Unassigned"));
    await userEvent.type(canvas.getByLabelText("Guiding Principle owner"), "Jamie");
    await waitFor(() => canvas.getByText(/Jamie Lee/));
    await userEvent.click(canvas.getByText(/Jamie Lee/));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles/${GUIDING_PRINCIPLE_ID}`,
      expect.objectContaining({ owner: { type: "user", id: "user-2" } })
    ));
  },
};

/** A team can own the Guiding Principle: picking an organisation group sends a typed principal and the badge names the group. */
export const OwnerCanBeAnOrgGroup: Story = {
  beforeEach: () => {
    mockDetailApis(guidingPrinciple());
    spyOn(api, "put").mockResolvedValue(guidingPrinciple({ owner: TEAM }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Guiding Principle owner"));
    await userEvent.type(canvas.getByLabelText("Guiding Principle owner"), "platform");
    await userEvent.click(await canvas.findByText("Platform Architecture"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles/${GUIDING_PRINCIPLE_ID}`,
      expect.objectContaining({ owner: { type: "org_group", id: "group-1" } })
    ));
    await waitFor(() => expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument());
  },
};

/** A Guiding Principle is project-scoped here, so a project group is a valid owner. */
export const OwnerCanBeAProjectGroup: Story = {
  beforeEach: () => {
    mockDetailApis(guidingPrinciple());
    spyOn(api, "put").mockResolvedValue(guidingPrinciple({ owner: SQUAD }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Guiding Principle owner"));
    await userEvent.type(canvas.getByLabelText("Guiding Principle owner"), "release");
    await userEvent.click(await canvas.findByText("Release board"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles/${GUIDING_PRINCIPLE_ID}`,
      expect.objectContaining({ owner: { type: "project_group", id: "pgroup-1" } })
    ));
  },
};

/** A group owner shows its name and kind, and Unassign clears it. */
export const GroupOwnerIsNamedAndCanBeUnassigned: Story = {
  beforeEach: () => {
    mockDetailApis(guidingPrinciple({ owner: TEAM }));
    spyOn(api, "put").mockResolvedValue(guidingPrinciple());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Platform Architecture")).toBeInTheDocument());
    await expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Unassign: Guiding Principle owner" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles/${GUIDING_PRINCIPLE_ID}`,
      expect.objectContaining({ owner: null })
    ));
  },
};

/** The version history shows who owned each version, naming a group with its kind. */
export const VersionHistoryShowsOwners: Story = {
  beforeEach: () =>
    mockDetailApis(guidingPrinciple({ owner: TEAM }), [
      { id: "v1", guiding_principle_id: GUIDING_PRINCIPLE_ID, version_number: 1, valid_from: "2026-01-10T09:00:00Z", valid_to: "2026-01-11T09:00:00Z", name: "Field data is captured once", principle_statement: "s", rationale: "", priority: "high", status: "draft", owner: null, change_note: "Initial creation.", created_by: "user-1", created_at: "2026-01-10T09:00:00Z" },
      { id: "v2", guiding_principle_id: GUIDING_PRINCIPLE_ID, version_number: 2, valid_from: "2026-01-11T09:00:00Z", valid_to: null, name: "Field data is captured once", principle_statement: "s", rationale: "", priority: "high", status: "proposed", owner: TEAM, change_note: "Owner assigned", created_by: "user-1", created_at: "2026-01-11T09:00:00Z" },
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Version history" })).toBeInTheDocument());
    await expect(canvas.getByText("Initial creation.")).toBeInTheDocument();
    await expect(canvas.getAllByText("Org group · 3 members").length).toBeGreaterThan(0);
  },
};

export const LightTheme: Story = { ...ProposedShowsApproveAndSendBack };
export const DarkTheme: Story = { ...ProposedShowsApproveAndSendBack, globals: { theme: "dark" } };

/** Links live in the shared Links panel beside the page; the page adds only what is specific to it. */
export const LinksPanelShowsLinks: Story = {
  beforeEach: () => mockDetailApis(guidingPrinciple()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "DEC-001 Use Postgres" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Supersede another Guiding Principle" })).toBeInTheDocument();
  },
};
