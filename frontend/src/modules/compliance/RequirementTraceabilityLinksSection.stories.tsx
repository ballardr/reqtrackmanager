import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withThemeProvider, withToast } from "../../testing/storybook-helpers";
import { RequirementTraceabilityLinksSection } from "./RequirementTraceabilityLinksSection";
import type { ComplianceRequirementTraceabilityLink } from "./types";

/**
 * Compliance's contribution to `pages/RequirementDetailPage.tsx`'s own
 * Links card (compliance-module-plan.md Phase 34), registered via
 * `module.ts`'s `requirementDetailSections` — mirrors
 * `ComplianceProjectOverviewTiles.stories.tsx`'s own "mount the module's
 * contributed component directly, mock only what it calls" convention
 * rather than integrating through the full `RequirementDetailPage`
 * (whose own stories deliberately keep `enabled-modules` returning `[]` —
 * see that file's own comment).
 *
 * Platform-review-2026-09 Phase 7 trimmed this component to list/remove
 * only — the "add a link" picker now lives in
 * `ComplianceRequirementLinkPickerTab.tsx` (its own story file), reached
 * via the shared `RequirementLinkPickerModal` instead of a button on this
 * section. See that file's stories for the cascading-picker/create flow
 * this file's own `AddLink` story used to cover.
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

// `refreshToken` bumping (the signal the shared picker modal sends after
// adding a link from its own, separate component instance) must trigger a
// re-fetch. A prop change mid-`play` isn't a natural fit for this file's
// "mount once, mock, assert" story shape — the meaningful end-to-end proof
// that adding a compliance link from the picker modal actually refreshes
// this list is `tests/playwright/tests/modules/compliance/
// requirement-traceability-links.spec.ts`, which drives the real add flow
// through `RequirementDetailPage` and asserts the link appears here
// afterwards without a page reload.
