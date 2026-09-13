import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import type { OrgUser } from "../../api/types";
import { api } from "../../api/client";
import { buildProjectListItem } from "../../testing/storybook-helpers";
import { withToast } from "../../testing/storybook-helpers";
import { StandardApplicabilityPanel } from "./StandardApplicabilityPanel";
import type { ComplianceStandard, ComplianceStandardDefaultExclusion } from "./types";

const ORG_ID = "org-1";

function standard(overrides: Partial<ComplianceStandard> = {}): ComplianceStandard {
  return {
    id: "std-1", organization_id: ORG_ID, reference: "ISO-27001", name: "ISO 27001",
    description: "", issuing_organisation: "ISO", owner_id: "user-1", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null,
    applicability_default: "opt_in", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function orgUser(overrides: Partial<OrgUser> = {}): OrgUser {
  return {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Rivera", is_active: true,
    is_archived: false, roles: [], display_name_locked: false, last_login_at: null, is_2fa_enabled: false,
    module_roles: [], ...overrides,
  };
}

function exclusion(overrides: Partial<ComplianceStandardDefaultExclusion> = {}): ComplianceStandardDefaultExclusion {
  return {
    id: "exc-1", standard_id: "std-1", project_id: "proj-2", excluded_by: "user-1",
    excluded_at: "2026-02-01T00:00:00Z", reason: "Legacy platform, standard does not apply.",
    created_at: "2026-02-01T00:00:00Z", updated_at: "2026-02-01T00:00:00Z", ...overrides,
  };
}

function mockApis(options: { exclusions?: ComplianceStandardDefaultExclusion[] } = {}) {
  let exclusions = options.exclusions ?? [];
  const projects = [
    buildProjectListItem({ id: "proj-1", organization_id: ORG_ID, name: "Atlas Platform" }),
    buildProjectListItem({ id: "proj-2", organization_id: ORG_ID, name: "Legacy System" }),
  ];
  const orgUsers: OrgUser[] = [orgUser()];

  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/exclusions")) return exclusions;
    if (path.startsWith("/api/v1/projects?")) return projects;
    if (path.endsWith("/users")) return orgUsers;
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/applicability-default")) {
      const payload = body as { applicability_default: "opt_in" | "applies_to_all_projects" };
      return standard({ applicability_default: payload.applicability_default });
    }
    throw new Error(`unmocked PATCH: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/exclusions")) {
      const payload = body as { project_id: string; reason: string };
      const created = exclusion({ id: `exc-${exclusions.length + 2}`, project_id: payload.project_id, reason: payload.reason });
      exclusions = [...exclusions, created];
      return created;
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const projectId = path.split("/exclusions/")[1];
    exclusions = exclusions.filter((e) => e.project_id !== projectId);
  });
}

/**
 * Phase 20's org-wide-mandate secondary path — the toggle switching a
 * standard's `applicability_default`, and (once switched on) the
 * exclusion-list `DirectoryTable` + "Exclude a project" modal. The
 * default, primary Project-Manager self-service assignment path has no
 * story here — it's exercised by `ProjectCompliancePage.stories.tsx`'s
 * own `AssignStandardFlow` instead, since it's a project-scoped action
 * this panel never touches.
 */
const meta: Meta<typeof StandardApplicabilityPanel> = {
  title: "Modules/Compliance/StandardApplicabilityPanel",
  component: StandardApplicabilityPanel,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof StandardApplicabilityPanel>;

export const OptInDefault: Story = {
  args: { standard: standard(), onStandardChanged: () => {} },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("switch")).toHaveAttribute("aria-checked", "false"));
    await expect(canvas.queryByText("Excluded projects")).not.toBeInTheDocument();
  },
};

export const AppliesToAllWithExclusions: Story = {
  args: { standard: standard({ applicability_default: "applies_to_all_projects" }), onStandardChanged: () => {} },
  beforeEach: () => mockApis({ exclusions: [exclusion()] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("switch")).toHaveAttribute("aria-checked", "true"));
    await waitFor(() => expect(canvas.getByText("Legacy System")).toBeInTheDocument());
    await expect(canvas.getByText("Legacy platform, standard does not apply.")).toBeInTheDocument();
  },
};

export const ToggleOn: Story = {
  args: { standard: standard(), onStandardChanged: () => {} },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("switch")).toHaveAttribute("aria-checked", "false"));
    await userEvent.click(canvas.getByRole("switch"));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/std-1/applicability-default`,
      { applicability_default: "applies_to_all_projects" }
    ));
  },
};

export const ExcludeProjectFlow: Story = {
  args: { standard: standard({ applicability_default: "applies_to_all_projects" }), onStandardChanged: () => {} },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Exclude a project" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Exclude a project" }));

    await waitFor(() => expect(body.getByLabelText("Project")).toBeInTheDocument());
    await userEvent.selectOptions(body.getByLabelText("Project"), "proj-2");
    // Mandatory reason: the confirm button stays disabled until filled in.
    await expect(body.getByRole("button", { name: "Exclude" })).toBeDisabled();
    await userEvent.type(body.getByLabelText("Reason (required)"), "Not applicable to this project.");
    await expect(body.getByRole("button", { name: "Exclude" })).toBeEnabled();
    await userEvent.click(body.getByRole("button", { name: "Exclude" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/std-1/exclusions`,
      { project_id: "proj-2", reason: "Not applicable to this project." }
    ));
  },
};

export const RemoveExclusion: Story = {
  args: { standard: standard({ applicability_default: "applies_to_all_projects" }), onStandardChanged: () => {} },
  beforeEach: () => mockApis({ exclusions: [exclusion()] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Legacy System")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/std-1/exclusions/proj-2`
    ));
  },
};

export const LightTheme: Story = { ...AppliesToAllWithExclusions };
