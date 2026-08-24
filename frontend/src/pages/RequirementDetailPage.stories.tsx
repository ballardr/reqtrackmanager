import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ActionTypeDefinition, LinkTypeDefinition, ProjectRole, Requirement, RequirementAction, RequirementLink } from "../api/types";
import {
  buildActionType,
  buildComment,
  buildLinkType,
  buildProjectListItem,
  buildRequirement,
  buildRequirementAction,
  buildRequirementLink,
  buildUser,
  withAuth,
  withRouter,
  withTerminology,
  withToast,
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
 * caught by a broken story, not silently. `links`/`linkedActions` populate
 * the Links/Actions cards; both default empty so existing stories that
 * don't care about them keep seeing the "no links/actions yet" state.
 */
function mockRequirementDetailApis(
  myRoles: ProjectRole[],
  requirementOverrides: Parameters<typeof buildRequirement>[0] = {},
  extra: { links?: RequirementLink[]; linkedActions?: RequirementAction[]; projectActions?: RequirementAction[]; otherRequirements?: Requirement[] } = {}
) {
  const requirement = buildRequirement({ id: REQUIREMENT_ID, project_id: PROJECT_ID, ...requirementOverrides });
  const linkTypes: LinkTypeDefinition[] = [buildLinkType({ id: "lt1", forward_name: "Depends on", reverse_name: "Is a dependency of" })];
  const actionTypes: ActionTypeDefinition[] = [buildActionType({ id: "at1", name: "Review" })];
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("archived=false")) return [buildProjectListItem({ id: PROJECT_ID, my_roles: myRoles })];
    if (path.endsWith(`/requirements/${REQUIREMENT_ID}`)) return requirement;
    if (path.endsWith("/history")) return [];
    if (path.endsWith("/comments")) return [buildComment({ author_display_name: "Jamie Lee" })];
    if (path.endsWith(`/requirements/${REQUIREMENT_ID}/files`)) return [];
    if (path.includes("custom-fields")) return [];
    if (path.endsWith("/stages")) return [];
    if (path.endsWith("/activity")) return [];
    if (path.endsWith(`/requirements/${REQUIREMENT_ID}/links`)) return extra.links ?? [];
    if (path.endsWith("/link-types")) return linkTypes;
    if (path.endsWith(`/requirements/${REQUIREMENT_ID}/actions`)) return extra.linkedActions ?? [];
    if (path.endsWith("/action-types")) return actionTypes;
    if (path.endsWith(`/projects/${PROJECT_ID}/actions`)) return extra.projectActions ?? [];
    if (path.endsWith(`/projects/${PROJECT_ID}/requirements`)) return extra.otherRequirements ?? [];
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
    withToast(),
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

/** Archiving opens the shared `ConfirmDialog` (2026-08 UX audit fix — this
 * used to fire with no confirmation at all, then just `window.confirm`),
 * then shows a success toast (Principle 7) before navigating back to the
 * list. */
export const ArchivingConfirmsAndShowsToast: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { status: "approved" });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Archive" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Archive" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Archive this requirement?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Archive" }));

    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}`)
    );
    await expect(within(document.body).getByText("Requirement archived")).toBeInTheDocument();
  },
};

/** Cancelling the dialog leaves the requirement untouched — no delete
 * call, no toast. */
export const ArchivingCanBeCancelled: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { status: "approved" });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Archive" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Archive" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Archive this requirement?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.delete).not.toHaveBeenCalled();
  },
};

/** An archived requirement shows a "Restore" button instead of "Archive",
 * plus an "Archived" badge — clicking Restore calls the new `/unarchive`
 * endpoint directly with no `ConfirmDialog` (unlike Archive above — mirrors
 * `ProjectAdminPage.tsx`'s existing unarchive button, which also fires
 * immediately) and shows a success toast (2026-08 UX audit roadmap:
 * unarchive endpoint + Restore button — archive used to be one-way for
 * requirements, unlike projects). */
export const ArchivedRequirementShowsRestoreButton: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { is_archived: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Restore" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    await expect(canvas.getByText("Archived", { selector: "div.badge" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Restore" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/unarchive`)
    );
    await expect(within(document.body).getByText("Requirement restored")).toBeInTheDocument();
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

/** Links card populated with an outgoing link — `display_name`/
 * `other_requirement_*` are already server-resolved, so the card just
 * renders them directly with zero client-side direction logic. */
export const LinksCardPopulated: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"], {}, {
      links: [buildRequirementLink({ id: "link1", display_name: "Depends on", other_requirement_unique_code: "AUTH-LOG-002", other_requirement_name: "Users can enable two-factor authentication" })],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/AUTH-LOG-002/)).toBeInTheDocument());
    // "Depends on" also appears as an <option> in the "add link" type
    // select below, so this is scoped to the link row's own badge.
    await expect(canvas.getByText("Depends on", { selector: "span.badge" })).toBeInTheDocument();
  },
};

/** "Add link" now opens a `Popover` (2026-08 UX audit, sixth pass: create
 * flows are a layer, not a permanently-visible inline row — style guide
 * Principle 3) anchored to the trigger button, rather than rendering the
 * target/type selects inline below the list at all times. */
