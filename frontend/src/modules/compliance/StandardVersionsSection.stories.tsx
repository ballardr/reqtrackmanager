import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { StandardVersionsSection } from "./StandardVersionsSection";
import type { ComplianceActionType, ComplianceStandard, ComplianceStandardVersion } from "./types";

const ORG_ID = "org-1";
const STANDARD: ComplianceStandard = {
  id: "std-1", organization_id: ORG_ID, reference: "ISO-27001", name: "ISO 27001",
  description: "", issuing_organisation: null, owner_id: "user-1", creator_id: "user-1",
  is_archived: false, archived_at: null, archived_by: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const ACTION_TYPES: ComplianceActionType[] = [{ id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 }];

function version(overrides: Partial<ComplianceStandardVersion> = {}): ComplianceStandardVersion {
  return {
    id: "ver-1", standard_id: STANDARD.id, version_number: 1, version_label: "v1.0", status: "draft",
    effective_date: null, change_note: "", created_by: "user-1", published_at: null, published_by: null,
    retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function mockVersionApis(versions: ComplianceStandardVersion[] = [version()]) {
  let current = versions;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/requirements") && !path.includes("required-actions")) return [];
    if (path.includes("/required-actions")) return [];
    if (path.includes("/versions")) return current;
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.includes("/versions") && !path.includes("/publish") && !path.includes("/retire")) {
      const payload = body as { version_label: string; change_note: string; clone_from_version_id: string | null };
      const created = version({ id: "ver-new", version_label: payload.version_label, change_note: payload.change_note });
      current = [...current, created];
      return created;
    }
    throw new Error(`unmocked POST: ${path}`);
  });
}

/**
 * `StandardVersionsSection` — the "Versions" content of `StandardWorkspacePage
 * .tsx` (docs/compliance-module-plan.md Phase 18), extracted from
 * `StandardsPanel.tsx`'s old `SidePanel`/`VersionWorkspace` drill-in.
 * `VersionWorkspace`'s own publish/retire/requirement-tree behaviour is
 * covered by `VersionWorkspace.stories.tsx`, not duplicated here.
 */
const meta: Meta<typeof StandardVersionsSection> = {
  title: "Modules/Compliance/StandardVersionsSection",
  component: StandardVersionsSection,
  args: { orgId: ORG_ID, standard: STANDARD, actionTypes: ACTION_TYPES },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof StandardVersionsSection>;

export const ListsVersions: Story = {
  beforeEach: () => mockVersionApis([version(), version({ id: "ver-2", version_label: "v1.1", version_number: 2 })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "v1.0" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "v1.1" })).toBeInTheDocument();
  },
};

export const CreateVersionClonedFromExisting: Story = {
  beforeEach: () => mockVersionApis([version(), version({ id: "ver-2", version_label: "v1.1", version_number: 2 })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByRole("button", { name: "v1.0" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "New version" }));
    await userEvent.type(body.getByLabelText("Version label"), "v2.0");
    await userEvent.selectOptions(body.getByLabelText("Clone requirements from"), "v1.1");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/${STANDARD.id}/versions`,
      { version_label: "v2.0", effective_date: null, change_note: "", clone_from_version_id: "ver-2" }
    ));
  },
};

export const DrillIntoVersionOpensWorkspace: Story = {
  beforeEach: () => mockVersionApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "v1.0" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "v1.0" }));

    await waitFor(() => expect(canvas.getByRole("button", { name: "← Back to ISO 27001" })).toBeInTheDocument());
    await expect(canvas.getByText("ISO-27001 — v1.0")).toBeInTheDocument();
  },
};
