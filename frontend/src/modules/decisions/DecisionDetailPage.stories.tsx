import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import type { OrgUser } from "../../api/types";
import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { DecisionDetailPage } from "./DecisionDetailPage";
import type { Decision, DecisionTypeDefinition } from "./types";

const PROJECT_ID = "project-1";
const DECISION_ID = "decision-1";

const DECISION_TYPES: DecisionTypeDefinition[] = [
  { id: "dt-1", project_id: PROJECT_ID, name: "Architecture", sort_order: 0 },
];

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: DECISION_ID, project_id: PROJECT_ID, unique_code: "DEC-001", title: "Adopt PostgreSQL for the new service",
    decision_statement: "Use PostgreSQL as the backing store for the billing service.", decision_type_id: "dt-1",
    status: "under_review", decision_date: "2026-02-01", decision_maker_id: "user-1", owner_id: "user-1",
    context: "The legacy MySQL cluster is nearing end of life.", options_considered: "PostgreSQL, MySQL 8, CockroachDB.",
    chosen_option: "PostgreSQL", rationale: "Best fit for our existing operational tooling.", consequences: null,
    assumptions: null, constraints: null, creator_id: "user-1", is_archived: false, archived_at: null,
    archived_by: null, is_locked: false, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockDetailApis(current: Decision) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith(`/decisions/${DECISION_ID}`)) return current;
    if (path.includes("/decision-types")) return DECISION_TYPES;
    if (path.includes("/comments")) return [];
    if (path.includes("/files")) return [];
    if (path.includes("/relationships")) return [];
    if (path.includes("/requirements")) return [];
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: "org-1" };
    if (path.includes("/users")) return ORG_USERS;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/**
 * `DecisionDetailPage` replaced the `SidePanel`-only `DecisionDetailPanel`
 * (Phase 9, 2026-09-22) — see that page's own module docstring. It's a real
 * routed page, so stories go through `withRouter`/`withAuth` rather than
 * passing props directly.
 */
const meta: Meta<typeof DecisionDetailPage> = {
  title: "Modules/Decisions/DecisionDetailPage",
  component: DecisionDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/modules/decisions/${DECISION_ID}`, "/projects/:projectId/modules/decisions/:decisionId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof DecisionDetailPage>;

export const UnderReviewShowsApproveReject: Story = {
  beforeEach: () => mockDetailApis(decision()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Adopt PostgreSQL for the new service")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  },
};

export const DraftShowsPropose: Story = {
  beforeEach: () => mockDetailApis(decision({ status: "draft" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Propose" })).toBeInTheDocument());
  },
};

export const ApprovedIsLockedAndUnEditable: Story = {
  beforeEach: () => mockDetailApis(decision({ status: "approved", is_locked: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Adopt PostgreSQL for the new service")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/new attachments can no longer be added/)).toBeInTheDocument();
  },
};

export const RejectRequiresComment: Story = {
  beforeEach: () => mockDetailApis(decision()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Reject" }));
    await userEvent.click(canvas.getByRole("button", { name: "Reject" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Reject this Decision?" }));
    await expect(dialog.getByRole("button", { name: "Reject" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Rejection comment"), "Needs a cost comparison first.");
    await expect(dialog.getByRole("button", { name: "Reject" })).toBeEnabled();
  },
};

export const ApproveDecision: Story = {
  beforeEach: () => {
    mockDetailApis(decision());
    spyOn(api, "post").mockImplementation(async (path: string) => {
      if (path.endsWith("/approve")) return decision({ status: "approved", is_locked: true });
      throw new Error(`Unmocked POST: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Approve" }));
    await userEvent.click(canvas.getByRole("button", { name: "Approve" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Approve this Decision?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/decisions/${DECISION_ID}/approve`,
      { comment: null }
    ));
    await waitFor(() => expect(canvas.getByText("Approved")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...UnderReviewShowsApproveReject };
export const DarkTheme: Story = { ...UnderReviewShowsApproveReject, globals: { theme: "dark" } };
