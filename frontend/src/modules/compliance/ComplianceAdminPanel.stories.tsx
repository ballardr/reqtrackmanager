import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { ComplianceAdminPanel } from "./ComplianceAdminPanel";
import type { ComplianceActionType, ComplianceMappingRelationshipType, ComplianceRequirement, ComplianceStandard, ComplianceStandardVersion } from "./types";

const ORG_ID = "org-1";

const standard: ComplianceStandard = {
  id: "std-1", organization_id: ORG_ID, reference: "ISO-27001", name: "ISO 27001",
  description: "Information security management.", issuing_organisation: "ISO", owner_id: "user-1",
  creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const version: ComplianceStandardVersion = {
  id: "ver-1", standard_id: "std-1", version_number: 1, version_label: "v1.0", status: "draft",
  effective_date: null, change_note: "", created_by: "user-1", published_at: null, published_by: null,
  retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

/**
 * A stateful mock of the compliance org-router's read/write surface, close
 * enough to the real backend's shapes for these stories' own `play`
 * assertions to prove a full create -> reload -> re-render round trip, the
 * same "assert real state change, not just that a mock fired" standard this
 * repo's other page stories already hold themselves to (see
 * `OrgAdminPage.stories.tsx`'s rename-then-assert-list-updated pattern).
 */
function mockComplianceApis(overrides: {
  standards?: ComplianceStandard[];
  actionTypes?: ComplianceActionType[];
  mappingTypes?: ComplianceMappingRelationshipType[];
  versions?: ComplianceStandardVersion[];
  actionTypesRejected?: boolean;
} = {}) {
  const standards = overrides.standards ?? [standard];
  const actionTypes = overrides.actionTypes ?? [{ id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 }];
  const mappingTypes = overrides.mappingTypes ?? [
    { id: "mt-1", organization_id: ORG_ID, name: "Equivalent", sort_order: 0, implies_equivalence: false },
  ];
  const versions = overrides.versions ?? [version];
  let requirements: ComplianceRequirement[] = [];

  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (overrides.actionTypesRejected && path.includes("/action-types")) {
      throw new ApiError(404, "Compliance module is not enabled for this organisation.");
    }
    if (path.includes("/action-types")) return actionTypes;
    if (path.includes("/mapping-relationship-types")) return mappingTypes;
    if (path.includes("/requirements") && !path.includes("required-actions")) return requirements;
    if (path.includes("/required-actions")) return [];
    if (path.includes("/versions/") ) return version;
    if (path.includes("/versions")) return versions;
    if (path.includes("/standards")) return standards;
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/requirements")) {
      const payload = body as { name: string; reference?: string | null; description?: string; reasoning?: string };
      const created: ComplianceRequirement = {
        id: `req-${requirements.length + 1}`, standard_version_id: version.id, parent_requirement_id: null,
        reference: payload.reference ?? null, name: payload.name, description: payload.description ?? "",
        reasoning: payload.reasoning ?? "", sort_order: requirements.length, created_by: "user-1",
        created_at: "2026-02-01T00:00:00Z", updated_at: "2026-02-01T00:00:00Z",
      };
      requirements = [...requirements, created];
      return created;
    }
    if (path.endsWith("/standards")) {
      const payload = body as { reference: string; name: string; description?: string; issuing_organisation?: string | null };
      return {
        ...standard, id: "std-new", reference: payload.reference, name: payload.name,
        description: payload.description ?? "", issuing_organisation: payload.issuing_organisation ?? null,
      };
    }
    if (path.endsWith("/action-types")) {
      const payload = body as { name: string };
      return { id: "at-new", organization_id: ORG_ID, name: payload.name, sort_order: actionTypes.length };
    }
    return undefined;
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    if (path.includes("/mapping-relationship-types/")) {
      const payload = body as { name: string; implies_equivalence: boolean };
      return { ...mappingTypes[0], ...payload };
    }
    return undefined;
  });
}

const meta: Meta<typeof ComplianceAdminPanel> = {
  title: "Modules/Compliance/ComplianceAdminPanel",
  component: ComplianceAdminPanel,
  args: { orgId: ORG_ID },
  decorators: [withRouter("/"), withToast()],
};
export default meta;

type Story = StoryObj<typeof ComplianceAdminPanel>;

export const StandardsListAndCreate: Story = {
  beforeEach: () => mockComplianceApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("ISO 27001")).toBeInTheDocument());
    await expect(canvas.getByText("ISO-27001")).toBeInTheDocument();

    // `Modal`/`SidePanel` render through a `createPortal` into
    // `document.body`, outside `canvasElement`'s own subtree — every query
    // that reaches into one of them must use `within(document.body)`, the
    // same convention `OrgAdminPage.stories.tsx`'s own modal/dropdown
    // assertions already establish.
    await userEvent.click(canvas.getByRole("button", { name: "New standard" }));
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Standard reference"), "SOC2");
    await userEvent.type(body.getByLabelText("Standard name"), "SOC 2");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining("/standards"),
      expect.objectContaining({ reference: "SOC2", name: "SOC 2" })
    ));
  },
};

export const StandardDetailAndVersionWorkspace: Story = {
  beforeEach: () => mockComplianceApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByText("ISO 27001")).toBeInTheDocument());

    // Open the standard's detail `SidePanel` (portalled — see the note above).
    await userEvent.click(canvas.getByRole("button", { name: /ISO-27001/ }));
    await waitFor(() => expect(body.getByRole("button", { name: "v1.0" })).toBeInTheDocument());

    // Drill into the version workspace — this replaces the Standards tab's
    // own content in place (not portalled), so it's back to `canvas` again.
    await userEvent.click(body.getByRole("button", { name: "v1.0" }));
    await waitFor(() => expect(canvas.getByText("No requirements defined for this version yet.")).toBeInTheDocument());

    // Add a root requirement (its form is a portalled `Modal` again) —
    // proves the full create -> reload round trip.
    await userEvent.click(canvas.getByRole("button", { name: "Add requirement" }));
    await userEvent.type(body.getByLabelText("Requirement name"), "Access control policy");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(canvas.getByText("Access control policy")).toBeInTheDocument());
    await expect(canvas.queryByText("No requirements defined for this version yet.")).not.toBeInTheDocument();
  },
};

export const ActionTypesTab: Story = {
  beforeEach: () => mockComplianceApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("tab", { name: "Action types" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("tab", { name: "Action types" }));
    await expect(await canvas.findByDisplayValue("Review")).toBeInTheDocument();

    await userEvent.type(canvas.getByPlaceholderText("Action type name"), "Evidence review");
    await userEvent.click(canvas.getByRole("button", { name: "Add action type" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining("/action-types"),
      expect.objectContaining({ name: "Evidence review" })
    ));
  },
};

export const MappingTypesTabToggleImpliesEquivalence: Story = {
  beforeEach: () => mockComplianceApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "Mapping types" }));
    const toggle = await canvas.findByRole("switch", { name: "Implies equivalence for Equivalent" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");

    await userEvent.click(toggle);
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      expect.stringContaining("/mapping-relationship-types/"),
      expect.objectContaining({ name: "Equivalent", implies_equivalence: true })
    ));
  },
};

export const ModuleNotEnabled: Story = {
  beforeEach: () => mockComplianceApis({ actionTypesRejected: true }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByText("Compliance module is not enabled for this organisation.")).toBeInTheDocument()
    );
  },
};

export const LightTheme: Story = { ...StandardsListAndCreate };
export const DarkTheme: Story = { ...StandardsListAndCreate, globals: { theme: "dark" } };
