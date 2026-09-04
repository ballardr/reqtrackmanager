import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ActionTypeDefinition, OrgUser, Requirement, RequirementAction } from "../api/types";
import {
  buildActionType,
  buildComment,
  buildRequirement,
  buildRequirementAction,
  buildUser,
  withAuth,
  withRouter,
  withToast,
} from "../testing/storybook-helpers";
import { ActionDetailPage } from "./ActionDetailPage";

const PROJECT_ID = "project-1";
const ACTION_ID = "action-1";

const actionTypes: ActionTypeDefinition[] = [
  buildActionType({ id: "at1", name: "Review" }),
  buildActionType({ id: "at2", name: "Test" }),
];
const requirement: Requirement = buildRequirement({ id: "req1", unique_code: "AUTH-LOG-001" });
const orgUser: OrgUser = {
  user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true,
  is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
};

function mockActionDetailApis(action: RequirementAction) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith(`/actions/${ACTION_ID}`)) return action;
    if (path.includes("/action-types")) return actionTypes;
    if (path.endsWith(`/actions/${ACTION_ID}/comments`)) return [buildComment({ author_display_name: "Jamie Lee" })];
    if (path.endsWith(`/actions/${ACTION_ID}/files`)) return [];
    if (path.endsWith(`/projects/${PROJECT_ID}/requirements`)) return [requirement];
    if (path.endsWith(`/requirements/${requirement.id}/actions`)) return [action];
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
    if (path.includes("/users")) return [orgUser];
    throw new Error(`unmocked path: ${path}`);
  });
}

const meta: Meta<typeof ActionDetailPage> = {
  title: "Pages/ActionDetailPage",
  component: ActionDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/actions/${ACTION_ID}`, "/projects/:projectId/actions/:actionId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ActionDetailPage>;

export const PendingActionWithLinkedRequirement: Story = {
  beforeEach: () => {
    mockActionDetailApis(buildRequirementAction({ id: ACTION_ID, title: "Review password reset flow", action_type_id: "at1" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: /Review password reset flow/ })).toBeInTheDocument());
    await expect(canvas.getByText(/AUTH-LOG-001/)).toBeInTheDocument();
    await expect(canvas.getByLabelText("Outcome")).toHaveValue("pending");
  },
};

export const TransitionOutcomeToFailed: Story = {
  beforeEach: () => {
    mockActionDetailApis(buildRequirementAction({ id: ACTION_ID, title: "Test 2FA enrolment", action_type_id: "at2" }));
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Outcome")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Outcome"), "failed");
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/actions/${ACTION_ID}`,
        expect.objectContaining({ outcome_status: "failed" })
      )
    );
  },
};

/** Archiving opens the shared `ConfirmDialog`, then shows a success toast
 * (Principle 7 — "every mutation ends with feedback") and reloads in
 * place, matching `RequirementDetailPage`'s archive behaviour. */
export const ArchivingConfirmsAndShowsToast: Story = {
  beforeEach: () => {
    mockActionDetailApis(buildRequirementAction({ id: ACTION_ID, title: "Review password reset flow", action_type_id: "at1" }));
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Archive" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Archive" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Archive this action?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Archive" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/actions/${ACTION_ID}/archive`)
    );
    await expect(within(document.body).getByText("Action archived")).toBeInTheDocument();
  },
};

export const ArchivedActionIsReadOnly: Story = {
  beforeEach: () => {
    mockActionDetailApis(
      buildRequirementAction({ id: ACTION_ID, title: "Archived action", action_type_id: "at1", is_archived: true, archived_at: "2026-02-01T00:00:00Z" })
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Title")).toBeDisabled());
    await expect(canvas.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    // Restore replaces Archive once archived (2026-08 UX audit roadmap:
    // unarchive endpoint + Restore button).
    await expect(canvas.getByRole("button", { name: "Restore" })).toBeInTheDocument();
  },
};

/** Clicking Restore calls the new `/unarchive` endpoint directly — no
 * `ConfirmDialog`, unlike Archive above (mirrors `ProjectAdminPage.tsx`'s
 * existing unarchive button, which also fires immediately) — and shows a
 * success toast. */
export const RestoreActionShowsToast: Story = {
  beforeEach: () => {
    mockActionDetailApis(
      buildRequirementAction({ id: ACTION_ID, title: "Archived action", action_type_id: "at1", is_archived: true, archived_at: "2026-02-01T00:00:00Z" })
    );
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Restore" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Restore" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/actions/${ACTION_ID}/unarchive`)
    );
    await expect(within(document.body).getByText("Action restored")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...PendingActionWithLinkedRequirement, globals: { theme: "light" } };
export const DarkTheme: Story = { ...PendingActionWithLinkedRequirement, globals: { theme: "dark" } };
