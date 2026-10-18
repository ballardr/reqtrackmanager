import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import type { OrgGroup, OrgUser, Principal, ProjectGroup } from "../../api/types";
import { api } from "../../api/client";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { buildProject, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { OpenQuestionDetailPage } from "./OpenQuestionDetailPage";
import type { OpenQuestion } from "./types";

const PROJECT_ID = "project-1";
const OPEN_QUESTION_ID = "open-question-1";

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

function openQuestion(overrides: Partial<OpenQuestion> = {}): OpenQuestion {
  return {
    id: OPEN_QUESTION_ID, project_id: PROJECT_ID, unique_code: "OQ-001", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null,
    question: "Should we standardise on a single battery vendor?",
    context: "Two vendors are currently qualified.", evidence: "12 field reports so far.",
    priority: "high", status: "open", owner: null, due_date: "2026-03-01", is_locked: false,
    created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

const LINKED_DECISION = buildGraphNode({ type: "decision", id: "dec-1", type_label: "Decision", label: "DEC-001 Use Postgres", status: null });

function mockDetailApis(current: OpenQuestion) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === `/api/v1/orgs/org-1/users`) return ORG_USERS;
    if (path.startsWith("/api/v1/orgs/org-1/users/search")) {
      const q = new URL(path, "http://localhost").searchParams.get("q")?.toLowerCase() ?? "";
      return { members: ORG_USERS.filter((u) => u.display_name.toLowerCase().includes(q)), external: null };
    }
    if (path === "/api/v1/orgs/org-1/groups") return ORG_GROUPS;
    if (path === `/api/v1/projects/${PROJECT_ID}/groups`) return PROJECT_GROUPS;
    if (path.endsWith(`/open-questions/${OPEN_QUESTION_ID}`)) return current;
    if (path.includes("/comments")) return [];
    if (path.includes("/files")) return [];
    if (path.includes("/artefacts/open_question/") && path.includes("/link-graph")) return buildGraph([[LINKED_DECISION]]);
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/**
 * A real routed page — stories go through `withRouter`/`withAuth` rather
 * than passing props directly, mirroring `PainPointDetailPage.stories.tsx`'s
 * own identical convention.
 */
const meta: Meta<typeof OpenQuestionDetailPage> = {
  title: "Modules/ContextStrategy/OpenQuestionDetailPage",
  component: OpenQuestionDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(
      `/projects/${PROJECT_ID}/modules/context_strategy/open-questions/${OPEN_QUESTION_ID}`,
      "/projects/:projectId/modules/context_strategy/open-questions/:openQuestionId"
    ),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof OpenQuestionDetailPage>;

export const OpenShowsInvestigate: Story = {
  beforeEach: () => mockDetailApis(openQuestion({ status: "open" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Should we standardise on a single battery vendor?" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Investigate" })).toBeInTheDocument();
  },
};

export const InvestigatingShowsBothBranches: Story = {
  beforeEach: () => mockDetailApis(openQuestion({ status: "investigating" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Mark ready for decision" }));
    await expect(canvas.getByRole("button", { name: "Withdraw" })).toBeInTheDocument();
  },
};

export const ReadyForDecisionShowsResolveAndWithdraw: Story = {
  beforeEach: () => mockDetailApis(openQuestion({ status: "ready_for_decision" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Resolve" }));
    await expect(canvas.getByRole("button", { name: "Withdraw" })).toBeInTheDocument();
  },
};

export const ResolvedIsLockedNoNewEvidence: Story = {
  beforeEach: () => mockDetailApis(openQuestion({ status: "resolved", is_locked: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument());
    await expect(canvas.getByText(/new evidence can no longer be added/)).toBeInTheDocument();
  },
};

export const WithdrawFromInvestigatingRequiresComment: Story = {
  beforeEach: () => mockDetailApis(openQuestion({ status: "investigating" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Withdraw" }));
    await userEvent.click(canvas.getByRole("button", { name: "Withdraw" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Withdraw this Open Question?" }));
    await expect(dialog.getByRole("button", { name: "Withdraw" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Withdrawal comment"), "Superseded by a vendor consolidation decision elsewhere.");
    await expect(dialog.getByRole("button", { name: "Withdraw" })).toBeEnabled();
  },
};

export const MarkReadyForDecision: Story = {
  beforeEach: () => {
    mockDetailApis(openQuestion({ status: "investigating" }));
    spyOn(api, "post").mockImplementation(async (path: string) => {
      if (path.endsWith("/mark-ready-for-decision")) return openQuestion({ status: "ready_for_decision" });
      throw new Error(`Unmocked POST: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Mark ready for decision" }));
    await userEvent.click(canvas.getByRole("button", { name: "Mark ready for decision" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Mark this Open Question ready for decision?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Mark ready for decision" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/open-questions/${OPEN_QUESTION_ID}/mark-ready-for-decision`,
      { comment: null }
    ));
    await waitFor(() => expect(canvas.getByText("Ready for Decision")).toBeInTheDocument());
  },
};

export const OwnerCanBeAssigned: Story = {
  beforeEach: () => {
    mockDetailApis(openQuestion());
    spyOn(api, "put").mockImplementation(async (path: string) => {
      if (path.endsWith(`/open-questions/${OPEN_QUESTION_ID}`)) return openQuestion({ owner: { type: "user", id: "user-2", label: "Jamie Lee", member_count: null, exists: true } });
      throw new Error(`Unmocked PUT: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Unassigned"));
    await userEvent.type(canvas.getByLabelText("Open Question owner"), "Jamie");
    await waitFor(() => canvas.getByText(/Jamie Lee/));
    await userEvent.click(canvas.getByText(/Jamie Lee/));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/open-questions/${OPEN_QUESTION_ID}`,
      expect.objectContaining({ owner: { type: "user", id: "user-2" } })
    ));
  },
};

/** A team can own the Open Question: picking an organisation group sends a typed principal and the badge names the group. */
export const OwnerCanBeAnOrgGroup: Story = {
  beforeEach: () => {
    mockDetailApis(openQuestion());
    spyOn(api, "put").mockResolvedValue(openQuestion({ owner: TEAM }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Open Question owner"));
    await userEvent.type(canvas.getByLabelText("Open Question owner"), "platform");
    await userEvent.click(await canvas.findByText("Platform Architecture"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/open-questions/${OPEN_QUESTION_ID}`,
      expect.objectContaining({ owner: { type: "org_group", id: "group-1" } })
    ));
    await waitFor(() => expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument());
  },
};

/** A Open Question is project-scoped here, so a project group is a valid owner. */
export const OwnerCanBeAProjectGroup: Story = {
  beforeEach: () => {
    mockDetailApis(openQuestion());
    spyOn(api, "put").mockResolvedValue(openQuestion({ owner: SQUAD }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Open Question owner"));
    await userEvent.type(canvas.getByLabelText("Open Question owner"), "release");
    await userEvent.click(await canvas.findByText("Release board"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/open-questions/${OPEN_QUESTION_ID}`,
      expect.objectContaining({ owner: { type: "project_group", id: "pgroup-1" } })
    ));
  },
};

/** A group owner shows its name and kind, and Unassign clears it. */
export const GroupOwnerIsNamedAndCanBeUnassigned: Story = {
  beforeEach: () => {
    mockDetailApis(openQuestion({ owner: TEAM }));
    spyOn(api, "put").mockResolvedValue(openQuestion());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Platform Architecture")).toBeInTheDocument());
    await expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Unassign: Open Question owner" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/open-questions/${OPEN_QUESTION_ID}`,
      expect.objectContaining({ owner: null })
    ));
  },
};

export const LightTheme: Story = { ...InvestigatingShowsBothBranches };
export const DarkTheme: Story = { ...InvestigatingShowsBothBranches, globals: { theme: "dark" } };

/** Links live in the shared Links panel beside the page; the page adds only what is specific to it. */
export const LinksPanelShowsLinks: Story = {
  beforeEach: () => mockDetailApis(openQuestion()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "DEC-001 Use Postgres" })).toBeInTheDocument());
  },
};
