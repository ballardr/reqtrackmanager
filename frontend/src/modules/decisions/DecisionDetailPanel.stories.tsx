import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import type { OrgUser } from "../../api/types";
import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { DecisionDetailPanel } from "./DecisionDetailPanel";
import type { Decision, DecisionTypeDefinition } from "./types";

const PROJECT_ID = "project-1";

const DECISION_TYPES: DecisionTypeDefinition[] = [
  { id: "dt-1", project_id: PROJECT_ID, name: "Architecture", sort_order: 0 },
];

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
  },
];

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: "decision-1", project_id: PROJECT_ID, unique_code: "DEC-001", title: "Adopt PostgreSQL for the new service",
    decision_statement: "Use PostgreSQL as the backing store for the billing service.", decision_type_id: "dt-1",
    status: "under_review", decision_date: "2026-02-01", decision_maker_id: "user-1", owner_id: "user-1",
    context: "The legacy MySQL cluster is nearing end of life.", options_considered: "PostgreSQL, MySQL 8, CockroachDB.",
    chosen_option: "PostgreSQL", rationale: "Best fit for our existing operational tooling.", consequences: null,
    assumptions: null, constraints: null, creator_id: "user-1", is_archived: false, archived_at: null,
    archived_by: null, is_locked: false, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockDetailApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/comments")) return [];
    if (path.includes("/files")) return [];
    if (path.includes("/relationships")) return [];
    if (path.includes("/requirements")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/**
 * `DecisionDetailPanel` renders via `SidePanel` (and its own `ConfirmDialog`/
 * `DecisionFormModal` children), all of which portal to `document.body`
 * (`createPortal`) — every assertion here queries `within(document.body)`,
 * not `canvasElement`, mirroring `DecisionFormModal.stories.tsx`'s own
 * convention.
 */
const meta: Meta<typeof DecisionDetailPanel> = {
  title: "Modules/Decisions/DecisionDetailPanel",
  component: DecisionDetailPanel,
  args: {
    projectId: PROJECT_ID, decisionTypes: DECISION_TYPES, orgUsers: ORG_USERS, currentUserId: "user-1",
    onClose: fn(), onChanged: fn(),
  },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof DecisionDetailPanel>;

export const UnderReviewShowsApproveReject: Story = {
  args: { decision: decision() },
  beforeEach: mockDetailApis,
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Adopt PostgreSQL for the new service")).toBeInTheDocument());
    await expect(body.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    await expect(body.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  },
};

export const DraftShowsPropose: Story = {
  args: { decision: decision({ status: "draft" }) },
  beforeEach: mockDetailApis,
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByRole("button", { name: "Propose" })).toBeInTheDocument());
  },
};

export const ApprovedIsLockedAndUnEditable: Story = {
  args: { decision: decision({ status: "approved", is_locked: true }) },
  beforeEach: mockDetailApis,
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Adopt PostgreSQL for the new service")).toBeInTheDocument());
    await expect(body.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(body.getByText(/new attachments can no longer be added/)).toBeInTheDocument();
  },
};

export const RejectRequiresComment: Story = {
  args: { decision: decision() },
  beforeEach: mockDetailApis,
  play: async () => {
    const body = within(document.body);
    await waitFor(() => body.getByRole("button", { name: "Reject" }));
    await userEvent.click(body.getByRole("button", { name: "Reject" }));
    const dialog = within(body.getByRole("dialog", { name: "Reject this Decision?" }));
    await expect(dialog.getByRole("button", { name: "Reject" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Rejection comment"), "Needs a cost comparison first.");
    await expect(dialog.getByRole("button", { name: "Reject" })).toBeEnabled();
  },
};

export const ApproveDecision: Story = {
  args: { decision: decision() },
  beforeEach: () => {
    mockDetailApis();
    spyOn(api, "post").mockImplementation(async (path: string) => {
      if (path.endsWith("/approve")) return decision({ status: "approved", is_locked: true });
      throw new Error(`Unmocked POST: ${path}`);
    });
  },
  play: async ({ args }) => {
    const body = within(document.body);
    await waitFor(() => body.getByRole("button", { name: "Approve" }));
    await userEvent.click(body.getByRole("button", { name: "Approve" }));
    const dialog = within(body.getByRole("dialog", { name: "Approve this Decision?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/decisions/decision-1/approve`,
      { comment: null }
    ));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

export const LightTheme: Story = { ...UnderReviewShowsApproveReject };
export const DarkTheme: Story = { ...UnderReviewShowsApproveReject, globals: { theme: "dark" } };
