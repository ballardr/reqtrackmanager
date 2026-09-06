import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { RequirementMappingsModal } from "./RequirementMappingsModal";
import type {
  ComplianceMappingRelationshipType,
  ComplianceRequirement,
  ComplianceRequirementMapping,
  ComplianceStandard,
  ComplianceStandardVersion,
} from "./types";

const ORG_ID = "org-1";
const BASE = `/api/v1/orgs/${ORG_ID}/modules/compliance`;

const SOURCE_STANDARD: ComplianceStandard = {
  id: "std-1", organization_id: ORG_ID, reference: "ISO-27001", name: "ISO 27001",
  description: "", issuing_organisation: "ISO", owner_id: "user-1", creator_id: "user-1",
  is_archived: false, archived_at: null, archived_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const TARGET_STANDARD: ComplianceStandard = {
  ...SOURCE_STANDARD, id: "std-2", reference: "SOC2", name: "SOC 2 Type II", issuing_organisation: "AICPA",
};
const TARGET_VERSION: ComplianceStandardVersion = {
  id: "ver-2", standard_id: "std-2", version_number: 1, version_label: "v1.0", status: "draft",
  effective_date: null, change_note: "", created_by: "user-1", published_at: null, published_by: null,
  retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const SOURCE_REQUIREMENT: ComplianceRequirement = {
  id: "req-1", standard_version_id: "ver-1", parent_requirement_id: null, reference: "A.5.1", name: "Access control",
  description: "", reasoning: "", sort_order: 0, created_by: "user-1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const TARGET_REQUIREMENT: ComplianceRequirement = {
  id: "req-2", standard_version_id: "ver-2", parent_requirement_id: null, reference: "CC6.1", name: "Logical access controls",
  description: "", reasoning: "", sort_order: 0, created_by: "user-1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const RELATIONSHIP_TYPES: ComplianceMappingRelationshipType[] = [
  { id: "mt-1", organization_id: ORG_ID, name: "Equivalent", sort_order: 0, implies_equivalence: true },
];

function mapping(overrides: Partial<ComplianceRequirementMapping> = {}): ComplianceRequirementMapping {
  return {
    id: "map-1", organization_id: ORG_ID, from_requirement_id: "req-1", to_requirement_id: "req-2",
    relationship_type_id: "mt-1", notes: "Cross-mapped during initial adoption.", created_by: "user-1",
    is_archived: false, archived_at: null, archived_by: null,
    created_at: "2026-02-01T00:00:00Z", updated_at: "2026-02-01T00:00:00Z", ...overrides,
  };
}

/**
 * Mocks the four read endpoints this modal loads on mount/selection change
 * (mappings for the source requirement, the org's relationship-type
 * vocabulary, the org's standards, then versions/requirements for whichever
 * standard/version the cascading picker currently has selected) plus the
 * three write endpoints (create/archive/unarchive a mapping) — enough to
 * exercise the full cascading standard -> version -> requirement picker and
 * the create/archive round trip described in this component's own
 * docstring.
 */
function mockMappingsApis(overrides: { mappings?: ComplianceRequirementMapping[] } = {}) {
  let mappings = overrides.mappings ?? [mapping()];

  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/mappings")) return mappings;
    if (path.includes("/mapping-relationship-types")) return RELATIONSHIP_TYPES;
    if (path.includes("/requirements")) {
      const versionId = path.split("/versions/")[1].split("/requirements")[0];
      if (versionId === "ver-2") return [TARGET_REQUIREMENT];
      return [];
    }
    if (path.includes("/versions")) {
      const standardId = path.split("/standards/")[1].split("/versions")[0];
      if (standardId === "std-2") return [TARGET_VERSION];
      return [];
    }
    if (path.includes("/standards?")) return [SOURCE_STANDARD, TARGET_STANDARD];
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/requirement-mappings")) {
      const payload = body as { from_requirement_id: string; to_requirement_id: string; relationship_type_id: string; notes?: string };
      const created = mapping({ id: "map-2", ...payload, notes: payload.notes ?? "" });
      mappings = [...mappings, created];
      return created;
    }
    if (path.endsWith("/archive")) {
      const id = path.split("/requirement-mappings/")[1].split("/archive")[0];
      mappings = mappings.map((m) => (m.id === id ? { ...m, is_archived: true } : m));
      return mappings.find((m) => m.id === id);
    }
    if (path.endsWith("/unarchive")) {
      const id = path.split("/requirement-mappings/")[1].split("/unarchive")[0];
      mappings = mappings.map((m) => (m.id === id ? { ...m, is_archived: false } : m));
      return mappings.find((m) => m.id === id);
    }
    throw new Error(`unmocked POST: ${path}`);
  });
}