export const AddLink: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"], {}, {
      otherRequirements: [buildRequirement({ id: "requirement-2", unique_code: "AUTH-LOG-002", name: "Users can enable two-factor authentication" })],
    });
    spyOn(api, "post").mockResolvedValue(buildComment());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Add link" })).toBeInTheDocument());
    // Selects aren't in the document until the popover trigger opens it.
    await expect(canvas.queryByLabelText("Target requirement")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add link" }));

    const popover = within(document.body).getByRole("dialog", { name: "Add link" });
    await userEvent.selectOptions(within(popover).getByLabelText("Target requirement"), "requirement-2");
    await userEvent.selectOptions(within(popover).getByLabelText("Link type"), "lt1");
    await userEvent.click(within(popover).getByRole("button", { name: "Add link" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/links`,
        { target_requirement_id: "requirement-2", link_type_id: "lt1" }
      )
    );
    // A successful add closes the popover.
    await waitFor(() => expect(within(document.body).queryByRole("dialog", { name: "Add link" })).not.toBeInTheDocument());
  },
};

/** Removing a link now opens the shared `ConfirmDialog` (Tier 1) instead of
 * firing `DELETE` immediately — the other half of the sixth-pass audit
 * finding, alongside `AddLink` above. */
export const RemoveLinkConfirms: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"], {}, {
      links: [buildRequirementLink({ id: "link1", display_name: "Depends on", other_requirement_unique_code: "AUTH-LOG-002", other_requirement_name: "Users can enable two-factor authentication" })],
    });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/AUTH-LOG-002/)).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Remove link" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Remove this link?" });
    await expect(dialog).toBeVisible();
    await expect(api.delete).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Remove link" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/links/link1`)
    );
  },
};

/** Actions card populated with a linked action, showing its outcome badge
 * and a link through to `ActionDetailPage`. */
export const ActionsCardPopulated: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"], {}, {
      linkedActions: [buildRequirementAction({ id: "action-1", unique_code: "ACT-001", title: "Review password reset flow", outcome_status: "completed" })],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/ACT-001/)).toBeInTheDocument());
    await expect(canvas.getByText("Completed")).toBeInTheDocument();
  },
};

/** "Link existing action" now opens a `Popover` (one field — fits the
 * style guide's Popover, not `SidePanel`, side of the decision tree)
 * instead of a permanently-visible inline select+button row. */
export const LinkExistingAction: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"], {}, {
      projectActions: [buildRequirementAction({ id: "action-9", unique_code: "ACT-009", title: "Existing action to attach" })],
    });
    spyOn(api, "post").mockResolvedValue(buildComment());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Link existing action" })).toBeInTheDocument());
    await expect(canvas.queryByLabelText("Link existing action")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Link existing action" }));

    const popover = within(document.body).getByRole("dialog", { name: "Link existing action" });
    await userEvent.selectOptions(within(popover).getByLabelText("Link existing action"), "action-9");
    await userEvent.click(within(popover).getByRole("button", { name: "Link existing action" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/actions`,
        { action_id: "action-9" }
      )
    );
  },
};

/** "Create and link a new action" now opens a `SidePanel` (multi-field —
 * the other side of the decision tree) instead of a permanently-visible
 * inline block toggled open below the list. */
export const CreateAndLinkAction: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"]);
    spyOn(api, "post").mockResolvedValue(buildComment());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No actions linked yet.")).toBeInTheDocument());
    await expect(canvas.queryByPlaceholderText("Title")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Create and link a new action" }));

    const panel = within(document.body).getByRole("dialog", { name: "Create and link a new action" });
    await userEvent.type(within(panel).getByPlaceholderText("Title"), "Verify audit log retention");
    await userEvent.selectOptions(within(panel).getByLabelText("Type"), "at1");
    await userEvent.click(within(panel).getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/actions/create-and-link`,
        expect.objectContaining({ title: "Verify audit log retention", action_type_id: "at1" })
      )
    );
    // A successful create closes the panel.
    await waitFor(() => expect(within(document.body).queryByRole("dialog", { name: "Create and link a new action" })).not.toBeInTheDocument());
  },
};

/** Unlinking an action now opens the shared `ConfirmDialog` (Tier 1)
 * instead of firing `DELETE` immediately. */
export const UnlinkActionConfirms: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"], {}, {
      linkedActions: [buildRequirementAction({ id: "action-1", unique_code: "ACT-001", title: "Review password reset flow", outcome_status: "completed" })],
    });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/ACT-001/)).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Unlink" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Unlink this action?" });
    await expect(dialog).toBeVisible();
    await expect(api.delete).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Unlink" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/actions/action-1`)
    );
  },
};

/**
 * C-C-03: this page was one of the 2026-08 UX audit's explicitly named
 * terminology leak sites — "Make change request", the archive confirm
 * dialog, and every other `strings.requirements.*` string on the page used
 * to hardcode the English noun regardless of the project's own Terminology
 * settings, even though `strings.ts`'s `{requirement}`/`{changeRequest}`
 * tokens already existed for the list page and nav. With the page now
 * reading through `useStrings()` instead of a module-scope `t()`, an
 * override actually reaches this page too.
 */
export const TerminologyOverrideAppliesThroughoutPage: Story = {
  decorators: [withTerminology({ requirement: "Spec", change_request: "ECR" })],
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { status: "approved" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Archive" })).toBeInTheDocument());
    // The "Make a change request" link picks up the {changeRequest} token.
    await expect(canvas.getByRole("link", { name: "Make ECR" })).toBeInTheDocument();

    // The archive confirm dialog's title picks up the {requirement} token.
    await userEvent.click(canvas.getByRole("button", { name: "Archive" }));
    await expect(within(document.body).getByRole("dialog", { name: "Archive this Spec?" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ManagerCanArchiveAndComplete, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ManagerCanArchiveAndComplete, globals: { theme: "dark" } };
