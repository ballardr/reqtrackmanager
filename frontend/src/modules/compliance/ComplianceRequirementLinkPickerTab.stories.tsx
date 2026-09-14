import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ComplianceRequirementLinkPickerTab } from "./ComplianceRequirementLinkPickerTab";
import type { ComplianceRequirement, ComplianceRequirementTraceabilityLink, ComplianceStandard, ComplianceStandardVersion } from "./types";

/**
 * The Compliance module's tab in the shared `RequirementLinkPickerModal`
 * (`components/RequirementLinkPickerModal.tsx`), registered via
 * `module.ts`'s `requirementLinkPickerTabs` — extracted from
 * `RequirementTraceabilityLinksSection.tsx`'s old inline "Add compliance
 * link" `Popover` (platform-review-2026-09 Phase 7) once link-creation
 * moved into the shared modal. Mounted directly, same "mock only what it
 * calls" convention as `RequirementTraceabilityLinksSection.stories.tsx`.
 */
const meta: Meta<typeof ComplianceRequirementLinkPickerTab> = {
  title: "Modules/Compliance/ComplianceRequirementLinkPickerTab",
  component: ComplianceRequirementLinkPickerTab,
  args: { projectId: "project-1", requirementId: "requirement-1", organizationId: "org-1", onLinked: fn() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ComplianceRequirementLinkPickerTab>;

const existingLink: ComplianceRequirementTraceabilityLink = {
  id: "link-1", requirement_id: "requirement-1", compliance_requirement_id: "creq-1", link_type_id: "lt-1",
  display_name: "Derives from", compliance_requirement_reference: "A.5.15", compliance_requirement_name: "Logical access control",
  standard_id: "standard-1", standard_reference: "ISO-27001", standard_name: "Corporate Security Standard",
  standard_version_id: "version-1", standard_version_label: "2.0", created_by: "user-1", created_at: "2026-01-01T00:00:00Z",
};

// Exercises the cascading standard -> version -> requirement picker end to
// end (`RequirementMappingsModal.tsx`'s own precedent for why this is
// cascading selects rather than a type-ahead search) plus the core
// `link-types` select, then confirms `onLinked` fires on success.
export const CascadingPickerCreatesLink: Story = {
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
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByLabelText("Standard"), "standard-1");
    await userEvent.selectOptions(await canvas.findByLabelText("Version"), "version-1");
    await userEvent.selectOptions(await canvas.findByLabelText("Requirement"), "creq-1");
    await userEvent.selectOptions(canvas.getByLabelText("Link type"), "lt-1");
    await userEvent.click(canvas.getByRole("button", { name: "Add link" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/projects/project-1/modules/compliance/requirements/requirement-1/traceability-links",
        { compliance_requirement_id: "creq-1", link_type_id: "lt-1" }
      )
    );
    await waitFor(() => expect(args.onLinked).toHaveBeenCalled());
  },
};

export const CreateFailureShowsInlineError: Story = {
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
      if (path.endsWith("/link-types")) return [{ id: "lt-1", organization_id: "org-1", forward_name: "Derives from", reverse_name: "Is the source of", sort_order: 0 }];
      if (path.endsWith("/standards/standard-1/versions")) return versions;
      if (path.endsWith("/versions/version-1/requirements")) return requirements;
      if (path.includes("/modules/compliance/standards")) return standards;
      throw new Error(`Unmocked path: ${path}`);
    });
    spyOn(api, "post").mockRejectedValue(new Error("A link to this requirement already exists."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByLabelText("Standard"), "standard-1");
    await userEvent.selectOptions(await canvas.findByLabelText("Version"), "version-1");
    await userEvent.selectOptions(await canvas.findByLabelText("Requirement"), "creq-1");
    await userEvent.selectOptions(canvas.getByLabelText("Link type"), "lt-1");
    await userEvent.click(canvas.getByRole("button", { name: "Add link" }));
    await waitFor(() => expect(canvas.getByText("A link to this requirement already exists.")).toBeInTheDocument());
  },
};
