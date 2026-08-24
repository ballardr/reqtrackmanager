import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ChangeRequestVoteTally, ProjectRole } from "../api/types";
import {
  buildChangeRequest,
  buildProjectListItem,
  buildUser,
  withAuth,
  withRouter,
  withToast,
} from "../testing/storybook-helpers";
import { ChangeRequestDetailPage } from "./ChangeRequestDetailPage";

const PROJECT_ID = "project-1";
const CR_ID = "cr-1";

const emptyTally: ChangeRequestVoteTally = { votes: [], approve_count: 0, reject_count: 0 };

/** Same role-permutation-pinning rationale as RequirementDetailPage.stories
 * — `canDecide`/`canManageTasks`/`canVote` mirror `rbac.py`'s role
 * hierarchy in JS for UI convenience only (see docs/decisions.md); these
 * stories catch drift between the two rather than re-implementing the
 * check itself. */
function mockChangeRequestDetailApis(myRoles: ProjectRole[], crOverrides: Parameters<typeof buildChangeRequest>[0] = {}) {
  const cr = buildChangeRequest({ id: CR_ID, project_id: PROJECT_ID, ...crOverrides });
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("archived=false")) return [buildProjectListItem({ id: PROJECT_ID, my_roles: myRoles })];
    if (path.endsWith(`/change-requests/${CR_ID}`)) return cr;
    if (path.endsWith("/comments")) return [];
    if (path.endsWith("/stages")) return [];
    if (path.endsWith("/activity")) return [];
    if (path.endsWith("/tasks")) return [];
    if (path.endsWith("/votes")) return emptyTally;
    if (path.endsWith(`/requirements/${cr.requirement_id}`)) return null;
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
    if (path.includes("/users")) return [];
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "post").mockResolvedValue(undefined);
  return cr;
}

const meta: Meta<typeof ChangeRequestDetailPage> = {
  title: "Pages/ChangeRequestDetailPage",
  component: ChangeRequestDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/change-requests/${CR_ID}`, "/projects/:projectId/change-requests/:crId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ChangeRequestDetailPage>;

/** submit/withdraw aren't role-gated at all (project settings, not rbac,
 * control who may create one in the first place) — a draft CR shows both
 * regardless of role. */
export const DraftShowsSubmitAndWithdraw: Story = {
  beforeEach: () => {
    mockChangeRequestDetailApis(["member"], { status: "draft", proposed_name: "Add password reset flow" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Add password reset flow" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Submit" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Withdraw" })).toBeInTheDocument();
  },
};

/** Submitting shows a success toast (Principle 7, sixth-pass audit —
 * `act()` previously reloaded silently with no feedback at all). */
export const SubmitShowsToast: Story = {
  beforeEach: () => {
    mockChangeRequestDetailApis(["member"], { status: "draft", proposed_name: "Add password reset flow" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Submit" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(expect.stringContaining("/submit")));
    await expect(within(document.body).getByText("Change request submitted")).toBeInTheDocument();
  },
};

/** Rejecting shows a success toast too — the audit specifically flagged
 * rejection as having *no* feedback of any kind before this pass. */
export const RejectShowsToast: Story = {
  beforeEach: () => {
    mockChangeRequestDetailApis(["project_manager"], { status: "submitted", proposed_name: "Add password reset flow" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Reject" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(expect.stringContaining("/decide"), { approve: false, note: "" }));
    await expect(within(document.body).getByText("Change request rejected")).toBeInTheDocument();
  },
};

/** A project manager sees Approve/Reject on a submitted CR — `canDecide`. */
export const SubmittedManagerCanDecide: Story = {
  beforeEach: () => {
    mockChangeRequestDetailApis(["project_manager"], { status: "submitted", proposed_name: "Add password reset flow" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  },
};

/** A stakeholder cannot decide, but can cast an advisory vote — `canVote`
 * includes stakeholder even though `canDecide` doesn't. */
export const SubmittedStakeholderCanVoteNotDecide: Story = {
  beforeEach: () => {
    mockChangeRequestDetailApis(["stakeholder"], { status: "submitted", proposed_name: "Add password reset flow" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Vote to approve" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  },
};

/** A plain member can neither decide nor vote. */
export const SubmittedMemberCannotDecideOrVote: Story = {
  beforeEach: () => {
    mockChangeRequestDetailApis(["member"], { status: "submitted", proposed_name: "Add password reset flow" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Withdraw" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Vote to approve" })).not.toBeInTheDocument();
  },
};

/** `canManageTasks` includes project_administrator, not just manager. */
export const ProjectAdministratorCanAddTask: Story = {
  beforeEach: () => {
    mockChangeRequestDetailApis(["project_administrator"], { status: "in_review", proposed_name: "Add password reset flow" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByPlaceholderText("Description")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("Description"), "Confirm rollout with support team");
    await userEvent.click(canvas.getByRole("button", { name: "New task" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(expect.stringContaining("/tasks"), { description: "Confirm rollout with support team" }));
  },
};

/** MODIFY_REQUIREMENT change requests only render the fields they actually
 * propose to change (`changed_fields`) — matches ChangeRequestsPage's
 * "ticking pre-fills, unticked is never shown" rule from
 * help/03-change-requests.md. */
export const ModifyRequirementShowsOnlyChangedFields: Story = {
  beforeEach: () => {
    mockChangeRequestDetailApis(["project_manager"], {
      kind: "modify_requirement",
      status: "in_review",
      requirement_id: "requirement-1",
      changed_fields: ["reasoning"],
      proposed_reasoning: "Locked users need a 24-hour recovery window instead of 1 hour.",
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Fields to change")).toBeInTheDocument());
    await expect(canvas.getByText("Locked users need a 24-hour recovery window instead of 1 hour.")).toBeInTheDocument();
    await expect(canvas.queryByText("Proposed name")).not.toBeInTheDocument();
  },
};

export const VoteCommentsModal: Story = {
  beforeEach: () => {
    const cr = buildChangeRequest({ id: CR_ID, project_id: PROJECT_ID, status: "submitted", proposed_name: "Add password reset flow" });
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("archived=false")) return [buildProjectListItem({ id: PROJECT_ID, my_roles: ["project_manager"] })];
      if (path.endsWith(`/change-requests/${CR_ID}`)) return cr;
      if (path.endsWith("/votes")) {
        return {
          votes: [{ id: "v1", change_request_id: CR_ID, user_id: "user-2", vote: "approve", comment: "Looks safe.", voted_at: "2026-02-01T09:00:00Z" }],
          approve_count: 1,
          reject_count: 0,
        } satisfies ChangeRequestVoteTally;
      }
      if (path.endsWith("/comments") || path.endsWith("/stages") || path.endsWith("/activity") || path.endsWith("/tasks")) return [];
      if (path.endsWith(`/requirements/${cr.requirement_id}`)) return null;
      if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
      if (path.includes("/users")) return [];
      throw new Error(`unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: /View comments/ })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /View comments/ }));
    const modal = within(document.body).getByRole("dialog");
    await expect(within(modal).getByText("Looks safe.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...SubmittedManagerCanDecide, globals: { theme: "light" } };
export const DarkTheme: Story = { ...SubmittedManagerCanDecide, globals: { theme: "dark" } };
