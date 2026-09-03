import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ActionTypeDefinition, FileAsset, LinkTypeDefinition, ProjectRole, Requirement, RequirementAction, RequirementLink, RequirementVersionEntry } from "../api/types";
import {
  buildActionType,
  buildComment,
  buildFileAsset,
  buildLinkType,
  buildProjectListItem,
  buildRequirement,
  buildRequirementAction,
  buildRequirementLink,
  buildUser,
  withAuth,
  withRouter,
  withStatefulAuth,
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
  extra: {
    links?: RequirementLink[];
    linkedActions?: RequirementAction[];
    projectActions?: RequirementAction[];
    otherRequirements?: Requirement[];
    history?: RequirementVersionEntry[];
    orgResources?: FileAsset[];
  } = {}
) {
  const requirement = buildRequirement({ id: REQUIREMENT_ID, project_id: PROJECT_ID, ...requirementOverrides });
  const linkTypes: LinkTypeDefinition[] = [buildLinkType({ id: "lt1", forward_name: "Depends on", reverse_name: "Is a dependency of" })];
  const actionTypes: ActionTypeDefinition[] = [buildActionType({ id: "at1", name: "Review" })];
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("archived=false")) return [buildProjectListItem({ id: PROJECT_ID, my_roles: myRoles })];
    if (path.endsWith(`/requirements/${REQUIREMENT_ID}`)) return requirement;
    if (path.endsWith("/history")) return extra.history ?? [];
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
    if (path.endsWith("/resources")) return extra.orgResources ?? [];
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

/** A stakeholder can edit the form fields (while still unlocked — draft) but
 * cannot archive or complete — `canArchive` stays false for this role. */
export const StakeholderCanEditNotArchive: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"], { status: "draft" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Name")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Mark completed" })).not.toBeInTheDocument();
  },
};

/**
 * A still-draft requirement (2026-08 UX audit roadmap, "No requirement
 * approval action") — a project manager sees the new "Approve" action
 * (`requires_approval` is true for draft/reviewed status), but not "Make
 * change request", since a change request can only target an already-locked
 * requirement; a stakeholder sees neither, since approval is PM-only.
 */
export const ManagerCanApproveDraftRequirement: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { status: "draft" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const approveButton = await canvas.findByRole("button", { name: "Approve" });
    await expect(canvas.queryByRole("link", { name: "Make change request" })).not.toBeInTheDocument();

    await userEvent.click(approveButton);
    await waitFor(() => expect(within(document.body).getByText("Requirement approved")).toBeInTheDocument());
  },
};

export const StakeholderDoesNotSeeApproveOnDraftRequirement: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["stakeholder"], { status: "draft" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Name")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "Make change request" })).not.toBeInTheDocument();
  },
};

/** A project manager can archive and — because status is "approved" — mark
 * the requirement completed. Being locked (status "approved" is locked for
 * every role, per C-G-12 — content is read-only until a change request is
 * approved), "Make change request" is offered instead of an edit form;
 * "Approve" is not, since it's no longer draft/reviewed. */
export const ManagerCanArchiveAndComplete: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { status: "approved" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Archive" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Mark completed" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Make change request" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
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

/** Once completed (C-G-11: `is_completed` is an overlay on top of
 * `approved`, not a separate status), a manager sees "Revert completion"
 * instead of "Mark completed", plus a distinct "Completed" badge alongside
 * the (still-"Approved") status badge — mirrors the lifecycle diagram in
 * help/02-requirement-lifecycle.md. */
export const CompletedRequirementShowsRevert: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_administrator"], {
      status: "approved", is_completed: true, completed_at: "2026-02-01T09:00:00Z", completed_by: "user-1",
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Revert completion" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Mark completed" })).not.toBeInTheDocument();
    await expect(canvas.getByText("Status: Approved")).toBeInTheDocument();
    await expect(canvas.getByText("Completed")).toBeInTheDocument();
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

/** Same lock rule as `CreateAndLinkActionRoutesThroughChangeRequestOnceLocked`,
 * above, for the link-existing side of the split (item 514). */
