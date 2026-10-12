import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, waitFor, within } from "storybook/test";

import type { Principal } from "../../api/types";
import { withRouter } from "../../testing/storybook-helpers";
import { DecisionQuickViewPanel } from "./DecisionQuickViewPanel";
import type { Decision, DecisionTypeDefinition } from "./types";

const PROJECT_ID = "project-1";

const DECISION_TYPES: DecisionTypeDefinition[] = [
  { id: "dt-1", project_id: PROJECT_ID, name: "Architecture", sort_order: 0 },
];

const USER_ALEX: Principal = { type: "user", id: "user-1", label: "Alex Morgan", member_count: null, exists: true };
const GROUP_PLATFORM: Principal = {
  type: "org_group", id: "group-1", label: "Platform Architecture", member_count: 3, exists: true,
};

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: "decision-1", project_id: PROJECT_ID, unique_code: "DEC-001", title: "Adopt PostgreSQL for the new service",
    decision_statement: "Use PostgreSQL as the backing store for the billing service.", decision_type_id: "dt-1",
    status: "under_review", decision_date: "2026-02-01", decision_maker: USER_ALEX, owner: GROUP_PLATFORM,
    context: null, options_considered: null, chosen_option: null, rationale: null, consequences: null,
    assumptions: null, constraints: null, creator_id: "user-1", is_archived: false, archived_at: null,
    archived_by: null, is_locked: false, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

/**
 * A minimal, read-only peek (Phase 9, 2026-09-22) — see this component's
 * own docstring and `docs/ux-style-guide.md`'s "Pattern: entity detail
 * panel" checklist. Portals via `SidePanel` (`createPortal`), so
 * assertions query `document.body`, not `canvasElement`.
 */
const meta: Meta<typeof DecisionQuickViewPanel> = {
  title: "Modules/Decisions/DecisionQuickViewPanel",
  component: DecisionQuickViewPanel,
  args: { projectId: PROJECT_ID, decisionTypes: DECISION_TYPES, onClose: fn() },
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/decisions`, "/projects/:projectId/modules/decisions")],
};
export default meta;

type Story = StoryObj<typeof DecisionQuickViewPanel>;

export const ShowsIdentifyingFieldsOnly: Story = {
  args: { decision: decision() },
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Adopt PostgreSQL for the new service")).toBeInTheDocument());
    await expect(body.getByText("Under review")).toBeInTheDocument();
    await expect(body.getByText("Architecture")).toBeInTheDocument();
    await expect(body.getByText(/Use PostgreSQL as the backing store/)).toBeInTheDocument();
    // A group owner shows its name, kind and member count; the decision maker is a user.
    await expect(body.getByText("Platform Architecture")).toBeInTheDocument();
    await expect(body.getByText("Org group · 3 members")).toBeInTheDocument();
    await expect(body.getByText("Alex Morgan")).toBeInTheDocument();
    // No lifecycle/edit controls — read-only per this pattern's own rule.
    await expect(body.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    await expect(body.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(body.getByRole("link", { name: "View full details" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/modules/decisions/decision-1`
    );
  },
};

export const LightTheme: Story = { ...ShowsIdentifyingFieldsOnly };
export const DarkTheme: Story = { ...ShowsIdentifyingFieldsOnly, globals: { theme: "dark" } };
