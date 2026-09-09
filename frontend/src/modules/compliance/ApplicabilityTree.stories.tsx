import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ApplicabilityTree } from "./ApplicabilityTree";
import type { ComplianceRequirement, ProjectComplianceRequirement } from "./types";

const ORG_ID = "org-1";
const PROJECT_ID = "proj-1";
const STANDARD_ID = "std-1";
const VERSION_ID = "ver-1";
const PC_ID = "pc-1";

function requirement(overrides: Partial<ComplianceRequirement> = {}): ComplianceRequirement {
  return {
    id: "req-1", standard_version_id: VERSION_ID, parent_requirement_id: null,
    reference: "4", name: "Environmental requirements", description: "", reasoning: "", sort_order: 0,
    created_by: "u1", clarification_count: 0, last_clarified_at: null, last_clarified_by: null, last_clarification_note: "",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

function pcr(overrides: Partial<ProjectComplianceRequirement> = {}): ProjectComplianceRequirement {
  return {
    id: "pcr-1", project_compliance_id: PC_ID, requirement_id: "req-1",
    explicit_applicability: null, effective_applicability: "applicable", applicability_source: "explicit",
    justification: "", notes: "", compliance_status: "in_progress", assessed_at: null, assessed_by: null,
    applicability_set_at: null, applicability_set_by: null, approval_state: "not_assessed",
    approval_decided_at: null, approval_decided_by: null, decision_note: "",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

/**
 * `ApplicabilityTree` proves §9's hierarchical-applicability requirement
 * end to end: a parent marked Not Applicable, a child inheriting that (no
 * explicit decision), and a sibling child explicitly overridden back to
 * Applicable — all three visible together, each with its own distinct
 * `ApplicabilityBadge` treatment (that component's own stories prove the
 * badge in isolation; this proves it wired to real tree data). Clicking a
 * row opens `RequirementAssessmentPanel` — its own nested fetches
 * (required actions, evidence) are mocked to resolve empty so drilling in
 * here settles cleanly; that panel's own deeper behaviour is covered in
 * `RequirementAssessmentPanel.stories.tsx`.
 */
function mockApis(requirements: ComplianceRequirement[], pcrs: ProjectComplianceRequirement[]) {
  let currentPcrs = pcrs;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/required-action-assessments")) return [];
    if (path.includes("/required-actions")) return [];
    if (path.endsWith("/evidence")) return [];
    if (path.includes(`/project-compliance/${PC_ID}/requirements`)) return currentPcrs;
    if (path.includes("/standards/") && path.includes("/requirements")) return requirements;
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/applicability")) {
      const id = path.split("/requirements/")[1].split("/applicability")[0];
      const payload = body as { applicability: "applicable" | "not_applicable"; justification: string };
      currentPcrs = currentPcrs.map((p) => (p.id === id ? { ...p, explicit_applicability: payload.applicability, effective_applicability: payload.applicability, applicability_source: "explicit", justification: payload.justification } : p));
      return currentPcrs.find((p) => p.id === id);
    }
    throw new Error(`unmocked PATCH: ${path}`);
  });
}

const meta: Meta<typeof ApplicabilityTree> = {
  title: "Modules/Compliance/ApplicabilityTree",
  component: ApplicabilityTree,
  decorators: [withToast()],
  args: { orgId: ORG_ID, projectId: PROJECT_ID, standardId: STANDARD_ID, versionId: VERSION_ID, projectComplianceId: PC_ID, orgUsers: [] },
};
export default meta;

type Story = StoryObj<typeof ApplicabilityTree>;

const REQUIREMENTS: ComplianceRequirement[] = [
  requirement({ id: "req-1", reference: "4", name: "Environmental requirements", parent_requirement_id: null }),
  requirement({ id: "req-2", reference: "4.1", name: "Temperature", parent_requirement_id: "req-1" }),
  requirement({ id: "req-3", reference: "4.2", name: "Water ingress", parent_requirement_id: "req-1" }),
];

const PCRS: ProjectComplianceRequirement[] = [
  pcr({ id: "pcr-1", requirement_id: "req-1", explicit_applicability: "not_applicable", effective_applicability: "not_applicable", applicability_source: "explicit", justification: "Indoor product only." }),
  pcr({ id: "pcr-2", requirement_id: "req-2", explicit_applicability: null, effective_applicability: "not_applicable", applicability_source: "inherited" }),
  pcr({ id: "pcr-3", requirement_id: "req-3", explicit_applicability: "applicable", effective_applicability: "applicable", applicability_source: "overridden", justification: "Still exposed to condensation." }),
];

export const HierarchicalApplicability: Story = {
  beforeEach: () => mockApis(REQUIREMENTS, PCRS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Environmental requirements")).toBeInTheDocument());
    await expect(canvas.getByText(/inherited/)).toBeInTheDocument();
    await expect(canvas.getByText(/overridden/)).toBeInTheDocument();
  },
};

export const OpenRequirementDetail: Story = {
  beforeEach: () => mockApis(REQUIREMENTS, PCRS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Environmental requirements")).toBeInTheDocument());
    await userEvent.click(canvas.getByText("Environmental requirements"));
    await waitFor(() => expect(within(document.body).getByRole("heading", { name: /Environmental requirements/ })).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...HierarchicalApplicability };
export const DarkTheme: Story = { ...HierarchicalApplicability, globals: { theme: "dark" } };
