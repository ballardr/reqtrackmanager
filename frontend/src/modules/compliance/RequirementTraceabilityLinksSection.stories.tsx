import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildLinkType, projectLinkTypesPayload, withRouter, withThemeProvider, withToast } from "../../testing/storybook-helpers";
import { RequirementTraceabilityLinksSection } from "./RequirementTraceabilityLinksSection";
import type { ComplianceRequirementTraceabilityLink } from "./types";

/**
 * Compliance's contribution to `pages/RequirementDetailPage.tsx`'s aside
 * (compliance-module-plan.md Phase 34), registered via `module.ts`'s
 * `requirementDetailSections` — mirrors `ComplianceProjectOverviewTiles.stories.tsx`'s
 * own "mount the module's contributed component directly, mock only what it calls"
 * convention rather than integrating through the full `RequirementDetailPage`
 * (whose own stories deliberately keep `enabled-modules` returning `[]` for most
 * stories). The section lists the requirement's links to standard requirements and
 * opens its own "Add" dialog (the cascading picker is covered by
 * `ComplianceRequirementLinkPickerTab.stories.tsx`).
 */
const meta: Meta<typeof RequirementTraceabilityLinksSection> = {
  title: "Modules/Compliance/RequirementTraceabilityLinksSection",
  component: RequirementTraceabilityLinksSection,
  args: { projectId: "project-1", requirementId: "requirement-1", organizationId: "org-1", refreshToken: 0 },
  decorators: [withRouter("/projects/project-1/requirements/requirement-1"), withToast(), withThemeProvider()],
};
export default meta;

type Story = StoryObj<typeof RequirementTraceabilityLinksSection>;

const existingLink: ComplianceRequirementTraceabilityLink = {
  id: "link-1", requirement_id: "requirement-1", compliance_requirement_id: "creq-1", link_type_id: "lt-1",
  display_name: "Derives from", compliance_requirement_reference: "A.5.15", compliance_requirement_name: "Logical access control",
  standard_id: "standard-1", standard_reference: "ISO-27001", standard_name: "Corporate Security Standard",
  standard_version_id: "version-1", standard_version_label: "2.0", created_by: "user-1", created_at: "2026-01-01T00:00:00Z",
};

export const Populated: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/traceability-links")) return [existingLink];
      throw new Error(`Unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Derives from")).toBeInTheDocument());
    await expect(canvas.getByText(/A\.5\.15 Logical access control/)).toBeInTheDocument();
    await expect(canvas.getByText(/Corporate Security Standard, v2\.0/)).toBeInTheDocument();
  },
};

export const NoLinksYet: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/traceability-links")) return [];
      throw new Error(`Unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No compliance requirement links yet.")).toBeInTheDocument());
  },
};

/** "Add link" opens the section's own dialog holding the cascading standard -> version -> requirement picker. */
export const AddOpensThePickerDialog: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/traceability-links")) return [];
      if (path.includes("/modules/compliance/standards")) return [];
      if (path.endsWith("/link-types")) return projectLinkTypesPayload([buildLinkType({ id: "lt-1", forward_name: "Derives from" })]);
      throw new Error(`Unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Add link" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Compliance requirement links" }));
    await expect(dialog.getByLabelText("Standard")).toBeInTheDocument();
    await expect(dialog.getByLabelText("Link type")).toBeInTheDocument();
  },
};