export const LinkExistingActionRoutesThroughChangeRequestOnceLocked: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { is_locked: true, status: "approved" }, {
      projectActions: [buildRequirementAction({ id: "action-9", unique_code: "ACT-009", title: "Existing action to attach" })],
    });
    spyOn(api, "post").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Link existing action" }));

    const popover = within(document.body).getByRole("dialog", { name: "Link existing action" });
    await userEvent.selectOptions(within(popover).getByLabelText("Link existing action"), "action-9");
    const linkButton = within(popover).getByRole("button", { name: "Link existing action" });
    await expect(linkButton).toBeDisabled();
    await userEvent.type(within(popover).getByLabelText("Reason for change"), "this review already covers it");
    await userEvent.click(linkButton);

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/change-requests`,
        expect.objectContaining({
          kind: "add_action", requirement_id: REQUIREMENT_ID,
          proposed_action_link_id: "action-9", reason: "this review already covers it",
        })
      )
    );
    expect(api.post).not.toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/actions`, expect.anything()
    );
  },
};

/** "Create and link a new action" now opens a `Modal` — a brand-new
 * `Action` has no "what came before it" to be contextual detail about, so
 * per the revised Principle 3 it no longer belongs in `SidePanel`. */
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

/** 2026-08 UX audit roadmap item 514: once the requirement is locked
 * (APPROVED/COMPLETED), "Create and link a new action" no longer calls the
 * direct create-and-link endpoint — it requires a reason and submits an
 * `ADD_ACTION` change request instead, the same change-request-only-once-
 * locked rule the requirement's own fields already follow. */
