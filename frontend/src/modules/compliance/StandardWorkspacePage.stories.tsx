import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { Organization, OrgUser } from "../../api/types";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { StandardWorkspacePage } from "./StandardWorkspacePage";
import type { ComplianceActionType, ComplianceAuditEvent, ComplianceStandard, ComplianceStandardVersion } from "./types";

const STANDARD: ComplianceStandard = {
  id: "std-1", organization_id: "org-1", reference: "ISO-27001", name: "ISO 27001",
  description: "Information security management.", issuing_organisation: "ISO", owner_id: "user-1",
  creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const VERSION: ComplianceStandardVersion = {
  id: "ver-1", standard_id: STANDARD.id, version_number: 1, version_label: "v1.0", status: "draft",
  effective_date: null, change_note: "", summary: "", created_by: "user-1", published_at: null, published_by: null,
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
    if (path.endsWith("/exclusions")) return [];
    if (path.endsWith("/project-summary")) return [];
    if (path.startsWith("/api/v1/projects?")) return [];
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
  decorators: [withToast(), withStatefulAuth(buildUser({ id: "user-1" }))],
};
export default meta;

type Story = StoryObj<typeof StandardWorkspacePage>;

export const Overview: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}`, "/standards/:standardId/:section?/:versionId?")],
  beforeEach: mockWorkspaceApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: /ISO-27001 — ISO 27001/ })).toBeInTheDocument());
    await expect(canvas.getByText("Information security management.")).toBeInTheDocument();
    await expect(canvas.getByText("Issued by ISO")).toBeInTheDocument();
    // Phase 20: the applicability-default panel renders in Overview too.
    await waitFor(() => expect(canvas.getByRole("switch")).toHaveAttribute("aria-checked", "false"));

    // Phase 23: clickable stat tiles — one version, zero requirements (the
    // mock's empty `/requirements` list), zero assigned projects.
    await waitFor(() => {
      const tile = canvas.getByRole("link", { name: /Versions/ });
      expect(within(tile).getByText("1")).toBeInTheDocument();
      expect(tile).toHaveAttribute("href", `/standards/${STANDARD.id}/versions`);
    });
    await waitFor(() => {
      const tile = canvas.getByRole("link", { name: /Requirements/ });
      expect(within(tile).getByText("0")).toBeInTheDocument();
      expect(tile).toHaveAttribute("href", `/standards/${STANDARD.id}/versions/${VERSION.id}`);
    });
    await waitFor(() => {
      expect(canvas.getByRole("link", { name: /^0 Projects$/ })).toHaveAttribute("href", `/standards/${STANDARD.id}/projects`);
    });
    await waitFor(() => {
      expect(canvas.getByRole("link", { name: /Compliant/ })).toHaveAttribute(
        "href", `/standards/${STANDARD.id}/projects?state=compliant`
      );
    });
  },
};

export const ExportsStandard: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}`, "/standards/:standardId/:section?/:versionId?")],
  beforeEach: () => {
    mockWorkspaceApis();
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["{}"], { type: "application/json" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Export" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await waitFor(() =>
      expect(api.getForBlob).toHaveBeenCalledWith(
        `/api/v1/orgs/${STANDARD.organization_id}/modules/compliance/standards/${STANDARD.id}/export`
      )
    );
  },
};

export const VersionsSection: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/versions`, "/standards/:standardId/:section?/:versionId?")],
  beforeEach: mockWorkspaceApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "v1.0" })).toBeInTheDocument());
  },
};

export const VersionDeepLink: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/versions/${VERSION.id}`, "/standards/:standardId/:section?/:versionId?")],
  beforeEach: mockWorkspaceApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Landing directly on `/versions/:versionId` opens `VersionWorkspace`
    // straight away, rather than the plain version list.
    await waitFor(() => expect(canvas.getByText(`ISO-27001 — ${VERSION.version_label}`)).toBeInTheDocument());
  },
};

export const ProjectsSection: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/projects`, "/standards/:standardId/:section?/:versionId?")],
  beforeEach: mockWorkspaceApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No projects match this filter.")).toBeInTheDocument());
  },
};

export const HistorySection: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/history`, "/standards/:standardId/:section?/:versionId?")],
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
  decorators: [withRouter("/standards/does-not-exist", "/standards/:standardId/:section?/:versionId?")],
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

const ORG: Organization = {
  id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
};
const SIBLING_STANDARD: ComplianceStandard = {
  ...STANDARD, id: "std-2", reference: "EN-60529", name: "EN 60529", organization_id: ORG.id,
};

/** Phase 28 — with more than one standard reachable across the caller's
 * orgs, a chevron next to the standard's name opens a popover listing the
 * others as plain links to their own workspace, via the same cross-org
 * fan-out `StandardListPage.tsx` uses (`listStandardsAcrossMyOrgs`). */
export const EntitySwitcherOffersSiblingStandards: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}`, "/standards/:standardId/:section?/:versionId?")],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === `/api/v1/compliance/standards/${STANDARD.id}`) return STANDARD;
      if (path.endsWith("/action-types")) return ACTION_TYPES;
      if (path.endsWith("/users")) return ORG_USERS;
      if (path.endsWith("/versions")) return [VERSION];
      if (path.endsWith("/history")) return HISTORY;
      if (path.endsWith("/exclusions")) return [];
      if (path.endsWith("/project-summary")) return [];
      if (path.startsWith("/api/v1/projects?")) return [];
      if (path.includes("/requirements") && !path.includes("required-actions")) return [];
      if (path === "/api/v1/orgs?mine=true") return [ORG];
      if (path === `/api/v1/orgs/${ORG.id}/modules/compliance/standards?include_archived=false`) {
        return [STANDARD, SIBLING_STANDARD];
      }
      throw new Error(`unmocked GET: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: /ISO-27001 — ISO 27001/ })).toBeInTheDocument());

    const trigger = await canvas.findByRole("button", { name: "Switch standard" });
    await userEvent.click(trigger);
    const dialog = within(document.body).getByRole("dialog", { name: "Switch standard" });
    await expect(within(dialog).getByRole("link", { name: "EN-60529 — EN 60529" })).toHaveAttribute(
      "href",
      `/standards/${SIBLING_STANDARD.id}`
    );
  },
};