const meta: Meta<typeof RequirementMappingsModal> = {
  title: "Modules/Compliance/RequirementMappingsModal",
  component: RequirementMappingsModal,
  args: { orgId: ORG_ID, standardId: "std-1", versionId: "ver-1", requirement: SOURCE_REQUIREMENT, onClose: fn() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof RequirementMappingsModal>;

export const ListsExistingMappingAndArchives: Story = {
  beforeEach: () => mockMappingsApis(),
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByRole("table")).toBeInTheDocument());
    // Scope to the table itself — "Equivalent" also appears as an
    // `<option>` in the "Add mapping" relationship-type `<select>` below.
    const table = within(body.getByRole("table"));
    await expect(table.getByText("Equivalent")).toBeInTheDocument();
    await expect(table.getByText("req-2")).toBeInTheDocument();
    await expect(table.getByText("Cross-mapped during initial adoption.")).toBeInTheDocument();

    await userEvent.click(table.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/requirement-mappings/map-1/archive`));
    await expect(await table.findByRole("button", { name: "Unarchive" })).toBeInTheDocument();
  },
};

export const EmptyStateShowsPlaceholder: Story = {
  beforeEach: () => mockMappingsApis({ mappings: [] }),
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("No mappings yet.")).toBeInTheDocument());
  },
};

export const CascadingPickerCreatesMapping: Story = {
  beforeEach: () => mockMappingsApis({ mappings: [] }),
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByLabelText("Target standard")).toBeInTheDocument());
    const addButton = body.getByRole("button", { name: "Add mapping" });
    await expect(addButton).toBeDisabled();

    await userEvent.selectOptions(body.getByLabelText("Target standard"), "std-2");
    await waitFor(() => expect(body.getByRole("option", { name: "v1.0" })).toBeInTheDocument());
    await userEvent.selectOptions(body.getByLabelText("Target version"), "ver-2");
    await waitFor(() => expect(body.getByRole("option", { name: "CC6.1 — Logical access controls" })).toBeInTheDocument());
    await userEvent.selectOptions(body.getByLabelText("Target requirement"), "req-2");
    await userEvent.selectOptions(body.getByLabelText("Relationship type"), "mt-1");
    await expect(addButton).toBeEnabled();

    await userEvent.type(body.getByLabelText("Notes"), "Direct equivalent.");
    await userEvent.click(addButton);

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${BASE}/requirement-mappings`,
      { from_requirement_id: "req-1", to_requirement_id: "req-2", relationship_type_id: "mt-1", notes: "Direct equivalent." }
    ));
    await waitFor(() => expect(body.getByText("Direct equivalent.")).toBeInTheDocument());
  },
};

export const LoadMappingsFailureShowsToast: Story = {
  beforeEach: () => {
    mockMappingsApis();
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/mappings")) throw new Error("Could not load mappings.");
      if (path.includes("/mapping-relationship-types")) return RELATIONSHIP_TYPES;
      if (path.includes("/standards?")) return [SOURCE_STANDARD, TARGET_STANDARD];
      throw new Error(`unmocked GET: ${path}`);
    });
  },
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Could not load mappings.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListsExistingMappingAndArchives };
export const DarkTheme: Story = { ...ListsExistingMappingAndArchives, globals: { theme: "dark" } };
