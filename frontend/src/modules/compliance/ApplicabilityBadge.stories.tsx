import type { Meta, StoryObj } from "@storybook/react-vite";

import { ApplicabilityBadge } from "./ApplicabilityBadge";
import type { ProjectComplianceRequirement } from "./types";

function pcr(overrides: Partial<ProjectComplianceRequirement> = {}): ProjectComplianceRequirement {
  return {
    id: "pcr-1", project_compliance_id: "pc-1", requirement_id: "req-1",
    explicit_applicability: null, effective_applicability: "applicable", applicability_source: "explicit",
    justification: "", notes: "", compliance_status: "not_started", assessed_at: null, assessed_by: null,
    applicability_set_at: null, applicability_set_by: null, approval_state: "not_assessed",
    approval_decided_at: null, approval_decided_by: null, decision_note: "",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

/**
 * §9's own explicit, non-optional UI requirement: "The UI must clearly
 * distinguish: Explicitly set applicability, Applicability inherited from a
 * parent, An overridden inherited value." These three stories are the
 * concrete proof each state gets a genuinely distinct visual treatment, not
 * just a different label string — see this component's own docstring.
 */
const meta: Meta<typeof ApplicabilityBadge> = {
  title: "Modules/Compliance/ApplicabilityBadge",
  component: ApplicabilityBadge,
};
export default meta;

type Story = StoryObj<typeof ApplicabilityBadge>;

export const Explicit: Story = {
  args: { pcr: pcr({ applicability_source: "explicit", effective_applicability: "applicable" }) },
};

export const ExplicitNotApplicable: Story = {
  args: { pcr: pcr({ applicability_source: "explicit", effective_applicability: "not_applicable", explicit_applicability: "not_applicable", justification: "Not present in this product configuration." }) },
};

export const Inherited: Story = {
  args: { pcr: pcr({ applicability_source: "inherited", effective_applicability: "not_applicable" }) },
};

export const Overridden: Story = {
  args: { pcr: pcr({ applicability_source: "overridden", effective_applicability: "applicable", explicit_applicability: "applicable" }) },
};

export const AllStatesSideBySide: Story = {
  render: () => (
    <div style={{ display: "flex", gap: "0.5rem" }}>
      <ApplicabilityBadge pcr={pcr({ applicability_source: "explicit" })} />
      <ApplicabilityBadge pcr={pcr({ applicability_source: "inherited", effective_applicability: "not_applicable" })} />
      <ApplicabilityBadge pcr={pcr({ applicability_source: "overridden", explicit_applicability: "applicable" })} />
    </div>
  ),
};

export const LightTheme: Story = { ...AllStatesSideBySide };
export const DarkTheme: Story = { ...AllStatesSideBySide, globals: { theme: "dark" } };