export const CreateAndLinkActionRoutesThroughChangeRequestOnceLocked: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { is_locked: true, status: "approved" });
    spyOn(api, "post").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No actions linked yet.")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Create and link a new action" }));

    const panel = within(document.body).getByRole("dialog", { name: "Create and link a new action" });
    await userEvent.type(within(panel).getByPlaceholderText("Title"), "Verify audit log retention");
    await userEvent.selectOptions(within(panel).getByLabelText("Type"), "at1");
    const createButton = within(panel).getByRole("button", { name: "Create" });
    await expect(createButton).toBeDisabled();
    await userEvent.type(within(panel).getByLabelText("Reason for change"), "found a gap during final review");
    await expect(createButton).toBeEnabled();
    await userEvent.click(createButton);

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/change-requests`,
        expect.objectContaining({
          kind: "add_action", requirement_id: REQUIREMENT_ID,
          proposed_action_title: "Verify audit log retention", proposed_action_type_id: "at1",
          reason: "found a gap during final review",
        })
      )
    );
    expect(api.post).not.toHaveBeenCalledWith(
      expect.stringContaining("/actions/create-and-link"), expect.anything()
    );
    await waitFor(() => expect(within(document.body).getByText("Change request created")).toBeInTheDocument());
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

/** Version-history table renders each row's status through
 * `REQUIREMENT_STATUS_LABEL` (2026-08 UX audit roadmap, "Fix raw-enum
 * filter/table text"), matching the status badge above it on the same
 * page — not the raw backend enum string. */
export const VersionHistoryShowsLabelledStatus: Story = {
  // The meta's default `withAuth` has a no-op `setUiPreference`, so
  // clicking the view toggle below wouldn't actually switch views —
  // `withStatefulAuth` is needed for the toggle's click to take effect.
  decorators: [withStatefulAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" }))],
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { status: "approved" }, {
      history: [
        {
          version_number: 1, name: "Reset password", reasoning: "r", clarification: "", description: "",
          status: "reviewed", owner_id: "user-1", target_stage_id: "s1", level: "requirement",
          change_note: "Initial submission", change_request_id: null, created_by: "user-1",
          created_at: "2026-01-01T00:00:00Z", valid_to: "2026-01-02T00:00:00Z",
        },
      ],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // History and Activity share one card with a view toggle (2026-08 UX
    // audit roadmap item 516), defaulting to Activity — switch to Version
    // history before the table is on screen at all.
    await userEvent.click(canvas.getByRole("button", { name: "Version history" }));
    await waitFor(() => expect(canvas.getByText("Initial submission")).toBeInTheDocument());
    await expect(canvas.getByRole("cell", { name: "Reviewed" })).toBeInTheDocument();
    await expect(canvas.queryByRole("cell", { name: "reviewed" })).not.toBeInTheDocument();
  },
};

/** History and Activity merged into one card with a view toggle (2026-08
 * UX audit roadmap item 516) — both renderings are kept, the toggle just
 * switches which one shows. Defaults to Activity (see the page's own
 * comment on `historyViewRaw` for why); uses `withStatefulAuth` rather than
 * the meta's default `withAuth`, since a no-op `setUiPreference` couldn't
 * actually change the pressed toggle button or which view renders. */
export const HistoryActivityToggleSwitchesViews: Story = {
  decorators: [withStatefulAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" }))],
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], {}, {
      history: [
        {
          version_number: 1, name: "Reset password", reasoning: "r", clarification: "", description: "",
          status: "reviewed", owner_id: "user-1", target_stage_id: "s1", level: "requirement",
          change_note: "Initial submission", change_request_id: null, created_by: "user-1",
          created_at: "2026-01-01T00:00:00Z", valid_to: "2026-01-02T00:00:00Z",
        },
      ],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Defaults to Activity: the version table isn't on screen yet, and the
    // Activity toggle button is the pressed one.
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Activity", level: 2 })).toBeInTheDocument());
    await expect(canvas.queryByText("Initial submission")).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Activity" })).toHaveAttribute("aria-pressed", "true");
    await expect(canvas.getByRole("button", { name: "Version history" })).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(canvas.getByRole("button", { name: "Version history" }));
    await expect(canvas.getByRole("heading", { name: "Version history", level: 2 })).toBeInTheDocument();
    await expect(canvas.getByText("Initial submission")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Version history" })).toHaveAttribute("aria-pressed", "true");
    await expect(canvas.getByRole("button", { name: "Activity" })).toHaveAttribute("aria-pressed", "false");

    // Switching back shows the Activity feed again — neither rendering was
    // dropped in favour of the other.
    await userEvent.click(canvas.getByRole("button", { name: "Activity" }));
    await expect(canvas.getByRole("heading", { name: "Activity", level: 2 })).toBeInTheDocument();
    await expect(canvas.queryByText("Initial submission")).not.toBeInTheDocument();
  },
};

/** The merged card no longer sits in a two-column `.side-grid` with a
 * separate narrow Activity sidebar — confirms the single-card shell by
 * checking there's exactly one "Activity"/"Version history" heading on the
 * page, not the old duplicate ("Change log" card in the main column plus a
 * standalone "Activity" sidebar panel). */
export const NoDuplicateHistoryOrActivityCard: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Activity", level: 2 })).toBeInTheDocument());
    await expect(canvas.getAllByRole("heading", { name: "Activity", level: 2 })).toHaveLength(1);
    await expect(canvas.queryByRole("heading", { name: "Change log" })).not.toBeInTheDocument();
  },
};

/** `Pattern: resource picker dialog` (2026-08 UX audit roadmap row 508) —
 * the Attachments card's new "Link from shared resources" button opens
 * `ResourcePickerModal` over the org's shared resources, and "Attach
 * selected" calls the previously frontend-uncalled `POST .../files/link`
 * endpoint once per selected file. */
export const LinkFromSharedResourcesAttachesFile: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], {}, {
      orgResources: [buildFileAsset({ id: "res-1", filename: "safety-spec.pdf", is_org_resource: true })],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Attachments" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Link from shared resources" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Link from shared resources" });
    await waitFor(() => expect(within(dialog).getByText("safety-spec.pdf")).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("checkbox"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Attach 1 selected" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/files/link`,
        { file_id: "res-1" }
      )
    );
    // Dialog closes once the attach succeeds.
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

/** The button is hidden once the requirement is locked, matching the
 * direct-upload trigger's own lock gating in `FileAttachmentList` — a
 * locked requirement's attachments can only change via a change request. */
export const LinkFromSharedResourcesHiddenWhenLocked: Story = {
  beforeEach: () => {
    mockRequirementDetailApis(["project_manager"], { is_locked: true, status: "approved" }, {
      orgResources: [buildFileAsset({ id: "res-1", filename: "safety-spec.pdf", is_org_resource: true })],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Attachments" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Link from shared resources" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ManagerCanArchiveAndComplete, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ManagerCanArchiveAndComplete, globals: { theme: "dark" } };
