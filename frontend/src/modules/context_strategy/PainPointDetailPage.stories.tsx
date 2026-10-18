import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import type { OrgGroup, OrgUser, Principal, ProjectGroup } from "../../api/types";
import { api } from "../../api/client";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { buildProject, buildScoringScheme, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { painPointScores } from "./painPointScoringFixtures";
import { PainPointDetailPage } from "./PainPointDetailPage";
import type { EffectivePainPointType, PainPoint } from "./types";

const PROJECT_ID = "project-1";
const PAIN_POINT_ID = "pain-point-1";

const TYPES: EffectivePainPointType[] = [
  { id: "type-operator", name: "Operator", display_order: 0, is_enabled: true, source: "org" },
];

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

function painPoint(overrides: Partial<PainPoint> = {}): PainPoint {
  return {
    id: PAIN_POINT_ID, project_id: PROJECT_ID, unique_code: "PP-001", pain_point_type_id: "type-operator", pain_point_type_name: "Operator",
    creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    title: "Report delays under poor connectivity", description: "Field reports queue for days before reaching HQ.",
    source: "Operator interviews", impact: "Decisions are made on stale data.", evidence: "12 reports last month.",
    priority: "high", status: "triaged", owner: null, date_identified: "2026-01-05", is_intentional: false, is_locked: false,
    created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

const LINKED_DECISION = buildGraphNode({ type: "decision", id: "dec-1", type_label: "Decision", label: "DEC-001 Use Postgres", status: null });

function mockDetailApis(current: PainPoint) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === `/api/v1/orgs/org-1/users`) return ORG_USERS;
    if (path.startsWith("/api/v1/orgs/org-1/users/search")) {
      const q = new URL(path, "http://localhost").searchParams.get("q")?.toLowerCase() ?? "";
      return { members: ORG_USERS.filter((u) => u.display_name.toLowerCase().includes(q)), external: null };
    }
    if (path === "/api/v1/orgs/org-1/groups") return ORG_GROUPS;
    if (path === `/api/v1/projects/${PROJECT_ID}/groups`) return PROJECT_GROUPS;
    if (path === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/pain_point`) return buildScoringScheme();
    if (path.includes(`/pain-points/${PAIN_POINT_ID}/scores`)) return painPointScores();
    if (path.endsWith(`/pain-points/${PAIN_POINT_ID}`)) return current;
    if (path.endsWith("/pain-point-types")) return TYPES;
    if (path.includes("/comments")) return [];
    if (path.includes("/files")) return [];
    if (path.includes("/artefacts/pain_point/") && path.includes("/link-graph")) return buildGraph([[LINKED_DECISION]]);
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/**
 * A real routed page — stories go through `withRouter`/`withAuth` rather
 * than passing props directly, mirroring `StrategyDetailPage.stories.tsx`'s
 * own identical convention.
 */
const meta: Meta<typeof PainPointDetailPage> = {
  title: "Modules/ContextStrategy/PainPointDetailPage",
  component: PainPointDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(
      `/projects/${PROJECT_ID}/modules/context_strategy/pain-points/${PAIN_POINT_ID}`,
      "/projects/:projectId/modules/context_strategy/pain-points/:painPointId"
    ),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof PainPointDetailPage>;

export const SubmittedShowsTriage: Story = {
  beforeEach: () => mockDetailApis(painPoint({ status: "submitted" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Report delays under poor connectivity" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Triage" })).toBeInTheDocument();
  },
};

export const TriagedShowsThreeBranches: Story = {
  beforeEach: () => mockDetailApis(painPoint()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Accept" }));
    await expect(canvas.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Mark duplicate" })).toBeInTheDocument();
  },
};

export const AcceptedShowsAddress: Story = {
  beforeEach: () => mockDetailApis(painPoint({ status: "accepted" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Address" })).toBeInTheDocument());
  },
};

export const AddressedShowsClose: Story = {
  beforeEach: () => mockDetailApis(painPoint({ status: "addressed" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Close" })).toBeInTheDocument());
  },
};

export const ClosedIsLockedNoNewEvidence: Story = {
  beforeEach: () => mockDetailApis(painPoint({ status: "closed", is_locked: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument());
    await expect(canvas.getByText(/new evidence can no longer be added/)).toBeInTheDocument();
  },
};

export const RejectRequiresComment: Story = {
  beforeEach: () => mockDetailApis(painPoint()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Reject" }));
    await userEvent.click(canvas.getByRole("button", { name: "Reject" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Reject this Pain Point?" }));
    await expect(dialog.getByRole("button", { name: "Reject" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Rejection comment"), "Out of scope for this quarter.");
    await expect(dialog.getByRole("button", { name: "Reject" })).toBeEnabled();
  },
};

export const MarkDuplicateRequiresComment: Story = {
  beforeEach: () => mockDetailApis(painPoint()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Mark duplicate" }));
    await userEvent.click(canvas.getByRole("button", { name: "Mark duplicate" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Mark this Pain Point a duplicate?" }));
    await expect(dialog.getByRole("button", { name: "Mark duplicate" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Duplicate comment"), "Duplicate of PP-1.");
    await expect(dialog.getByRole("button", { name: "Mark duplicate" })).toBeEnabled();
  },
};

export const AcceptPainPoint: Story = {
  beforeEach: () => {
    mockDetailApis(painPoint());
    spyOn(api, "post").mockImplementation(async (path: string) => {
      if (path.endsWith("/accept")) return painPoint({ status: "accepted" });
      throw new Error(`Unmocked POST: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Accept" }));
    await userEvent.click(canvas.getByRole("button", { name: "Accept" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Accept this Pain Point?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Accept" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-points/${PAIN_POINT_ID}/accept`,
      { comment: null }
    ));
    await waitFor(() => expect(canvas.getByText("Accepted")).toBeInTheDocument());
  },
};

export const OwnerCanBeAssigned: Story = {
  beforeEach: () => {
    mockDetailApis(painPoint());
    spyOn(api, "put").mockImplementation(async (path: string) => {
      if (path.endsWith(`/pain-points/${PAIN_POINT_ID}`)) return painPoint({ owner: { type: "user", id: "user-2", label: "Jamie Lee", member_count: null, exists: true } });
      throw new Error(`Unmocked PUT: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Unassigned"));
    await userEvent.type(canvas.getByLabelText("Pain Point owner"), "Jamie");
    await waitFor(() => canvas.getByText(/Jamie Lee/));
    await userEvent.click(canvas.getByText(/Jamie Lee/));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-points/${PAIN_POINT_ID}`,
      expect.objectContaining({ owner: { type: "user", id: "user-2" } })
    ));
  },
};

/** A team can own the Pain Point: picking an organisation group sends a typed principal and the badge names the group. */
export const OwnerCanBeAnOrgGroup: Story = {
  beforeEach: () => {
    mockDetailApis(painPoint());
    spyOn(api, "put").mockResolvedValue(painPoint({ owner: TEAM }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Pain Point owner"));
    await userEvent.type(canvas.getByLabelText("Pain Point owner"), "platform");
    await userEvent.click(await canvas.findByText("Platform Architecture"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-points/${PAIN_POINT_ID}`,
      expect.objectContaining({ owner: { type: "org_group", id: "group-1" } })
    ));
    await waitFor(() => expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument());
  },
};

/** A Pain Point is project-scoped here, so a project group is a valid owner. */
export const OwnerCanBeAProjectGroup: Story = {
  beforeEach: () => {
    mockDetailApis(painPoint());
    spyOn(api, "put").mockResolvedValue(painPoint({ owner: SQUAD }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Pain Point owner"));
    await userEvent.type(canvas.getByLabelText("Pain Point owner"), "release");
    await userEvent.click(await canvas.findByText("Release board"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-points/${PAIN_POINT_ID}`,
      expect.objectContaining({ owner: { type: "project_group", id: "pgroup-1" } })
    ));
  },
};

/** A group owner shows its name and kind, and Unassign clears it. */
export const GroupOwnerIsNamedAndCanBeUnassigned: Story = {
  beforeEach: () => {
    mockDetailApis(painPoint({ owner: TEAM }));
    spyOn(api, "put").mockResolvedValue(painPoint());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Platform Architecture")).toBeInTheDocument());
    await expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Unassign: Pain Point owner" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-points/${PAIN_POINT_ID}`,
      expect.objectContaining({ owner: null })
    ));
  },
};

export const LightTheme: Story = { ...TriagedShowsThreeBranches };
export const DarkTheme: Story = { ...TriagedShowsThreeBranches, globals: { theme: "dark" } };

/** Links live in the shared Links panel beside the page; the page adds only what is specific to it. */
export const LinksPanelShowsLinks: Story = {
  beforeEach: () => mockDetailApis(painPoint()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "DEC-001 Use Postgres" })).toBeInTheDocument());
  },
};
