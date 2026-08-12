import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ProjectRole } from "../api/types";
import {
  buildComment,
  buildProjectListItem,
  buildRequirement,
  buildUser,
  withAuth,
  withRouter,
} from "../testing/storybook-helpers";
import { RequirementDetailPage } from "./RequirementDetailPage";

const PROJECT_ID = "project-1";
const REQUIREMENT_ID = "requirement-1";

/**
 * Routes every `api.get`/list call RequirementDetailPage's several parallel
 * fetches can make. `myRoles` drives `useMyProjectRoles` (via the
 * `?archived=false` projects list, matched by id) — the mechanism the QA
 * inventory flagged as a convenience-only, backend-mirroring permission
 * derivation (see docs/decisions.md); these stories pin the resulting
 * button visibility against `rbac.py`'s role hierarchy so drift here is
 * caught by a broken story, not silently.
 */
function mockRequirementDetailApis(myRoles: ProjectRole[], requirementOverrides: Parameters<typeof buildRequirement>[0] = {}) {
  const requirement = buildRequirement({ id: REQUIREMENT_ID, project_id: PROJECT_ID, ...requirementOverrides });
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("archived=false")) return [buildProjectListItem({ id: PROJECT_ID, my_roles: myRoles })];
    if (path.endsWith(`/requirements/${REQUIREMENT_ID}`)) return requirement;
    if (path.endsWith("/history")) return [];
    if (path.endsWith("/comments")) return [buildComment({ author_display_name: "Jamie Lee" })];
    if (path.endsWith("/files")) return [];
    if (path.includes("custom-fields")) return [];
    if (path.endsWith("/stages")) return [];
    if (path.endsWith("/activity")) return [];
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
    if (path.includes("/users")) return [];
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "post").mockResolvedValue(buildComment({ author_display_name: "Alex Morgan" }));
  return requirement;
}

const meta: Meta<typeof RequirementDetailPage> = {
  title: "Pages/RequirementDetailPage",
  component: RequirementDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(
      `/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}`,
      "/projects/:projectId/requirements/:requirementId"
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof RequirementDetailPage>;

/** A plain member (no stakeholder/manager/admin role) gets the read-only
 * view even though the requirement itself isn't locked — matches
 * `canEdit = canArchive || myRoles.includes("stakeholder")` in the page. */
export const MemberSeesReadOnlyView: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["member"]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Users can reset a forgotten password/)).toBeInTheDocument());
    await expect(canvas.queryByLabelText("Name")).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  },
};

/** A stakeholder can edit the form fields but cannot archive or complete —
 * `canArchive` stays false for this role. */
export const StakeholderCanEditNotArchive: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"], { status: "approved" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Name")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Mark completed" })).not.toBeInTheDocument();
  },
};

/** A project manager can edit, archive, and — because status is "approved"
 * — mark the requirement completed. */
export const ManagerCanArchiveAndComplete: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { status: "approved" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Name")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Mark completed" })).toBeInTheDocument();
  },
};

/** Once completed, a manager sees "Revert completion" instead of "Mark
 * completed" — mirrors the lifecycle diagram in
 * help/02-requirement-lifecycle.md. */
export const CompletedRequirementShowsRevert: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_administrator"], { status: "completed" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Revert completion" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Mark completed" })).not.toBeInTheDocument();
  },
};

/** A locked requirement is read-only for every role, including a manager —
 * editing only resumes through an approved change request. */
export const LockedRequirementIsReadOnlyForManager: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { is_locked: true, status: "approved" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The locked badge's text ("Locked (approved) — use a change request to
    // modify") spans multiple sibling text nodes within one <div>, so match
    // on that div's combined textContent rather than a single exact string.
    await waitFor(() =>
      expect(
        canvas.getByText((_, element) => element?.className === "badge" && (element.textContent ?? "").includes("Locked (approved)"))
      ).toBeInTheDocument()
    );
    await expect(canvas.queryByLabelText("Name")).not.toBeInTheDocument();
    // Archive is still available to a manager even while locked.
    await expect(canvas.getByRole("button", { name: "Archive" })).toBeInTheDocument();
  },
};

export const ReviewSectionRecordOutcome: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { review_date: "2026-03-01", reviewer_id: null });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Record review outcome")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Record review outcome"), "failed");
    await expect(canvas.getByLabelText("Comment")).toBeInTheDocument();
  },
};

export const PostComment: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Jamie Lee/)).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("Add comment"), "Looks correct to me.");
    await userEvent.click(canvas.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
  },
};

export const LightTheme: Story = { ...ManagerCanArchiveAndComplete, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ManagerCanArchiveAndComplete, globals: { theme: "dark" } };
