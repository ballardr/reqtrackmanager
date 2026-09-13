import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { RequirementTraceabilityLinksSection } from "./RequirementTraceabilityLinksSection";
import type { ComplianceRequirement, ComplianceRequirementTraceabilityLink, ComplianceStandard, ComplianceStandardVersion } from "./types";

/**
 * Compliance's contribution to `pages/RequirementDetailPage.tsx`'s own
 * Links card (compliance-module-plan.md Phase 34), registered via
 * `module.ts`'s `requirementDetailSections` — mirrors
 * `ComplianceProjectOverviewTiles.stories.tsx`'s own "mount the module's
 * contributed component directly, mock only what it calls" convention
 * rather than integrating through the full `RequirementDetailPage`
 * (whose own stories deliberately keep `enabled-modules` returning `[]` —
 * see that file's own comment).
 */
const meta: Meta<typeof RequirementTraceabilityLinksSection> = {
  title: "Modules/Compliance/RequirementTraceabilityLinksSection",
  component: RequirementTraceabilityLinksSection,
  args: { projectId: "project-1", requirementId: "requirement-1", organizationId: "org-1" },
  decorators: [withRouter("/projects/project-1/requirements/requirement-1"), withToast()],
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
      if (path.endsWith("/link-types")) return [];
      if (path.includes("/modules/compliance/standards")) return [];
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
      if (path.endsWith("/link-types")) return [];
      if (path.includes("/modules/compliance/standards")) return [];
      throw new Error(`Unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No compliance requirement links yet.")).toBeInTheDocument());
  },
};

// Exercises the cascading standard -> version -> requirement picker end to
// end (`RequirementMappingsModal.tsx`'s own precedent for why this is
// cascading selects rather than a type-ahead search) plus the core
// `link-types` select, then confirms the newly created link renders.
export const AddLink: Story = {
  beforeEach: () => {
    const standards: ComplianceStandard[] = [
      {
        id: "standard-1", organization_id: "org-1", reference: "ISO-27001", name: "Corporate Security Standard",
        description: "", issuing_organisation: null, owner_id: "user-1", creator_id: "user-1", is_archived: false,
        archived_at: null, archived_by: null, applicability_default: "opt_in", created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];
    const versions: ComplianceStandardVersion[] = [
      {
        id: "version-1", standard_id: "standard-1", version_number: 1, version_label: "2.0", status: "published",
        effective_date: null, change_note: "", summary: "", created_by: "user-1", published_at: "2026-01-01T00:00:00Z",
        published_by: "user-1", retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      },
    ];
    const requirements: ComplianceRequirement[] = [
      {
        id: "creq-1", standard_version_id: "version-1", parent_requirement_id: null, reference: "A.5.15",
        name: "Logical access control", description: "", reasoning: "", sort_order: 0, created_by: "user-1",
        clarification_count: 0, last_clarified_at: null, last_clarified_by: null, last_clarification_note: "",
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      },
    ];
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/traceability-links")) return [];
      if (path.endsWith("/link-types")) return [{ id: "lt-1", organization_id: "org-1", forward_name: "Derives from", reverse_name: "Is the source of", sort_order: 0 }];
      // More specific paths (versions/requirements) must be checked before
      // the broader `/modules/compliance/standards` substring match below,
      // since `/standards/standard-1/versions` also contains that substring.
      if (path.endsWith("/standards/standard-1/versions")) return versions;
      if (path.endsWith("/versions/version-1/requirements")) return requirements;
      if (path.includes("/modules/compliance/standards")) return standards;
      throw new Error(`Unmocked path: ${path}`);
    });
    spyOn(api, "post").mockResolvedValue(existingLink);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add compliance link" }));

    // Popover portals to `document.body`, outside `canvasElement`'s own
    // subtree — same pattern as `RequirementDetailPage.stories.tsx`'s own
    // "AddLink" story.
    const popover = within(document.body).getByRole("dialog", { name: "Add compliance link" });
    await userEvent.selectOptions(within(popover).getByLabelText("Standard"), "standard-1");
    await userEvent.selectOptions(await within(popover).findByLabelText("Version"), "version-1");
    await userEvent.selectOptions(await within(popover).findByLabelText("Requirement"), "creq-1");
    await userEvent.selectOptions(within(popover).getByLabelText("Link type"), "lt-1");
    await userEvent.click(within(popover).getByRole("button", { name: "Add link" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/projects/project-1/modules/compliance/requirements/requirement-1/traceability-links",
        { compliance_requirement_id: "creq-1", link_type_id: "lt-1" }
      )
    );
    // A successful add closes the popover (mirrors `RequirementDetailPage
    // .stories.tsx`'s own "AddLink" story).
    await waitFor(() => expect(within(document.body).queryByRole("dialog", { name: "Add compliance link" })).not.toBeInTheDocument());
  },
};
