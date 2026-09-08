import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { StandardWorkspacePage } from "./StandardWorkspacePage";
import type { ComplianceActionType, ComplianceAuditEvent, ComplianceStandard, ComplianceStandardVersion } from "./types";

const STANDARD: ComplianceStandard = {
  id: "std-1", organization_id: "org-1", reference: "ISO-27001", name: "ISO 27001",
  description: "Information security management.", issuing_organisation: "ISO", owner_id: "user-1",
  creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const VERSION: ComplianceStandardVersion = {
  id: "ver-1", standard_id: STANDARD.id, version_number: 1, version_label: "v1.0", status: "draft",
  effective_date: null, change_note: "", created_by: "user-1", published_at: null, published_by: null,
  retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const ACTION_TYPES: ComplianceActionType[] = [];
const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false,
    roles: ["org_admin"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
  },
];
const HISTORY: ComplianceAuditEvent[] = [
  { id: "ev-1", entity_type: "compliance_standard", entity_id: STANDARD.id, action: "created", actor_id: "user-1", detail: null, created_at: "2026-01-01T00:00:00Z" },
];

function mockWorkspaceApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/compliance/standards/${STANDARD.id}`) return STANDARD;
    if (path.endsWith("/action-types")) return ACTION_TYPES;
    if (path.endsWith("/users")) return ORG_USERS;
    if (path.endsWith("/versions")) return [VERSION];
    if (path.endsWith("/history")) return HISTORY;
    if (path.includes("/requirements") && !path.includes("required-actions")) return [];
    throw new Error(`unmocked GET: ${path}`);
  });
}

/**
 * `StandardWorkspacePage` — the per-standard drill-down at `/standards/
 * :standardId[/versions|/history]` (docs/compliance-module-plan.md Phase
 * 18). Resolves its owning org via the new `GET /api/v1/compliance/
 * standards/{id}` before threading it through to every existing org-scoped
 * nested call (action types, versions, history) unchanged.
 */
const meta: Meta<typeof StandardWorkspacePage> = {
  title: "Modules/Compliance/StandardWorkspacePage",
  component: StandardWorkspacePage,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof StandardWorkspacePage>;

export const Overview: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}`, "/standards/:standardId/:section?")],
  beforeEach: mockWorkspaceApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: /ISO-27001 — ISO 27001/ })).toBeInTheDocument());
    await expect(canvas.getByText("Information security management.")).toBeInTheDocument();
    await expect(canvas.getByText("Issued by ISO")).toBeInTheDocument();
  },
};

export const VersionsSection: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/versions`, "/standards/:standardId/:section?")],
  beforeEach: mockWorkspaceApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "v1.0" })).toBeInTheDocument());
  },
};

export const HistorySection: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/history`, "/standards/:standardId/:section?")],
  beforeEach: mockWorkspaceApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("listitem")).toBeInTheDocument());
    const item = canvas.getByRole("listitem");
    await expect(item).toHaveTextContent("Alex Morgan");
    await expect(item).toHaveTextContent("created");
  },
};

export const NotFound: Story = {
  decorators: [withRouter("/standards/does-not-exist", "/standards/:standardId/:section?")],
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("404"));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByText(/This compliance standard could not be found/)).toBeInTheDocument()
    );
  },
};
